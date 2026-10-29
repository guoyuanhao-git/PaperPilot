import json
import threading
import unittest
import urllib.request
import urllib.error
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import test_core
from paperpilot import store, user_profile, assistant_memory as memory, discovery, service, providers
from paperpilot.server import Handler, TOKEN


class ProfileMemorySources(unittest.TestCase):
    setUp = test_core.Core.setUp
    tearDown = test_core.Core.tearDown
    wait_job = test_core.Core.wait_job

    def test_cool_filter_date_or_queries_dedup_and_saved_source(self):
        today = datetime.now(timezone.utc).date().isoformat()
        def item(ident, published):
            return {'id':'cool-'+ident,'title':'World action models','abstract':'Evidence',
                'source':'papers_cool','kind':'paper','paper_url':'https://arxiv.org/abs/'+ident,
                'source_url':'https://papers.cool/arxiv/'+ident,'published':published}
        recent = item('2608.00001',today)
        with patch('paperpilot.discovery.public_fetch', return_value='HTML') as fetch, \
             patch('paperpilot.title_search.cool_items', side_effect=[[recent,item('2001.00001','2020-01-01')],[recent,item('2608.00002',today)]]):
            rows=discovery.feed('papers_cool','all:"world action model" OR all:"cloth manipulation"',7,5)
        self.assertEqual([r['id'] for r in rows],['2608.00001','2608.00002'])
        self.assertIn('query=world+action+model',fetch.call_args_list[0].args[0])
        self.assertIn('query=cloth+manipulation',fetch.call_args_list[1].args[0])
        config=store.settings();config['discovery_sources']=['papers_cool'];store.save_settings(config)
        self.assertEqual(store.settings()['discovery_sources'],['papers_cool'])
        self.assertEqual(discovery.validate_search_sources(['papers_cool']),['papers_cool'])
        with patch('paperpilot.discovery.feed',side_effect=[rows,[dict(recent,id='2608.00001')]]):
            merged,_=discovery.collect(['papers_cool','arxiv'],'test',7)
        self.assertEqual(len(merged),2)

    def test_cool_chinese_request_is_translated_before_lookup(self):
        p={'id':'2608.00001','source':'papers_cool','kind':'paper','title':'World action models','abstract':'Evidence','paper_url':'https://arxiv.org/abs/2608.00001'}
        translation={'value':{'query':'all:"cloth manipulation"'},'usage':{}}
        recommendation={'value':{'recommendations':[{'id':p['id'],'reason':'Relevant','taste':'Clear','tracking':'Useful'}]},'usage':{},'provider':'fixture','model':'fixture'}
        with patch('paperpilot.discovery.collect',return_value=([p],[])) as collect, \
             patch('paperpilot.providers.generate',side_effect=[translation,recommendation]):
            job=self.wait_job(service.recommend('布料操作',sources=['papers_cool'],count=1))
        self.assertEqual(job['status'],'completed',job.get('error'))
        self.assertEqual(collect.call_args.args[3],'all:"cloth manipulation"')
        self.assertEqual(job['result']['recommendations'][0]['paper_url'],p['paper_url'])

    def test_gender_selection_roundtrip_and_legacy_profile(self):
        user_profile.save({'display_name': '原有称呼'})
        self.assertEqual(user_profile.get()['gender'], '')
        for value in ('男', '女', '秘密', ''):
            profile = user_profile.get()
            profile['gender'] = value
            user_profile.save(profile)
            self.assertEqual(user_profile.get()['gender'], value)
            self.assertEqual(user_profile.get()['display_name'], '原有称呼')
        with self.assertRaises(ValueError):
            user_profile.save({'gender': '未知'})

    def test_manual_profile_is_blank_not_inferred_and_drives_prompts(self):
        (store.DATA / 'profile.md').write_text('LEGACY_PROFILE_DO_NOT_INJECT')
        self.assertTrue(all(not v for v in user_profile.get().values()))
        self.assertNotIn('LEGACY_PROFILE', service.system_prompt())
        p = user_profile.save({'education': '数学本科', 'research_directions': '图学习', 'personal_statement': '我更关注可解释性', 'mainline': '图神经网络'})
        self.assertEqual(user_profile.get(), p)
        for value in ('数学本科', '图学习', '我更关注可解释性', '图神经网络'):
            self.assertIn(value, service.system_prompt())
        user_profile.save({})
        self.assertNotIn('数学本科', service.system_prompt())
        with self.assertRaises(ValueError):
            user_profile.save({'mainline': '长' * 101})

    def test_multiple_mainlines_legacy_preservation_limits_and_context(self):
        legacy = user_profile.save({'mainline': '原有主线', 'mainline_detail': '原有补充'})
        self.assertEqual(legacy['mainlines'], [{'title': '原有主线', 'detail': '原有补充'}])
        value = user_profile.save({'mainlines': [{'title': '动作模型', 'detail': '字'*320}, {'title': '柔体仿真', 'detail': '数据生成'}, {'title': '条件建模', 'detail': '表示学习'}]})
        self.assertEqual(len(user_profile.get()['mainlines']), 3)
        self.assertEqual(value['mainline'], '动作模型')
        for title in ('动作模型', '柔体仿真', '条件建模'):
            self.assertIn(title, service.system_prompt())
        from paperpilot import knowledge
        self.assertIn('条件建模', knowledge.research_context()['mainlines'])
        user_profile.save_display({'display_name': '显示名称', 'gender': ''})
        self.assertEqual(user_profile.get()['mainlines'], value['mainlines'])
        with self.assertRaisesRegex(ValueError, '三条'):
            user_profile.save({'mainlines': [{'title': 'a'}]*4})
        with self.assertRaisesRegex(ValueError, '320'):
            user_profile.save({'mainlines': [{'title': 'a', 'detail': '字'*321}]})
        # Legacy clients may edit the first line while preserving later entries.
        edited = user_profile.save({**user_profile.get(), 'mainline': '第一条修改'})
        self.assertEqual(edited['mainlines'][0]['title'], '第一条修改')
        self.assertEqual(edited['mainlines'][2]['title'], '条件建模')
        self.assertEqual(user_profile.save({'mainlines': []})['mainline'], '')

    def test_memory_switch_revisions_clear_and_inflight_invalidation(self):
        memory.capture('目标', 'OFF_SHOULD_NOT_SAVE', schedule=False)
        self.assertEqual(store.all_objects('memory_event'), [])
        memory.configure(True)
        memory.capture('论文反馈', 'OLD_OPINION', 'paper', 'Title', schedule=False)
        events = store.all_objects('memory_event')
        evidence = events[0]['id']
        response = {'value': {'observations': [{'text': 'OLD_OPINION', 'evidence_ids': [evidence]}]}}
        with patch('paperpilot.providers.generate', return_value=response):
            memory.summarize(store.settings(), memory.state()['epoch'], events)
        self.assertIn('OLD_OPINION', memory.context())
        memory.capture('论文反馈', 'NEW_OPINION', 'paper', 'Title', schedule=False)
        self.assertNotIn('OLD_OPINION', memory.context())
        self.assertIn('NEW_OPINION', memory.context())
        memory.configure(False)
        memory.capture('目标', 'ALSO_OFF', schedule=False)
        self.assertEqual(memory.context(), '')
        self.assertEqual(len(store.all_objects('memory_event')), 1)
        memory.configure(True)
        epoch = memory.state()['epoch']
        def finish_after_clear(*args, **kwargs):
            memory.clear()
            return response
        with patch('paperpilot.providers.generate', side_effect=finish_after_clear):
            memory.summarize(store.settings(), epoch, store.all_objects('memory_event'))
        self.assertEqual(memory.state()['observations'], [])
        self.assertEqual(store.all_objects('memory_event'), [])
        self.assertNotIn('OPINION', memory.context())

    def test_memory_forget_and_evidence_validation(self):
        memory.configure(True)
        memory.capture('个人思考', 'PRIVATE_NOTE', 'paper', schedule=False)
        bad = {'value': {'observations': [{'text': 'Unsupported', 'evidence_ids': ['invented']}]}}
        with patch('paperpilot.providers.generate', return_value=bad):
            memory.summarize(store.settings(), memory.state()['epoch'], store.all_objects('memory_event'))
        self.assertEqual(memory.state()['observations'], [])
        self.assertTrue(memory.status()['error'])
        memory.forget_paper('paper')
        self.assertNotIn('PRIVATE_NOTE', memory.context())

    def test_memory_batches_three_changes_and_throttles(self):
        memory.configure(True)
        with patch('paperpilot.assistant_memory.WORKER.submit') as submit:
            memory.capture('目标', 'a')
            memory.capture('目标', 'b')
            submit.assert_not_called()
            memory.capture('目标', 'c')
            self.assertEqual(submit.call_count, 1)
            memory.capture('目标', 'd')
            self.assertEqual(submit.call_count, 1)
            s = memory.state(); s['running'] = False; store.save('assistant_memory', s)
            memory.maybe_update()
            self.assertEqual(submit.call_count, 1)

    def test_source_parsers_keep_evidence_and_reject_unsafe_links(self):
        rss = '<rss><channel><item><title>标题</title><link>https://www.qbitai.com/2026/10/1.html</link><description>&lt;b&gt;摘要&lt;/b&gt;</description><pubDate>Mon, 12 Oct 2026 05:48:36 +0000</pubDate></item><item><title>Bad</title><link>javascript:alert(1)</link></item></channel></rss>'
        rows = discovery.rss_items(rss, 'qbitai')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['abstract'], '摘要')
        self.assertEqual(rows[0]['kind'], 'news')
        with self.assertRaises(ValueError):
            discovery.rss_items('<html>数据服务</html>', 'jiqizhixin')
        hf = discovery.hf_items(json.dumps([{'paper': {'id': '2210.02747', 'title': 'Test', 'summary': 'Summary', 'publishedAt': '2026-10-12T00:00:00Z', 'authors': [{'name': 'Someone'}]}}]))
        self.assertEqual(hf[0]['paper_url'], 'https://arxiv.org/abs/2210.02747')
        self.assertIn('huggingface.co', hf[0]['source_url'])
        raw = 'var FEED=' + json.dumps([['12:00', '12/31', '标题', '摘要', '新智元', 'tg123', 1], ['12:00', '01/01', 'Other', '摘要', 'Other outlet', 'other', 0]]) + '; executeMaliciousCode()'
        aiera = discovery.aiera_items(raw, datetime(2026, 1, 2, tzinfo=timezone.utc))
        self.assertEqual(len(aiera), 1)
        self.assertTrue(aiera[0]['published'].startswith('2025-12-31'))
        self.assertTrue(aiera[0]['date_inferred'])
        with self.assertRaises(ValueError):
            discovery.validate_sources([])
        with self.assertRaises(ValueError):
            discovery.public_fetch('http://localhost', {'localhost'})

    def test_source_failure_does_not_mask_other_results(self):
        def feed(source, *args):
            if source == 'jiqizhixin':
                raise ValueError('数据服务权限')
            return [{'id': source, 'source': source}]
        with patch('paperpilot.discovery.feed', side_effect=feed):
            candidates, status = discovery.collect(['qbitai', 'jiqizhixin', 'huggingface'], 'query', 30)
        self.assertEqual({r['id'] for r in candidates}, {'qbitai', 'huggingface'})
        self.assertEqual([s['ok'] for s in status], [True, False, True])

    def test_hf_recommendation_keeps_verified_url_and_no_arxiv_translation(self):
        p = {'id': '2210.02747', 'source': 'huggingface', 'kind': 'paper', 'source_url': 'https://huggingface.co/papers/2210.02747', 'title': 'Test', 'abstract': 'fixture'}
        response = {'value': {'recommendations': [{'id': p['id'], 'reason': 'x', 'taste': 'y', 'tracking': 'z', 'source_url': 'https://invented.test'}]}, 'usage': {}, 'provider': 'fixture', 'model': 'fixture'}
        with patch('paperpilot.discovery.collect', return_value=([p], [{'source': 'qbitai', 'ok': True, 'count': 1}])) as collect, patch('paperpilot.providers.generate', return_value=response) as generate:
            job = self.wait_job(service.recommend('我想了解图学习', sources=['huggingface']))
        self.assertEqual(job['status'], 'completed', job.get('error'))
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(collect.call_args.args[0], ['huggingface'])
        self.assertEqual(job['result']['recommendations'][0]['source_url'], p['source_url'])
        with self.assertRaises(ValueError):
            service.recommend('test', sources=[])

    def test_http_profile_memory_private_and_provider_options(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        def post(path, value):
            req = urllib.request.Request(base + path, json.dumps(value).encode(), {'X-PaperPilot-Token': TOKEN})
            with urllib.request.urlopen(req) as response:
                return json.load(response)
        try:
            post('/api/profile-display', {'display_name': '测试用户', 'gender': ''})
            post('/api/profile', {'profile': {'personal_statement': '自己写的陈述'}})
            post('/api/memory', {'enabled': True})
            memory.capture('使用', 'PRIVATE_MEMORY_NEVER_IN_BOOTSTRAP', schedule=False)
            with urllib.request.urlopen(base + '/api/bootstrap') as response:
                raw = response.read().decode()
            self.assertNotIn('PRIVATE_MEMORY_NEVER_IN_BOOTSTRAP', raw)
            data = json.loads(raw)
            self.assertEqual(data['profile']['personal_statement'], '自己写的陈述')
            self.assertNotIn('openai', data['settings'])
            self.assertNotIn('openai', data['capabilities']['keys'])
            with self.assertRaises(urllib.error.HTTPError):
                post('/api/settings', {'provider': 'openai'})
            policy = {'custom_enabled': True, 'overrides': {'study': 'low', 'knowledge': 'high'}}
            saved = post('/api/settings', {'reasoning_policy': policy})['settings']
            self.assertEqual(saved['reasoning']['detailed'], 'low')
            self.assertEqual(saved['reasoning']['deep'], 'low')
            self.assertEqual(saved['reasoning']['memory'], 'medium')
            for invalid in ({'reasoning': {'memory': 'high'}},
                            {'reasoning_policy': {'custom_enabled': True, 'overrides': {'memory': 'high'}}},
                            {'reasoning_policy': {'custom_enabled': 'yes', 'overrides': {}}}):
                with self.assertRaises(urllib.error.HTTPError) as error:
                    post('/api/settings', invalid)
                self.assertEqual(error.exception.code, 400)
            self.assertEqual(store.settings()['reasoning_policy'], policy)
            saved = post('/api/settings', {'provider': 'deepseek', 'reasoning_policy': {**policy, 'custom_enabled': False}})['settings']
            self.assertEqual(saved['reasoning']['detailed'], 'high')
            self.assertEqual(saved['reasoning']['knowledge'], 'medium')
            self.assertEqual(saved['reasoning_policy']['overrides'], policy['overrides'])
            disabled = post('/api/settings', {'hotspot_news_enabled': False})['settings']
            self.assertFalse(disabled['hotspot_news_enabled'])
            with urllib.request.urlopen(base + '/api/bootstrap') as response:
                self.assertEqual(json.load(response)['daily']['items'], [])
            with self.assertRaises(urllib.error.HTTPError) as error:
                post('/api/daily-refresh', {'force': True})
            self.assertEqual(error.exception.code, 400)
            with patch('paperpilot.hf_daily.refresh', return_value={'items': [], 'days': 1}) as hf:
                self.assertEqual(post('/api/hf-list', {'days': 1})['items'], [])
                hf.assert_called_once()
            with self.assertRaises(urllib.error.HTTPError):
                post('/api/settings', {'hotspot_news_enabled': 'false'})
            self.assertFalse(store.settings()['hotspot_news_enabled'])
            post('/api/settings', {'hotspot_news_enabled': True})
            post('/api/settings', {'discovery_sources': ['arxiv', 'huggingface']})
            with self.assertRaises(urllib.error.HTTPError):
                post('/api/settings', {'discovery_sources': ['qbitai']})
            self.assertTrue(memory.enabled())
            post('/api/memory-clear', {})
            self.assertEqual(store.all_objects('memory_event'), [])
            self.assertEqual(user_profile.get()['display_name'], '测试用户')
        finally:
            server.shutdown(); server.server_close()


if __name__ == '__main__':
    unittest.main()
