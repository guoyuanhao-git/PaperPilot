import copy
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import test_core
from test_figure_reading import generator
from paperpilot import documents, paper_info, reading, report_cache, service, store


class Freshness(unittest.TestCase):
    def test_seven_day_boundary_and_non_sliding_legacy_migration(self):
        start = datetime(2026, 10, 1, tzinfo=timezone.utc)
        paper = {'report': {'generated_at': start.isoformat(), 'abstract': {
            'original': 'Original', 'translation': '中文', 'pages': [1]}}}
        cached = report_cache.recent(paper, 'abstract', start + timedelta(days=7))
        self.assertEqual(cached['fetched_at'], start.isoformat())
        self.assertNotIn('fetched_at', paper['report']['abstract'])
        paper['report']['abstract'] = cached
        paper['report']['generated_at'] = (start + timedelta(days=6)).isoformat()
        self.assertIsNone(report_cache.recent(paper, 'abstract', start + timedelta(days=7, seconds=1)))

    def test_missing_invalid_and_future_cache_are_not_reused(self):
        for stamp in (None, '', 'bad', '2026-10-01', '2999-01-01T00:00:00+00:00'):
            paper = {'report': {'generated_at': stamp, 'paper_info': {'original_title': 'Title', 'authors': []}}}
            self.assertIsNone(report_cache.recent(paper, 'paper_info'))
        self.assertIsNone(report_cache.recent({'report': {'generated_at': report_cache.now(), 'abstract': {'translation': 'Missing source'}}}, 'abstract'))


class CachedReading(unittest.TestCase):
    setUp = test_core.Core.setUp
    tearDown = test_core.Core.tearDown

    def test_regeneration_skips_only_static_model_stages_and_expires_independently(self):
        p = documents.ingest(test_core.pdf(), 'cache.pdf')
        stamp = report_cache.now()
        p['abstract'] = 'This is the complete original abstract supplied by the paper source.'
        p.pop('abstract_record', None)
        service.store.save('paper', p)
        p['report'] = {'generated_at': stamp, 'abstract': {'original': p['abstract'], 'translation': '保持原摘要。', 'pages': [1]},
            'paper_info': {'original_title': 'Original Title', 'authors': [], 'organizations': ['One Lab']}}
        snapshot = copy.deepcopy(p['report'])
        with patch('paperpilot.providers.generate', side_effect=generator(p)) as model, patch('paperpilot.paper_info.extract') as extract:
            result, _ = reading.build(p, 'overview', store.settings(), lambda _: None, 'test', service.report_schema, service.validate_report)
        extract.assert_not_called()
        self.assertEqual(p['report'], snapshot)
        self.assertEqual(result['abstract']['fetched_at'], stamp)
        self.assertEqual(result['paper_info']['fetched_at'], stamp)
        self.assertEqual(result['sections'][0]['paragraphs'], ['保持原摘要。'])
        self.assertGreater(model.call_count, 2)  # Story and figure analysis still run.
        self.assertFalse(any('translation' in c.kwargs['schema']['properties'] for c in model.call_args_list))
        p['report'] = result
        p['report']['paper_info']['fetched_at'] = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        with patch('paperpilot.providers.generate', side_effect=generator(p)), patch('paperpilot.paper_info.extract', return_value={'original_title': 'Refreshed', 'authors': []}) as extract:
            result, _ = reading.build(p, 'overview', store.settings(), lambda _: None, 'test', service.report_schema, service.validate_report)
        extract.assert_called_once()

    def test_last_author_fallback_legacy_and_manual_citation_persistence(self):
        p = documents.ingest(test_core.pdf(), 'roles.pdf')
        p['report'] = {'title': 'Title', 'paper_info': {'authors': [{'name': 'Alice'}, {'name': 'Bob'}]}}
        info = p['report']['paper_info']
        paper_info.apply_defaults(info, p)
        self.assertTrue(info['authors'][-1]['corresponding'])
        self.assertEqual(info['authors'][-1]['corresponding_source'], 'last_author_default')
        service.store.save('paper', p)
        saved = service.save_author_citations(p['id'], {'Alice': 0, 'Bob': 123})
        self.assertEqual(saved['report']['paper_info']['authors'][0]['manual_citation']['count'], 0)
        saved['report']['paper_info'] = {'authors': [{'name': 'Alice'}, {'name': 'Bob'}], 'corresponding_mentioned': False}
        paper_info.apply_defaults(saved['report']['paper_info'], saved)
        self.assertEqual(saved['report']['paper_info']['authors'][-1]['manual_citation']['count'], 123)
        paper_info.set_citations(saved, {'Bob': None})
        self.assertNotIn('manual_citation', saved['report']['paper_info']['authors'][-1])
        self.assertEqual(saved['exports'], [])
        for values in ({'Other': 12}, {'Alice': -1}, {'Alice': 1.2}, {'Alice': True}, {'Alice': '123'}, {'Alice': 10**20}):
            before = copy.deepcopy(saved)
            with self.assertRaises(ValueError): paper_info.set_citations(saved, values)
            self.assertEqual(saved, before)

    def test_new_metadata_defaults_last_author_without_unverifiable_lookup(self):
        value = {'original_title': 'Title', 'authors': [{'name': 'Alice', 'affiliations': []}, {'name': 'Bob', 'affiliations': []}]}
        with patch('paperpilot.paper_info.source_material', return_value=('Title Alice Bob', [])), patch('paperpilot.author_names.resolve', return_value=None), patch('paperpilot.scholarly_metadata.venue', return_value=None), patch('paperpilot.scholarly_metadata.fetch') as network:
            info = paper_info.extract({}, lambda *args: {'value': value})
        network.assert_not_called()
        self.assertFalse(info['authors'][0]['corresponding'])
        self.assertTrue(info['authors'][1]['corresponding'])
        self.assertIn('fetched_at', info)
