import json
import unittest
from unittest.mock import patch
import test_core
from paperpilot import daily, news_metadata as meta, store


class NewsMetadata(unittest.TestCase):
    setUp = test_core.Core.setUp
    tearDown = test_core.Core.tearDown

    def paper(self, ident='2609.24976'):
        return {'id': ident, 'title': 'arXiv · '+ident, 'paper_url': 'https://arxiv.org/abs/'+ident, 'reports': []}

    def test_arxiv_page_requires_exact_id_and_reads_citation_title(self):
        raw = '<meta name="citation_title" content="DexTacWAM: A Visuo-Tactile Model"><meta name="citation_pdf_url" content="http://arxiv.org/pdf/2609.24976v1"><meta name="citation_author" content="Example Author">'
        with patch('paperpilot.discovery.public_fetch', return_value=raw):
            value = meta.resolve(self.paper())
            self.assertEqual(value['title'], 'DexTacWAM: A Visuo-Tactile Model')
            self.assertEqual(value['authors'], ['Example Author'])
            with self.assertRaises(ValueError):
                meta.resolve(self.paper('2607.02195'))

    def test_doi_uses_exact_registry_record(self):
        paper = {'paper_url': 'https://doi.org/10.1111/j.1559-3584.1922.tb04958.x'}
        value = {'DOI': '10.1111/j.1559-3584.1922.tb04958.x', 'title': ['Directional Stability'],
                 'author': [{'given': 'Example', 'family': 'Author'}]}
        with patch('paperpilot.discovery.public_fetch', return_value=json.dumps({'message': value})) as fetch:
            self.assertEqual(meta.resolve(paper)['title'], 'Directional Stability')
            self.assertIn('api.crossref.org/works/10.1111%2F', fetch.call_args.args[0])
        value['DOI'] = '10.1111/another'
        with patch('paperpilot.discovery.public_fetch', return_value=json.dumps({'message': value})):
            with self.assertRaises(ValueError):
                meta.resolve(paper)

    def test_failed_identifiers_do_not_block_others_and_cache_both_results(self):
        papers = [self.paper(), self.paper('2607.02195')]
        def resolve(p):
            if p['id'] == '2607.02195':
                raise ValueError('offline')
            return {'title': 'Verified paper title'}
        with patch.object(meta, 'resolve', side_effect=resolve) as lookup:
            first = meta.enrich(papers)
            self.assertEqual(lookup.call_count, 2)
            self.assertEqual(first[0]['title'], 'Verified paper title')
            self.assertEqual(first[1]['title'], meta.MISSING_TITLE)
            self.assertEqual(meta.enrich(papers), first)
            self.assertEqual(lookup.call_count, 2)
            self.assertEqual(papers[0]['title'], 'arXiv · 2609.24976')

    def test_cached_edition_can_repair_titles_without_model_or_new_news(self):
        value = {'id': 'latest', 'updated_at': '2026-10-16T01:00:00+00:00', 'items': [self.paper()], 'articles': [], 'source_status': [], 'note': ''}
        with patch.object(meta, 'resolve', return_value={'title': 'Verified title'}), patch('paperpilot.providers.generate') as model, patch.object(daily, 'collect') as collect:
            result = daily.repair_metadata(value)
            self.assertEqual(result['items'][0]['title'], 'Verified title')
            self.assertEqual(result['updated_at'], value['updated_at'])
            self.assertEqual(result['items'][0]['reports'], [])
            self.assertEqual(store.get('daily', 'latest')['items'], result['items'])
            model.assert_not_called(); collect.assert_not_called()

    def test_wrapped_doi_is_rejoined_but_following_prose_is_not(self):
        full = 'https://doi.org/10.1111/j.1559-3584.1922.tb04958.x'
        self.assertEqual(daily.paper_links(full.replace('3584', '358 4')), {full: full})
        self.assertEqual(daily.paper_links(full.replace('3584', '358\n4')), {full: full})
        url = 'https://doi.org/10.1000/example'
        self.assertEqual(daily.paper_links(url+' 2026 research news'), {url: url})

    def test_title_lookup_never_overwrites_a_newer_news_edition(self):
        old = {'id': 'latest', 'updated_at': '2026-10-16T01:00:00+00:00', 'items': [self.paper()], 'articles': [], 'note': ''}
        newer = {**old, 'updated_at': '2026-10-16T02:00:00+00:00', 'items': []}
        # The resolver runs outside account state. Simulate a concurrent edition at commit.
        with patch.object(meta, 'enrich', side_effect=lambda papers, **kwargs: (store.save('daily', newer), [{**self.paper(), 'title': 'Resolved old title'}])[1]):
            daily.repair_metadata(old)
        self.assertEqual(store.get('daily', 'latest'), newer)
