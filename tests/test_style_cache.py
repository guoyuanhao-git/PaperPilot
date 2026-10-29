import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import test_core
from paperpilot import store, style_cache, style_samples, reading


def response(config, system, messages, **kwargs):
    items=json.loads(messages[0]['content'])
    return {'value':{'rules':['先提出问题，再给出直觉。','用简短例子引出符号。','解释假设与适用边界。','联系实现。','小结回顾。'],
                     'snippets':[{'source_id':items[0]['id'],'text':items[0]['excerpt'][:80]}]},
            'provider':config['provider'],'model':'fixture','usage':{'completion_tokens':100}}


class StyleCache(unittest.TestCase):
    setUp=test_core.Core.setUp
    tearDown=test_core.Core.tearDown
    wait_job=test_core.Core.wait_job

    def upload(self,word='Example'):
        return style_samples.upload((word+' intuition first. '*80).encode(),'style.md')[0]

    def test_reuses_across_providers_and_invalidates_on_input_changes(self):
        item=self.upload()
        with patch('paperpilot.providers.generate',side_effect=response) as model:
            one=style_cache.ensure(dict(store.settings(),provider='deepseek'))
            two=style_cache.ensure(dict(store.settings(),provider='codex'))
            self.assertEqual(one,two);self.assertEqual(model.call_count,1)
            self.assertLess(style_cache.status()['characters'],item['characters'])
            self.assertIn('风格规范',reading.math_style_examples());self.assertEqual(model.call_count,1)
            style_samples.change(item['id'],'enable',False)
            self.assertEqual(style_cache.status()['state'],'empty')
            self.assertEqual(store.all_objects('style_cache'),[])
            style_samples.change(item['id'],'enable',True)
            style_cache.ensure();self.assertEqual(model.call_count,2)
            self.assertEqual(model.call_args.args[0]['codex_reasoning_effort'],'medium')
            self.assertEqual(model.call_args.args[0]['deepseek']['thinking'],'low')

    def test_background_and_simultaneous_reading_share_one_generation(self):
        self.upload()
        with patch('paperpilot.providers.generate',side_effect=response) as model:
            job=style_cache.start()
            with ThreadPoolExecutor(2) as pool:
                results=list(pool.map(lambda _:style_cache.context(),range(2)))
            self.assertEqual(results[0],results[1]);self.assertEqual(model.call_count,1)
            self.assertEqual(self.wait_job(job)['status'],'completed')
            self.assertIsNone(style_cache.start())

    def test_changed_sources_cannot_commit_obsolete_result(self):
        item=self.upload();entered=threading.Event();release=threading.Event()
        def slow(*args,**kwargs):
            entered.set();release.wait(3);return response(*args,**kwargs)
        with patch('paperpilot.providers.generate',side_effect=slow):
            job=style_cache.start();self.assertTrue(entered.wait(3))
            style_samples.change(item['id'],'enable',False);release.set()
            self.assertEqual(self.wait_job(job)['status'],'failed')
            self.assertEqual(store.all_objects('style_cache'),[])
            self.assertEqual(style_cache.status()['state'],'empty')

    def test_validation_retries_once_and_rejects_invented_snippet(self):
        self.upload()
        def bad(*args,**kwargs):
            result=response(*args,**kwargs);result['value']['snippets'][0]['text']='invented quotation';return result
        with patch('paperpilot.providers.generate',side_effect=bad) as model:
            job=self.wait_job(style_cache.start())
            self.assertEqual(job['status'],'failed');self.assertEqual(model.call_count,2)
            self.assertEqual(store.all_objects('style_cache'),[])
            self.assertEqual(style_cache.status()['state'],'failed')
        with patch('paperpilot.providers.generate',side_effect=response):
            self.assertEqual(self.wait_job(style_cache.start())['status'],'completed')

    def test_direct_mode_skips_distillation_and_switch_back_reuses_cache(self):
        self.upload()
        with patch('paperpilot.providers.generate',side_effect=response) as model:
            original=style_cache.ensure()
            style_samples.set_mode('direct')
            self.assertIsNone(style_cache.start())
            self.assertIn('直接参考',reading.math_style_examples())
            self.assertEqual(model.call_count,1)
            style_samples.set_mode('cached')
            self.assertEqual(style_cache.ensure(),original)
            self.assertEqual(model.call_count,1)
            # A generation captures its chosen mode, even after the account changes it.
            self.assertIn('直接参考',reading.math_style_examples('direct'))
        for invalid in ('unknown',None,[]):
            with self.assertRaises(ValueError):style_samples.set_mode(invalid)

    def test_direct_mode_changes_do_not_start_model_and_choice_is_account_local(self):
        with store.scope({'directory':store.DATA/'a'}):
            store.init();style_samples.set_mode('direct')
            with patch('paperpilot.providers.generate',side_effect=AssertionError('No model expected')):
                item=self.upload();self.assertIsNone(style_cache.start())
                self.assertIn('Example',reading.math_style_examples())
                style_samples.change(item['id'],'enable',False)
                self.assertNotIn('Example',reading.math_style_examples())
                self.assertIsNone(style_cache.start())
        with store.scope({'directory':store.DATA/'b'}):
            store.init();self.assertEqual(style_samples.mode(),'cached')
        with store.scope({'directory':store.DATA/'a'}):self.assertEqual(style_samples.mode(),'direct')

    def test_equal_sources_in_two_accounts_have_separate_caches(self):
        with patch('paperpilot.providers.generate',side_effect=response) as model:
            for name in ('a','b'):
                with store.scope({'directory':store.DATA/name}):
                    store.init();self.upload();self.assertEqual(store.all_objects('style_cache'),[])
                    style_cache.ensure()
            self.assertEqual(model.call_count,2)
