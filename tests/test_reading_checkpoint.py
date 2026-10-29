import subprocess
import unittest
from unittest.mock import patch
import test_core
from test_figure_reading import generator
from paperpilot import documents, providers, reading, service, store
from paperpilot.reading_checkpoint import Checkpoints


class ResumeReading(unittest.TestCase):
    setUp = test_core.Core.setUp
    tearDown = test_core.Core.tearDown
    wait_job = test_core.Core.wait_job

    def test_failed_job_keeps_stage_and_rejects_duplicate_generation(self):
        def fail(progress):
            progress('逐图阅读 31–33 / 36')
            raise ValueError('network unavailable')
        result = self.wait_job(service.job('analysis', fail, 'p'))
        self.assertEqual(result['last_stage'], '逐图阅读 31–33 / 36')
        self.assertEqual(service.analysis_statuses()['p']['error'], 'network unavailable')
        p = documents.ingest(test_core.pdf(), 'busy.pdf')
        store.save('job', {'id':'busy','kind':'analysis','paper_id':p['id'],'status':'running'})
        with self.assertRaisesRegex(ValueError, '仍在生成'):
            service.analyze(p['id'], 'overview')

    def test_codex_route_error_is_not_misreported_as_auth_and_not_retried_again(self):
        process = subprocess.CompletedProcess([], 1, '', 'ERROR: workspace routing discovery failed')
        with patch('paperpilot.providers.shutil.which', return_value='/test/codex'), patch('paperpilot.providers.subprocess.run', return_value=process):
            with self.assertRaises(providers.TransientProviderError) as raised:
                providers.generate(dict(store.settings(), provider='codex'), 'test', [{'role':'user','content':'test'}])
        self.assertIn('路由失败', str(raised.exception))
        self.assertFalse(raised.exception.retryable)

    def build(self, p, stages=None, system='test'):
        return reading.build(p, 'overview', dict(store.settings(), vision=False),
                             (stages if stages is not None else []).append, system,
                             service.report_schema, service.validate_report)

    def test_failed_stage_resumes_and_successful_regeneration_is_fresh(self):
        p = documents.ingest(test_core.pdf(), 'resume.pdf')
        real = generator(p)
        def fail(config, system, messages, images=(), **kwargs):
            if 'items' in kwargs['schema']['properties']:
                raise providers.TransientProviderError('connection interrupted', retryable=False)
            return real(config, system, messages, images, **kwargs)
        with patch('paperpilot.providers.generate', side_effect=fail):
            with self.assertRaisesRegex(ValueError, 'interrupted'):
                self.build(p)
        self.assertTrue(list((store.data_dir()/'drafts').glob('*-checkpoint-*.json')))
        stages = []
        with patch('paperpilot.providers.generate', side_effect=real) as resumed:
            result, _ = self.build(p, stages)
        self.assertTrue(any('复用已完成步骤' in s for s in stages))
        self.assertTrue(any(c['usage'].get('checkpoint_reused') for c in result['usage']['calls']))
        self.assertFalse(list((store.data_dir()/'drafts').glob('*-checkpoint-*.json')))
        with patch('paperpilot.providers.generate', side_effect=real) as fresh:
            self.build(p)
        self.assertGreater(fresh.call_count, resumed.call_count)

    def test_invalid_figure_result_is_not_reused_and_profile_change_invalidates(self):
        p = documents.ingest(test_core.pdf(), 'invalid.pdf'); real = generator(p)
        def bad(config, system, messages, images=(), **kwargs):
            result = real(config, system, messages, images, **kwargs)
            if 'items' in kwargs['schema']['properties']:
                result['value']['items'] = []
            return result
        with patch('paperpilot.providers.generate', side_effect=bad):
            with self.assertRaisesRegex(ValueError, '未覆盖'):
                self.build(p)
        with patch('paperpilot.providers.generate', side_effect=real) as calls:
            self.build(p, system='changed research profile')
        self.assertTrue(any('sections' in c.kwargs['schema']['properties'] for c in calls.call_args_list))
        self.assertTrue(any('items' in c.kwargs['schema']['properties'] for c in calls.call_args_list))

    def test_transient_retry_is_bounded(self):
        p = documents.ingest(test_core.pdf(), 'retry.pdf')
        for retryable, expected in ((True, 2), (False, 1)):
            with patch('paperpilot.providers.generate', side_effect=providers.TransientProviderError('offline', retryable)) as calls:
                with self.assertRaisesRegex(ValueError, 'offline'):
                    self.build(p)
            self.assertEqual(calls.call_count, expected)

    def test_key_includes_image_bytes_and_config_and_accounts_are_isolated(self):
        image=store.data_dir()/'image.png';image.write_bytes(b'old')
        cp=Checkpoints('paper'); args=('stage', {'model':'a'}, 'system', 'prompt', {}, [image])
        old=cp.key(*args);image.write_bytes(b'new');self.assertNotEqual(old, cp.key(*args))
        new=cp.key(*args);result={'value':{},'usage':{},'model':'a','provider':'fixture'}
        cp.stage(new,result);cp.advance();self.assertIsNotNone(cp.get(new))
        other=store.data_dir()/'other';other.mkdir()
        with store.scope({'directory':other}):
            self.assertIsNone(Checkpoints('paper').get(new))
        self.assertNotEqual(new,cp.key('stage',{'model':'b'},'system','prompt',{},[image]))

    def test_latest_status_uses_creation_time_not_completion_order(self):
        store.save('job',{'id':'new','kind':'analysis','paper_id':'p','status':'completed','created_at':'2026-10-21'})
        store.save('job',{'id':'old','kind':'analysis','paper_id':'p','status':'failed','created_at':'2026-10-20','last_stage':'figures'})
        self.assertEqual(service.analysis_statuses()['p']['id'],'new')
