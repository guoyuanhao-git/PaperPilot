import copy
import unittest
from unittest.mock import patch
import test_core
from paperpilot import daily, daily_filter, store, user_profile


def passthrough(rows):
    return [{**{k:v for k,v in a.items() if k!='selection_text'},'selection_reason':'测试入选理由'} for a in rows], {'ok':True,'context_signature':daily_filter.context_signature()[0]}


class DailyFilter(unittest.TestCase):
    def setUp(self):
        test_core.Core.setUp(self)
        metadata_patcher=patch('paperpilot.news_metadata.resolve',return_value={});metadata_patcher.start();self.addCleanup(metadata_patcher.stop)
    tearDown=test_core.Core.tearDown

    def test_disabled_news_exposes_no_cache_and_makes_no_remote_calls(self):
        original = {'id': 'latest', 'items': [{'id': 'private-cached-paper'}], 'articles': [{'title': 'cached'}]}
        store.save('daily', original)
        config = store.settings()
        config['hotspot_news_enabled'] = False
        store.save_settings(config)
        with patch('paperpilot.providers.generate') as model, patch.object(daily, 'articles') as fetch:
            for action in (lambda: daily.refresh(True), lambda: daily.collect(), lambda: daily_filter.select(self.rows())):
                with self.assertRaisesRegex(ValueError, '已关闭'):
                    action()
            self.assertEqual(daily.cached()['articles'], [])
            self.assertEqual(daily.cached()['items'], [])
            self.assertFalse(daily.cached()['stale'])
            model.assert_not_called()
            fetch.assert_not_called()
        self.assertEqual(store.get('daily', 'latest'), original)

    def test_disabled_during_refresh_does_not_publish_results(self):
        original = {'id': 'latest', 'items': [], 'articles': [], 'source_status': [], 'updated_at': None}
        store.save('daily', original)
        def collect():
            config = store.settings()
            config['hotspot_news_enabled'] = False
            store.save_settings(config)
            return {'items': [], 'articles': [{'title': 'late response'}], 'source_status': []}
        with patch.object(daily, 'collect', side_effect=collect):
            with self.assertRaisesRegex(ValueError, '已关闭'):
                daily.refresh(True)
        self.assertEqual(store.get('daily', 'latest'), original)

    def test_news_uses_managed_light_level_for_both_providers(self):
        for provider in ('codex', 'deepseek'):
            config = store.settings()
            config['provider'] = provider
            config['reasoning_policy'] = {'custom_enabled': True, 'overrides': {'knowledge': 'high'}}
            store.save_settings(config)
            routed = daily_filter.context_signature()[2]
            self.assertEqual(routed['codex_reasoning_effort'], 'low')
            self.assertEqual(routed['deepseek']['thinking'], 'disabled')

    def rows(self):
        return [{'title':title,'source':'qbitai','source_url':'https://www.qbitai.com/'+str(i),
                 'channel':'website','published':daily.utcnow().isoformat(),'selection_text':body} for i,(title,body) in enumerate([
                     ('布料数据研究','论文介绍与数据集'),('报名活动','付费峰会报名'),('有价值的工具','开源仿真代码')])]

    def generate(self, config, system, messages, **kwargs):
        import json
        rows=json.loads(messages[0]['content'])['candidates']
        return {'value':{'decisions':[{'id':r['id'],'keep':r['title']!='报名活动','score':75,'reason':'研究信息' if r['title']!='报名活动' else '活动营销'} for r in rows]},'usage':{},'provider':'test','model':'test'}

    def test_model_filter_cache_profile_change_and_new_content(self):
        with patch('paperpilot.providers.generate',side_effect=self.generate) as gen:
            rows=self.rows();selected,status=daily_filter.select(rows)
            self.assertEqual(len(selected),2);self.assertEqual(status['reviewed'],3)
            self.assertNotIn('selection_text',selected[0]);self.assertTrue(selected[0]['selection_reason'])
            daily_filter.select(rows);self.assertEqual(gen.call_count,1)
            changed=copy.deepcopy(rows);changed[0]['selection_text']+=' 新增实验'
            daily_filter.select(changed);self.assertEqual(gen.call_count,2)
            user_profile.save({'mainline':'新的研究问题'})
            daily_filter.select(changed);self.assertEqual(gen.call_count,3)
            config=store.settings();config['provider']='deepseek';store.save_settings(config)
            daily_filter.select(changed);self.assertEqual(gen.call_count,4)

    def test_invalid_output_and_failure_never_publish_unreviewed_articles(self):
        with patch('paperpilot.providers.generate',return_value={'value':{'decisions':[{'id':'invented','keep':True,'reason':'Fake'}]}}):
            selected,status=daily_filter.select(self.rows())
        self.assertEqual(selected,[]);self.assertFalse(status['ok'])
        with patch('paperpilot.providers.generate',side_effect=self.generate):daily_filter.select(self.rows()[:1])
        with patch('paperpilot.providers.generate',side_effect=ValueError('bad secret must not be exposed')):
            selected,status=daily_filter.select(self.rows())
        self.assertEqual(len(selected),1);self.assertFalse(status['ok']);self.assertNotIn('secret',status['message'])

    def test_only_selected_articles_contribute_papers(self):
        rows=self.rows()[:2]
        for r in rows:r['body']='https://arxiv.org/abs/2610.00001'
        with (patch.object(daily,'OUTLETS',('qbitai',)),patch.object(daily,'articles',return_value=(rows,'官网')),
              patch('paperpilot.providers.generate',side_effect=self.generate),patch.object(daily,'metadata',return_value={})):
            result=daily.collect()
        self.assertEqual(len(result['articles']),1)
        self.assertEqual(len(result['items'][0]['reports']),1)
        self.assertEqual(result['items'][0]['reports'][0]['title'],'布料数据研究')

    def test_website_preferred_and_labeled_rss_fallback(self):
        rows=self.rows()
        with (patch('paperpilot.daily_sources.website_articles',return_value=(rows,'官网')),
             patch.object(daily,'wechat_articles',side_effect=AssertionError('Website worked'))):
            result,_=daily.articles('qbitai',daily.utcnow())
        self.assertTrue(all(r['channel']=='website' for r in result))
        with (patch('paperpilot.daily_sources.website_articles',side_effect=ValueError('Unavailable')),
             patch.object(daily,'wechat_articles',return_value=([], 'RSS latest yesterday'))):
            _,coverage=daily.articles('jiqizhixin',daily.utcnow())
        self.assertIn('官网暂不可读',coverage)
