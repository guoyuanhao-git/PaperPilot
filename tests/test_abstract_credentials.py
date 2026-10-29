import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch
import test_core
from paperpilot import abstracts, providers, credentials, store
from paperpilot.server import Handler, TOKEN


class AbstractCredentials(test_core.unittest.TestCase):
    setUp = test_core.Core.setUp
    tearDown = test_core.Core.tearDown
    wait_job = test_core.Core.wait_job

    def test_mask_identifies_active_key_with_actual_precedence(self):
        saved = 'sk-01234-secret-middle-wxyz'
        session = 'sk-98765-other-secret-abcd'
        credentials.save(saved)
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'sk-env12-middle-efgh'}):
            info = providers.capabilities(store.settings())['key_storage']['deepseek']
            self.assertEqual(info['masked'], 'sk-01234*****wxyz')
            self.assertEqual(info['source'], credentials.storage_kind())
            providers.KEYS['deepseek'] = session
            info = providers.capabilities(store.settings())['key_storage']['deepseek']
            self.assertEqual(info['masked'], 'sk-98765*****abcd')
            self.assertEqual(info['source'], 'session')
            self.assertEqual(providers.api_key('deepseek'), session)
            self.assertNotIn(session, json.dumps(info))
            providers.KEYS.clear(); credentials.delete()
            self.assertEqual(providers.capabilities(store.settings())['key_storage']['deepseek']['masked'], 'sk-env12*****efgh')
        self.assertEqual(providers.mask_key(''), '')
        for value in ('abc', 'sk-1234', 'sk-123456789'):
            self.assertEqual(providers.mask_key(value), '********')

    def test_translation_cached_by_content_and_language(self):
        paper = {'id': '2610.00001', 'title': 'Test', 'abstract': 'We evaluate a robot policy. Improvement is limited to this benchmark.'}
        store.save('discovery', {'id': 'latest-search', 'recommendations': [paper]})
        result = {'value': {'translation': '我们评估一个机器人策略。提升仅限于该基准。'}, 'provider': 'fixture', 'model': 'fixture', 'usage': {}}
        with patch('paperpilot.providers.generate', return_value=result) as model:
            first = self.wait_job(abstracts.translate('discovery', 'latest-search', paper['id'], 'zh'))
            second = self.wait_job(abstracts.translate('discovery', 'latest-search', paper['id'], 'zh'))
            self.assertEqual(first['status'], 'completed', first.get('error'))
            self.assertEqual(second['result']['text'], first['result']['text'])
            self.assertEqual(model.call_count, 1)
            paper['abstract'] = 'A revised abstract with a different result.'
            store.save('discovery', {'id': 'latest-search', 'recommendations': [paper]})
            self.wait_job(abstracts.translate('discovery', 'latest-search', paper['id'], 'zh'))
            self.assertEqual(model.call_count, 2)
        self.assertEqual(len(store.all_objects('abstract_translation')), 2)
        with self.assertRaises(ValueError): abstracts.translate('discovery', 'latest-search', paper['id'], 'fr')
        with self.assertRaises(ValueError): abstracts.translate('discovery', 'latest-search', 'invented', 'zh')

    def test_translation_deduplicates_running_calls_and_retries_failure(self):
        paper = {'id': 'test', 'title': 'Test', 'abstract': 'A test abstract.'}
        store.save('favorite', {'id': 'favorite', 'paper': paper})
        entered, release = threading.Event(), threading.Event()
        def model(*args, **kwargs):
            entered.set();release.wait(3)
            return {'value': {'translation': 'English instead of Chinese'}, 'provider': 'fixture', 'model': 'fixture'}
        with patch('paperpilot.providers.generate', side_effect=model):
            job = abstracts.translate('favorite', '', 'test', 'zh')
            self.assertTrue(entered.wait(2))
            duplicate = abstracts.translate('favorite', '', 'test', 'zh')
            self.assertEqual(job['id'], duplicate['id'])
            release.set()
            self.assertEqual(self.wait_job(job)['status'], 'failed')
        self.assertEqual(store.all_objects('abstract_translation'), [])
        with patch('paperpilot.providers.generate', return_value={'value': {'translation': '测试摘要。'}, 'provider': 'fixture', 'model': 'fixture'}):
            self.assertEqual(self.wait_job(abstracts.translate('favorite', '', 'test', 'zh'))['status'], 'completed')

    def test_keychain_priority_reload_replace_delete_and_no_plaintext(self):
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'env-fixture'}):
            credentials.save('saved-fixture')
            self.assertEqual(providers.api_key('deepseek'), 'saved-fixture')
            credentials.CACHE.clear()
            self.assertEqual(providers.api_key('deepseek'), 'saved-fixture')
            self.assertTrue(providers.capabilities(store.settings())['key_storage']['deepseek']['persistent'])
            credentials.save('replacement-fixture'); credentials.CACHE.clear()
            self.assertEqual(providers.api_key('deepseek'), 'replacement-fixture')
            credentials.delete()
            self.assertEqual(providers.api_key('deepseek'), 'env-fixture')
            self.assertFalse(providers.capabilities(store.settings())['key_storage']['deepseek']['persistent'])
        self.assertNotIn('saved-fixture', (store.DATA/'paperpilot.sqlite').read_bytes().decode(errors='ignore'))
        with patch('paperpilot.credentials.backend', side_effect=ValueError('测试钥匙串锁定')):
            with self.assertRaises(ValueError): credentials.save('failed-fixture')
        self.assertNotEqual(credentials.get(), 'failed-fixture')

    def test_settings_persist_blank_preserves_and_never_returns_key(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{server.server_port}'
        def post(value):
            req = urllib.request.Request(base+'/api/settings', json.dumps(value).encode(), {'X-PaperPilot-Token': TOKEN})
            with urllib.request.urlopen(req) as response: return json.load(response)
        try:
            result = post({'deepseek_key': 'SECRET-fixture-never-return'})
            self.assertTrue(result['capabilities']['key_storage']['deepseek']['persistent'])
            self.assertNotIn('SECRET-fixture-never-return', json.dumps(result))
            post({'deepseek_key': ''})
            credentials.CACHE.clear()
            self.assertEqual(providers.api_key('deepseek'), 'SECRET-fixture-never-return')
            with urllib.request.urlopen(base+'/api/bootstrap') as response:
                self.assertNotIn('SECRET-fixture-never-return', response.read().decode())
            self.assertNotIn('SECRET-fixture-never-return', (store.DATA/'paperpilot.sqlite').read_bytes().decode(errors='ignore'))
            post({'clear_deepseek_key': True})
            self.assertEqual(credentials.get(), '')
        finally:
            server.shutdown();server.server_close()

    def test_environment_still_works_if_keychain_is_unavailable(self):
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'environment-fixture'}), patch('paperpilot.credentials.get', side_effect=ValueError('不可用')):
            self.assertEqual(providers.api_key('deepseek'), 'environment-fixture')
            self.assertEqual(providers.capabilities(store.settings())['key_storage']['deepseek']['source'], 'environment')
