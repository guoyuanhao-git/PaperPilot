import copy
import json
from pathlib import Path
from unittest.mock import patch
import unittest
import test_core
from paperpilot import hf_topics, user_profile, store


class HfTopics(unittest.TestCase):
    setUp=test_core.Core.setUp
    tearDown=test_core.Core.tearDown
    wait_job=test_core.Core.wait_job

    def listing(self,n=12):
        return store.save('hf_listing',{'id':'listing','items':[{'id':str(i),'title':'Robot control '+str(i),
            'abstract':'A robot learns manipulation with efficient policies.','paper_url':'https://arxiv.org/abs/2601.00001'} for i in range(n)]})

    def response(self,c,system,messages,**kwargs):
        self.assertEqual(c['codex_reasoning_effort'],'low')
        self.assertEqual(c['deepseek']['thinking'],'disabled')
        rows=json.loads(messages[0]['content'].split('\n上次')[0])
        return {'value':{'papers':[{'id':r['id'],'relevant':True,
                                   'reason':'提供机器人策略中的轻量计算模块。'} for r in rows]},'usage':{'output_tokens':20}}

    def test_batches_cache_reuse_and_source_records_unchanged(self):
        listing=self.listing();before=copy.deepcopy(listing)
        user_profile.save({'research_directions':'机器人与模型架构'})
        with patch('paperpilot.providers.generate',side_effect=self.response) as model:
            result=hf_topics.classify(listing,lambda _:None)
            self.assertEqual(model.call_count,2)
            self.assertEqual(result['classified_count'],12)
            hf_topics.classify(listing,lambda _:None);self.assertEqual(model.call_count,2)
            config=store.settings();config['provider']='deepseek'
            with patch('paperpilot.store.settings',return_value=config):hf_topics.classify(listing,lambda _:None)
            self.assertEqual(model.call_count,2)
            listing['items'].append({'id':'new','title':'New paper','abstract':'New abstract'})
            hf_topics.classify(listing,lambda _:None);self.assertEqual(model.call_count,3)
        self.assertEqual(store.get('hf_listing','listing'),before)
        self.assertNotIn('classification',store.get('hf_listing','listing')['items'][0])

    def test_empty_profile_no_inferred_relevance_and_profile_change_invalidates(self):
        listing=self.listing(1)
        with patch('paperpilot.providers.generate',side_effect=self.response):result=hf_topics.classify(listing,lambda _:None)
        self.assertFalse(result['items'][0]['classification']['relevant'])
        self.assertEqual(result['items'][0]['classification']['reason'],'')
        user_profile.save({'research_directions':'具身智能'})
        self.assertEqual(hf_topics.view(listing)['classified_count'],0)
        with patch('paperpilot.providers.generate',side_effect=self.response):result=hf_topics.classify(listing,lambda _:None)
        self.assertTrue(result['items'][0]['classification']['relevant'])
        listing['items'][0]['abstract']='Changed evidence'
        self.assertEqual(hf_topics.view(listing)['classified_count'],0)

    def test_invalid_output_repaired_once_no_fabricated_papers(self):
        listing=self.listing(1)
        bad={'value':{'papers':[{'id':'invented','relevant':True,'reason':'Wrong'}]}}
        with patch('paperpilot.providers.generate',return_value=bad) as model:
            with self.assertRaises(ValueError):hf_topics.classify(listing,lambda _:None)
            self.assertEqual(model.call_count,2)
        self.assertEqual(hf_topics.view(listing)['classified_count'],0)
        valid={'id':'0','relevant':False,'reason':''}
        for changed in ({'relevant':'true'},{'reason':None},{'relevant':True,'reason':''}):
            with self.assertRaises(ValueError):hf_topics.validate({'papers':[{**valid,**changed}]},{'0'})

    def test_partial_failure_keeps_completed_batches_and_resume(self):
        listing=self.listing()
        def fail(c,s,m,**kw):
            if json.loads(m[0]['content'])[0]['id']=='10':raise ValueError('Network failed')
            return self.response(c,s,m,**kw)
        with patch('paperpilot.providers.generate',side_effect=fail):
            with self.assertRaises(ValueError):hf_topics.classify(listing,lambda _:None)
        self.assertEqual(hf_topics.view(listing)['classified_count'],10)
        with patch('paperpilot.providers.generate',side_effect=self.response) as model:
            result=hf_topics.classify(listing,lambda _:None)
            self.assertEqual(model.call_count,1);self.assertEqual(result['classified_count'],12)

    def test_accounts_and_source_boundary(self):
        listing=self.listing(1)
        user_profile.save({'research_directions':'机器人'})
        with patch('paperpilot.providers.generate',side_effect=self.response):hf_topics.classify(listing,lambda _:None)
        with store.scope({'directory':Path(self.tmp.name)/'another'}):
            store.init();self.assertEqual(hf_topics.cache(),{})
            with self.assertRaises(ValueError):hf_topics.start('listing')
        with self.assertRaises(ValueError):hf_topics.start('forged')
        with patch('paperpilot.providers.generate',side_effect=self.response) as model:
            job=self.wait_job(hf_topics.start('listing'))
            self.assertEqual(job['status'],'completed');model.assert_not_called()

    def test_profile_edit_during_generation_and_input_budget(self):
        listing=self.listing(1)
        def edit(*args,**kwargs):
            result=self.response(*args,**kwargs)
            user_profile.save({'research_directions':'changed'})
            return result
        with patch('paperpilot.providers.generate',side_effect=edit):
            with self.assertRaisesRegex(ValueError,'研究方向或主线已修改'):hf_topics.classify(listing,lambda _:None)
        self.assertEqual(hf_topics.cache(),{})
        config=store.settings();config['context_chars']=4000
        with patch('paperpilot.store.settings',return_value=config),patch('paperpilot.providers.generate') as model:
            with self.assertRaisesRegex(ValueError,'上限'):hf_topics.classify(listing,lambda _:None)
            model.assert_not_called()

    def test_mainline_only_supported_and_details_invalidate_cache(self):
        listing = self.listing(1)
        user_profile.save({'mainlines': [{'title': '机器人闭环控制', 'detail': '降低执行时延'}]})
        def generate(c, system, messages, **kwargs):
            self.assertIn('降低执行时延', system)
            self.assertNotIn('topics', json.dumps(kwargs['schema']))
            return self.response(c, system, messages, **kwargs)
        with patch('paperpilot.providers.generate', side_effect=generate):
            result = hf_topics.classify(listing, lambda _: None)
        self.assertTrue(result['items'][0]['classification']['relevant'])
        user_profile.save({'mainlines': [{'title': '机器人闭环控制', 'detail': '提高触觉精度'}]})
        self.assertEqual(hf_topics.view(listing)['classified_count'], 0)

    def test_empty_profile_start_does_not_schedule_model(self):
        self.listing(1)
        with patch('paperpilot.service.job') as start:
            with self.assertRaisesRegex(ValueError, '填写研究方向或研究主线'):
                hf_topics.start('listing')
            start.assert_not_called()
