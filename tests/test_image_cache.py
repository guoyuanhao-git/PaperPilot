import io
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from reportlab.pdfgen import canvas
from paperpilot import documents, image_cache, paper_storage, store


class ImageCache(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.scope = store.scope({'directory': Path(self.temp.name)})
        self.scope.__enter__()
        store.init()
        self.ident = 'a' * 20
        self.folder = documents.directory(self.ident)
        self.folder.mkdir(parents=True)
        stream = io.BytesIO()
        c = canvas.Canvas(stream, pagesize=(600, 800), invariant=1)
        c.setFillColorRGB(1, 0, 0); c.rect(0, 400, 300, 400, fill=1, stroke=0)
        c.setFillColorRGB(0, 1, 0); c.rect(300, 400, 300, 400, fill=1, stroke=0)
        c.setFillColorRGB(0, 0, 1); c.rect(0, 0, 600, 400, fill=1, stroke=0)
        c.save()
        self.raw = stream.getvalue()
        (self.folder / 'source.pdf').write_bytes(self.raw)
        self.figure = {'id': 'fig-1', 'page': 1, 'bbox': [.05, .05, .45, .45]}
        self.paper = {'id': self.ident, 'page_count': 1, 'figures': [self.figure],
                      'report': {'figures': [self.figure]}}
        store.save('paper', self.paper)

    def tearDown(self):
        self.scope.__exit__(None, None, None)
        self.temp.cleanup()

    def fake_crop(self, number, size=100, stamp=1):
        path = self.folder / f'crop-{number:016x}.png'
        path.write_bytes(b'x' * size)
        os.utime(path, (stamp, stamp))
        return path

    def test_direct_pdf_crop_is_sharp_bounded_and_uses_correct_coordinates(self):
        small = documents.crop_figure(self.ident, self.figure, quality='model')
        large = documents.crop_figure(self.ident, self.figure)
        with Image.open(small) as old, Image.open(large) as new:
            self.assertGreater(new.width, old.width * 3)
            self.assertGreaterEqual(new.width, 1600)
            self.assertLessEqual(new.width, 2400)
            self.assertLessEqual(new.width * new.height, 4_000_000)
            self.assertEqual(new.convert('RGB').getpixel((new.width // 2, new.height // 2)), (255, 0, 0))
        blue = documents.crop_figure(self.ident, {**self.figure, 'bbox': [0, .6, 1, 1]})
        with Image.open(blue) as image:
            self.assertEqual(image.convert('RGB').getpixel((image.width // 2, image.height // 2)), (0, 0, 255))
        skinny = documents.crop_figure(self.ident, {**self.figure, 'bbox': [0, 0, .02, 1]})
        with Image.open(skinny) as image:
            self.assertLessEqual(image.height, 4096)
            self.assertLessEqual(image.width * image.height, 4_000_000)
        self.assertEqual(image_cache.LIMIT_BYTES, 512 * 1024 * 1024)

    def test_lru_shared_by_papers_and_excludes_source_report_and_pins(self):
        old = self.fake_crop(1, stamp=1)
        recent = self.fake_crop(2, stamp=5)
        pinned = self.fake_crop(3, size=1000, stamp=0)
        self.paper['report']['figures'][0]['image_file'] = pinned.name
        store.save('paper', self.paper)
        second = {**self.paper, 'id': 'b' * 20, 'report': None}
        folder = documents.directory(second['id']); folder.mkdir()
        (folder / 'source.pdf').write_bytes(self.raw)
        other = folder / 'page-1.png'; other.write_bytes(b'x' * 100); os.utime(other, (2, 2))
        store.save('paper', second)
        with patch.object(image_cache, 'LIMIT_BYTES', 100):
            self.assertEqual(image_cache.trim(), 100)
        self.assertFalse(old.exists()); self.assertFalse(other.exists())
        self.assertTrue(recent.exists()); self.assertTrue(pinned.exists())
        self.assertEqual((self.folder / 'source.pdf').read_bytes(), self.raw)
        self.assertEqual(store.get('paper', self.ident)['report'], self.paper['report'])

    def test_evicted_image_regenerates_without_model_and_hit_updates_lru(self):
        path = documents.crop_figure(self.ident, self.figure)
        os.utime(path, (1, 1))
        documents.crop_figure(self.ident, self.figure)
        self.assertGreater(path.stat().st_mtime, 1)
        expected = path.read_bytes()
        with patch.object(image_cache, 'LIMIT_BYTES', 0):
            self.assertEqual(documents.figure_bytes(self.ident, self.figure), expected)
            self.assertFalse(path.exists())
        self.assertEqual(documents.figure_bytes(self.ident, self.figure), expected)
        self.assertTrue(path.exists())

    def test_legacy_released_pdf_and_manual_pinned_report_never_evicted(self):
        old = documents.crop_figure(self.ident, self.figure, quality='model')
        self.paper['pdf_released'] = True
        store.save('paper', self.paper)
        (self.folder / 'source.pdf').unlink()
        with patch.object(image_cache, 'LIMIT_BYTES', 0):
            self.assertEqual(documents.figure_bytes(self.ident, self.figure), old.read_bytes())
            self.assertTrue(old.exists())
            # A later manual PDF version cannot be used to regenerate the old report.
            (self.folder / 'source.pdf').write_bytes(self.raw + b'\n% replacement')
            self.paper['pdf_released'] = False
            self.paper['report']['figures'][0]['image_file'] = old.name
            store.save('paper', self.paper)
            image_cache.trim()
            self.assertTrue(old.exists())
            with documents.model_images(self.ident, [self.figure]) as paths:
                self.assertTrue(paths[0].is_file())
        old.unlink()
        with self.assertRaisesRegex(ValueError, '旧报告图片缺失'):
            documents.crop_figure(self.ident, self.figure)

    def test_model_snapshots_survive_eviction_and_cleanup_on_error(self):
        paths = []
        with patch.object(image_cache, 'LIMIT_BYTES', 0):
            with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                with documents.model_images(self.ident, [self.figure]) as paths:
                    self.assertTrue(paths[0].is_file())
                    self.assertFalse(list(self.folder.glob('crop-*.png')))
                    # Another thread can take the PDF lock during a model call.
                    acquired = []
                    def probe():
                        ok = documents.PDF_LOCK.acquire(timeout=.5)
                        acquired.append(ok)
                        if ok: documents.PDF_LOCK.release()
                    t = threading.Thread(target=probe); t.start(); t.join()
                    self.assertEqual(acquired, [True])
                    with Image.open(paths[0]) as image:
                        self.assertLessEqual(max(image.size), 1600)
                    raise RuntimeError('cancelled')
        self.assertFalse(paths[0].exists())
        self.assertFalse(list(self.folder.glob('.model-images-*')))

    def test_account_isolation_and_missing_pdf_are_safe(self):
        protected = self.fake_crop(1)
        (self.folder / 'source.pdf').unlink()
        with patch.object(image_cache, 'LIMIT_BYTES', 0):
            image_cache.trim()
            self.assertTrue(protected.exists())
            with tempfile.TemporaryDirectory() as other:
                with store.scope({'directory': Path(other)}):
                    store.init()
                    image_cache.trim()
                    with self.assertRaises(ValueError):
                        documents.figure_bytes(self.ident, self.figure)
            self.assertTrue(protected.exists())

    def test_startup_removes_interrupted_model_snapshots_and_trims_legacy_cache(self):
        cache = self.fake_crop(1)
        job = self.folder / '.model-images-aborted'; job.mkdir(); (job / '0.png').write_bytes(b'temp')
        with patch.object(image_cache, 'LIMIT_BYTES', 0):
            paper_storage.recover()
        self.assertFalse(cache.exists()); self.assertFalse(job.exists())

    def test_release_in_progress_excluded(self):
        cache = self.fake_crop(1)
        (self.folder / '.release-staging').mkdir()
        with patch.object(image_cache, 'LIMIT_BYTES', 0):
            image_cache.trim()
        self.assertTrue(cache.exists())


if __name__ == '__main__':
    unittest.main()
