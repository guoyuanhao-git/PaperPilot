import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import patch
import test_core
from paperpilot import store, documents, paper_storage, knowledge_sources, exports, service


class PaperStorage(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.scope = store.scope({'directory': Path(self.temp.name)})
        self.scope.__enter__()
        store.init()
        self.raw = test_core.pdf()
        self.paper = documents.ingest(self.raw, 'example.pdf', 'https://arxiv.org/abs/2501.12345v1')
        self.id = self.paper['id']
        self.folder = documents.directory(self.id)
        self.fig = {'id': 'fig-1', 'page': 1, 'bbox': [.1,.1,.8,.7], 'selected': True}
        self.paper.update(report={'figures': [self.fig], 'sections': [], 'summary': 'Saved report'},
                          notes='Keep this idea', liked=True, read_status='已精读', messages=[{'role':'user','content':'Old question'}])
        store.save('paper', self.paper)
        documents.render_page(self.id, 1)
        documents.render_page(self.id, 2)
        build = self.folder / 'build-abcdef123456';build.mkdir();(build / 'temporary.png').write_bytes(b'x'*1024)
        exported = self.folder / 'exports';exported.mkdir();(exported / 'report-test.pdf').write_bytes(b'Keep export')

    def tearDown(self):
        self.scope.__exit__(None, None, None)
        self.temp.cleanup()

    def total(self):
        return sum(p.stat().st_size for p in self.folder.rglob('*') if p.is_file())

    def test_release_keeps_evidence_report_images_and_restores_exact_file(self):
        before = self.total()
        files = {p.name for p in self.folder.iterdir()}
        revision = knowledge_sources.local_revision(self.paper)
        evidence = knowledge_sources.collect(self.paper)
        plan = paper_storage.preview(self.id)
        self.assertEqual(files, {p.name for p in self.folder.iterdir()})
        self.assertTrue(plan['can_download'])
        self.assertGreater(plan['bytes'], 0)
        result = paper_storage.release(self.id)
        p = result['paper']
        self.assertEqual(before - self.total(), result['freed_bytes'])
        self.assertEqual(plan['bytes'], result['freed_bytes'])
        self.assertFalse((self.folder / 'source.pdf').exists())
        self.assertFalse(list(self.folder.glob('page-*.png')))
        self.assertFalse(list(self.folder.glob('build-*')))
        self.assertTrue((self.folder / 'exports' / 'report-test.pdf').exists())
        self.assertTrue((self.folder / 'pages.json').exists())
        self.assertTrue(documents.crop_figure(self.id, self.fig).exists())
        self.assertEqual(knowledge_sources.local_revision(p), revision)
        self.assertEqual(knowledge_sources.collect(p)['paragraphs'], evidence['paragraphs'])
        for field in ('report', 'notes', 'liked', 'messages', 'read_status', 'figures'):
            self.assertEqual(p[field], self.paper[field])
        exports.validate_request(p, 'pdf')
        with self.assertRaises(ValueError): exports.validate_request(p, 'pptx')
        with self.assertRaises(ValueError): documents.render_page(self.id, 2)
        with self.assertRaises(ValueError): knowledge_sources.cache_pdf(p)
        with self.assertRaises(ValueError): paper_storage.restore_bytes(self.id, self.raw + b'wrong-version')
        self.assertFalse((self.folder / 'source.pdf').exists())
        restored = paper_storage.restore_bytes(self.id, self.raw)
        self.assertFalse(restored['pdf_released'])
        self.assertEqual(restored['report'], self.paper['report'])
        self.assertEqual(knowledge_sources.local_revision(restored), revision)
        self.assertEqual((self.folder / 'source.pdf').read_bytes(), self.raw)

    def test_failed_preparation_and_active_jobs_do_not_remove_original(self):
        with patch('paperpilot.documents.crop_figure', side_effect=ValueError('invalid crop')):
            with self.assertRaises(ValueError): paper_storage.release(self.id)
        self.assertTrue((self.folder / 'source.pdf').exists())
        store.save('job', {'id':'graph', 'kind':'knowledge', 'status':'running'})
        with self.assertRaises(ValueError): paper_storage.release(self.id)
        self.assertTrue((self.folder / 'source.pdf').exists())

    def test_persistence_failure_rolls_back_and_crash_recovery(self):
        with patch('paperpilot.paper_storage.store.save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): paper_storage.release(self.id)
        self.assertEqual((self.folder / 'source.pdf').read_bytes(), self.raw)
        self.assertFalse((self.folder / '.release-staging').exists())
        staging = self.folder / '.release-staging';staging.mkdir()
        (self.folder / 'source.pdf').rename(staging / 'source.pdf')
        paper_storage.recover()
        self.assertTrue((self.folder / 'source.pdf').exists())
        self.assertFalse(staging.exists())

    def test_account_isolation_and_no_address(self):
        self.paper['source_url'] = '';store.save('paper', self.paper)
        self.assertFalse(paper_storage.preview(self.id)['can_download'])
        paper_storage.release(self.id)
        with self.assertRaises(ValueError): paper_storage.download(self.id)
        with tempfile.TemporaryDirectory() as other:
            with store.scope({'directory':Path(other)}):
                store.init()
                with self.assertRaises(ValueError): paper_storage.restore_bytes(self.id, self.raw)
        self.assertTrue(store.get('paper', self.id)['pdf_released'])

    def test_chat_uses_only_retained_images_and_body(self):
        paper_storage.release(self.id)
        def immediate(kind, ident, work, metadata=None):
            return work(lambda text: None)
        def generate(config, system, messages, images):
            self.assertIn('原文 PDF 已释放', messages[0]['content'])
            self.assertIn('Research motivation', messages[0]['content'])
            self.assertEqual(len(images), 1)
            self.assertTrue(all(p.is_file() for p in images))
            return {'value':'Example answer','provider':'codex','model':'test','usage':{}}
        with patch('paperpilot.service.paper_job', side_effect=immediate), patch('paperpilot.providers.generate', side_effect=generate):
            result = service.chat(self.id, 'What is the method?')
        self.assertEqual(result['paper_id'], self.id)
        self.assertFalse((self.folder / 'source.pdf').exists())

    def test_no_report_retains_body_and_download_restores_without_ingestion(self):
        self.paper['report'] = None
        store.save('paper', self.paper)
        paper_storage.release(self.id)
        self.assertEqual(knowledge_sources.collect(store.get('paper', self.id))['status'], 'local')
        def immediate(kind, ident, work, metadata=None):
            return work(lambda message: None)
        with patch('paperpilot.service.paper_job', side_effect=immediate), patch('paperpilot.discovery.download', return_value=(self.raw, 'paper.pdf', '')) as download:
            self.assertEqual(paper_storage.download(self.id)['paper_id'], self.id)
            download.assert_called_once_with('https://arxiv.org/abs/2501.12345v1')
        self.assertEqual(store.get('paper', self.id)['notes'], 'Keep this idea')

    def test_empty_extracted_body_prevents_release(self):
        (self.folder / 'pages.json').write_text('[]')
        with self.assertRaises(ValueError): paper_storage.release(self.id)
        self.assertTrue((self.folder / 'source.pdf').exists())

    def test_manual_new_version_keeps_old_report_images_and_uses_new_body(self):
        paper_storage.release(self.id)
        old_image = documents.crop_figure(self.id, self.fig)
        pixels = old_image.read_bytes()
        new_pdf = self.raw + b'\n% revised edition\n'
        restored = paper_storage.manual_restore(self.id, new_pdf, 'revised.pdf')
        self.assertEqual((self.folder / 'source.pdf').read_bytes(), new_pdf)
        self.assertEqual(restored['filename'], 'revised.pdf')
        self.assertFalse(restored['pdf_released'])
        saved_figure = restored['report']['figures'][0]
        self.assertEqual(documents.crop_figure(self.id, saved_figure), old_image)
        self.assertEqual(old_image.read_bytes(), pixels)
        # Even identical page coordinates use a different cache for the replacement.
        self.assertNotEqual(documents.crop_figure(self.id, self.fig), old_image)
        for field in ('notes', 'liked', 'messages', 'read_status'):
            self.assertEqual(restored[field], self.paper[field])
        self.assertNotIn('revision', restored['source_storage'])

    def test_manual_wins_when_automatic_download_finishes_later(self):
        paper_storage.release(self.id)
        new_pdf = self.raw + b'\n% preferred by user\n'
        def immediate(kind, ident, work, metadata=None):
            store.save('job', {'id':'restore', 'kind':kind, 'paper_id':ident, 'status':'running'})
            return work(lambda message: None)
        def downloaded(url):
            paper_storage.manual_restore(self.id, new_pdf)
            return self.raw, 'old.pdf', url
        with patch('paperpilot.service.paper_job', side_effect=immediate), patch('paperpilot.discovery.download', side_effect=downloaded):
            paper_storage.download(self.id)
        self.assertEqual((self.folder / 'source.pdf').read_bytes(), new_pdf)

    def test_manual_can_override_completed_download_and_rollback_failed_save(self):
        paper_storage.release(self.id)
        paper_storage.restore_bytes(self.id, self.raw)
        old_pages = (self.folder / 'pages.json').read_bytes()
        with patch('paperpilot.paper_storage.store.save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                paper_storage.manual_restore(self.id, self.raw + b'\n% replacement\n')
        self.assertEqual((self.folder / 'source.pdf').read_bytes(), self.raw)
        self.assertEqual((self.folder / 'pages.json').read_bytes(), old_pages)
        self.assertFalse((self.folder / '.restore-staging').exists())
        paper_storage.manual_restore(self.id, self.raw + b'\n% replacement\n')
        self.assertTrue(store.get('paper', self.id)['source_storage']['manual_revision'])

    def test_successful_new_report_cleans_old_images_but_retains_reused_ones(self):
        paper_storage.release(self.id)
        old_image = documents.crop_figure(self.id, self.fig)
        p = paper_storage.manual_restore(self.id, self.raw + b'\n% new\n')
        old_report = p['report']
        paper_storage.cleanup_report_images(p, old_report)
        self.assertTrue(old_image.exists())  # Same report still references it.
        new_image = documents.crop_figure(self.id, self.fig)
        p['report'] = {'figures': [self.fig], 'summary':'New report'}
        store.save('paper', p)
        paper_storage.cleanup_report_images(p, old_report)
        self.assertFalse(old_image.exists())
        self.assertTrue(new_image.exists())
        self.assertTrue((self.folder / 'source.pdf').exists())

    def test_invalid_manual_pdf_or_other_active_work_preserves_release(self):
        paper_storage.release(self.id)
        with self.assertRaises(Exception): paper_storage.manual_restore(self.id, b'%PDF-invalid')
        self.assertTrue(store.get('paper', self.id)['pdf_released'])
        store.save('job', {'id':'analysis', 'kind':'analysis', 'paper_id':self.id, 'status':'running'})
        with self.assertRaises(ValueError): paper_storage.manual_restore(self.id, self.raw)
        self.assertFalse((self.folder / 'source.pdf').exists())

    def test_interrupted_manual_replacement_rolls_back(self):
        paper_storage.release(self.id)
        old_pages = (self.folder / 'pages.json').read_bytes()
        staging = self.folder / '.restore-staging'; staging.mkdir()
        (staging / 'manifest.json').write_text(json.dumps({'token':'not-committed', 'existing':['pages.json']}))
        (self.folder / 'pages.json').rename(staging / 'old-pages.json')
        (self.folder / 'source.pdf').write_bytes(self.raw)
        (self.folder / 'pages.json').write_text('[]')
        paper_storage.recover()
        self.assertEqual((self.folder / 'pages.json').read_bytes(), old_pages)
        self.assertFalse((self.folder / 'source.pdf').exists())

    def test_restore_url_follows_uploaded_version(self):
        self.assertEqual(paper_storage.restore_url(self.paper, [{'text':'arXiv:2501.12345v3'}]),
                         'https://arxiv.org/abs/2501.12345v3')
