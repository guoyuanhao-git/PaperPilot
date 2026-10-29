import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from paperpilot import store, hotspot_triage as triage, collections, abstracts


class HotspotTriage(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.scope = store.scope({'directory': Path(self.temp.name) / 'one'})
        self.scope.__enter__()
        store.init()
        self.paper = {'id': 'p', 'title': 'Example paper', 'paper_url': 'https://arxiv.org/abs/2501.12345v2', 'abstract': 'Original abstract'}
        store.save('hf_listing', {'id': 'list', 'items': [self.paper]})

    def tearDown(self):
        self.scope.__exit__(None, None, None)
        self.temp.cleanup()

    def skip_paper(self):
        return triage.skip({'origin': 'hf-listing', 'run_id': 'list', 'paper_id': 'p'})

    def test_snapshot_survives_feed_expiry_and_supports_reading_queue(self):
        entry = self.skip_paper()
        store.remove('hf_listing', 'list')
        self.assertEqual(abstracts.resolve('hotspot-skipped', entry['id'], 'p')['abstract'], 'Original abstract')
        favorite = collections.save('hotspot-skipped', entry['id'], 'p')
        self.assertEqual(favorite['paper']['title'], 'Example paper')
        triage.restore(entry['id'])
        self.assertEqual(store.all_objects('hotspot_skip'), [])
        self.assertEqual(abstracts.resolve('hotspot-recovered', entry['id'], 'p')['abstract'], 'Original abstract')
        self.assertEqual(len(store.all_objects('favorite')), 1)
        self.assertEqual(store.all_objects('paper'), [])
        self.assertEqual(store.all_objects('memory'), [])

    def test_account_isolation_and_duplicate_identity(self):
        first = self.skip_paper()
        self.paper['paper_url'] = 'https://huggingface.co/papers/2501.12345'
        store.save('hf_listing', {'id': 'list', 'items': [self.paper]})
        self.assertEqual(self.skip_paper()['id'], first['id'])
        self.assertEqual(len(store.all_objects('hotspot_skip')), 1)
        with store.scope({'directory': Path(self.temp.name) / 'two'}):
            store.init()
            self.assertEqual(store.all_objects('hotspot_skip'), [])
            with self.assertRaises(ValueError):
                triage.restore(first['id'])
        self.assertEqual(len(store.all_objects('hotspot_skip')), 1)

    def test_articles_are_independent_and_untrusted_cards_are_rejected(self):
        article = {'title': 'News', 'source_url': 'https://example.org/story', 'paper_ids': ['p']}
        with patch('paperpilot.daily.cached', return_value={'articles': [article], 'items': [self.paper]}):
            entry = triage.skip({'origin': 'news-article', 'url': article['source_url'], 'item': {'title': 'Injected'}})
            self.assertEqual(entry['item']['title'], 'News')
            self.assertNotEqual(entry['identity'], triage.identity(self.paper, 'paper'))
            with self.assertRaises(ValueError):
                triage.skip({'origin': 'news-article', 'url': 'https://untrusted.test'})
        with self.assertRaises(ValueError):
            triage.skip({'origin': 'title-search'})
        triage.restore(entry['id'])
        self.assertEqual(store.all_objects('hotspot_skip'), [])

    def test_identity(self):
        for url in ['https://arxiv.org/abs/2501.12345', 'https://arxiv.org/pdf/2501.12345v2.pdf', 'https://papers.cool/arxiv/2501.12345']:
            self.assertEqual(triage.identity({'paper_url': url}, 'paper'), 'paper:arxiv:2501.12345')
        self.assertEqual(triage.identity({'paper_url': 'https://doi.org/10.1000/ABC'}, 'paper'), 'paper:doi:10.1000/abc')

    def test_daily_reset_shanghai_boundary_preserves_queue(self):
        with patch.object(triage, 'today', return_value='2026-10-28'):
            entry = self.skip_paper()
            collections.save('hotspot-skipped', entry['id'], 'p')
            self.assertEqual(len(triage.public()), 1)
        with patch.object(triage, 'today', return_value='2026-10-29'):
            self.assertEqual(triage.public(), [])
            self.assertEqual(store.all_objects('hotspot_skip'), [])
            self.assertEqual(len(store.all_objects('favorite')), 1)
            self.assertEqual(self.skip_paper()['day'], '2026-10-29')
        self.assertEqual(triage.entry_day({'created_at':'2026-10-29T00:00:00+00:00'}), '2026-10-29')
        self.assertEqual(triage.entry_day({'created_at':'2026-10-28T23:59:59+00:00'}), '2026-10-28')

    def test_legacy_skip_and_restored_snapshots_expire(self):
        entry = self.skip_paper()
        entry.pop('day')
        entry['created_at'] = '2026-10-28T15:00:00+00:00'
        store.save('hotspot_skip', entry)
        with patch.object(triage, 'today', return_value='2026-10-28'):
            self.assertEqual(len(triage.public()), 1)
            triage.restore(entry['id'])
            self.assertEqual(len(store.all_objects('hotspot_recovered')), 1)
        with patch.object(triage, 'today', return_value='2026-10-29'):
            triage.public()
            self.assertEqual(store.all_objects('hotspot_recovered'), [])

    def test_reset_is_eight_am_not_midnight(self):
        self.assertEqual(triage.entry_day({'created_at':'2026-10-29T00:01:00+08:00'}), '2026-10-28')
        self.assertEqual(triage.entry_day({'created_at':'2026-10-29T07:59:59+08:00'}), '2026-10-28')
        self.assertEqual(triage.entry_day({'created_at':'2026-10-29T08:00:00+08:00'}), '2026-10-29')
