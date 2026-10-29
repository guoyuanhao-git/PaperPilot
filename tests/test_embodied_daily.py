import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paperpilot import collections, embodied_daily as feed, hotspot_triage, store


class EmbodiedDaily(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.scope = store.scope({'directory': Path(self.temp.name) / 'one'})
        self.scope.__enter__()
        store.init()
        self.paper = {'id': '2610.12345v2', 'title': 'A robot paper', 'abstract': 'Original abstract',
                      'summary': 'English summary', 'translations': {'zh': {'summary': '中文概括'}},
                      'reading_status': 'ready'}
        self.response = {'day': '2026-10-01', 'papers': [self.paper, self.paper]}

    def tearDown(self):
        self.scope.__exit__(None, None, None)
        self.temp.cleanup()

    def test_normalization_preserves_original_evidence(self):
        value = feed.normalize(self.paper)
        self.assertEqual(value['id'], '2610.12345')
        self.assertEqual(value['abstract'], 'Original abstract')
        self.assertEqual(value['summary'], '中文概括')
        self.assertTrue(value['reading_ready'])
        del self.paper['abstract']
        self.assertEqual(feed.normalize(self.paper)['abstract'], '')
        self.assertEqual(value['paper_url'], 'https://arxiv.org/abs/2610.12345')

    def test_cache_dedup_and_outage(self):
        with patch.object(feed, 'fetch', return_value=self.response) as fetch:
            result = feed.listing('2026-10-01')
            self.assertEqual(len(result['items']), 1)
            self.assertEqual(feed.listing('2026-10-01')['id'], result['id'])
            fetch.assert_called_once()
        result['fetched_at'] = 0
        store.save('embodied_listing', result)
        with patch.object(feed, 'fetch', side_effect=OSError('offline')):
            self.assertTrue(feed.listing('2026-10-01')['stale'])
            with self.assertRaises(ValueError):
                feed.listing('2026-10-02')

    def test_wrong_day_and_invalid_id_rejected(self):
        with patch.object(feed, 'fetch', return_value=self.response):
            with self.assertRaises(ValueError):
                feed.listing('2026-10-02')
        for ident in ['https://other.test', '../secrets', '2610.12345&admin=1']:
            with self.assertRaises(ValueError):
                feed.preview(ident)
        with patch.object(feed, 'fetch', return_value=self.paper):
            with self.assertRaises(ValueError):
                feed.preview('2610.99999')

    def test_local_queue_skip_recovery_and_account_isolation(self):
        with patch.object(feed, 'fetch', return_value=self.paper):
            result = feed.preview('2610.12345')
        self.assertEqual(store.all_objects('favorite'), [])  # Preview never subscribes.
        favorite = collections.save('embodied-daily', result['id'], '2610.12345')
        store.save('hf_listing', {'id': 'hf', 'items': [feed.normalize(self.paper)]})
        self.assertEqual(collections.save('hf-listing', 'hf', '2610.12345')['id'], favorite['id'])
        skipped = hotspot_triage.skip({'origin': 'embodied-daily', 'run_id': result['id'], 'paper_id': '2610.12345'})
        store.remove('embodied_listing', result['id'])
        hotspot_triage.restore(skipped['id'])
        self.assertEqual(collections.resolve('hotspot-recovered', skipped['id'], '2610.12345')['title'], self.paper['title'])
        with store.scope({'directory': Path(self.temp.name) / 'two'}):
            store.init()
            self.assertEqual(store.all_objects('favorite'), [])
            self.assertEqual(store.all_objects('embodied_listing'), [])
            with self.assertRaises(ValueError):
                collections.resolve('hotspot-recovered', skipped['id'], '2610.12345')

    def test_configured_public_origin(self):
        with patch.dict('os.environ', {'PAPERPILOT_EMBODIED_DAILY_URL': 'https://daily.example.org/'}):
            self.assertTrue(feed.normalize(self.paper)['reading_url'].startswith('https://daily.example.org/reader.html?'))
        with patch.dict('os.environ', {'PAPERPILOT_EMBODIED_DAILY_URL': 'https://user:secret@example.org'}):
            with self.assertRaises(ValueError):
                feed.base_url()
