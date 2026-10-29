import io
import unittest
from unittest.mock import patch
from reportlab.pdfgen import canvas
import test_core
from paperpilot import collections, documents, news_metadata, service, store


class ImportMetadata(unittest.TestCase):
    setUp = test_core.Core.setUp
    tearDown = test_core.Core.tearDown
    wait_job = test_core.Core.wait_job

    def pdf(self):
        stream = io.BytesIO()
        c = canvas.Canvas(stream)
        c.setTitle('2501.09747')
        c.setFont('Helvetica-Bold', 18)
        c.drawString(50, 770, 'FAST: Efficient Action Tokenization for')
        c.drawString(50, 747, 'Vision-Language-Action Models')
        c.setFont('Helvetica', 11)
        c.drawString(50, 710, 'First Author and Second Author')
        c.drawString(50, 670, 'Abstract: A test abstract about action generation.')
        c.save()
        return stream.getvalue()

    def test_numeric_pdf_metadata_uses_first_page_title_without_a_model(self):
        with patch('paperpilot.providers.generate') as model:
            p = documents.ingest(self.pdf(), '2501.09747.pdf', 'https://arxiv.org/abs/2501.09747')
        self.assertEqual(p['title'], 'FAST: Efficient Action Tokenization for Vision-Language-Action Models')
        self.assertEqual(p['publication_month'], '2025-01')
        self.assertIsNone(p['report'])
        model.assert_not_called()

    def test_direct_arxiv_import_works_with_news_disabled_and_keeps_pdf_fallback(self):
        config = store.settings(); config['hotspot_news_enabled'] = False; store.save_settings(config)
        with patch('paperpilot.discovery.download', return_value=(self.pdf(), '2501.09747.pdf', 'https://arxiv.org/abs/2501.09747')), patch.object(news_metadata, 'resolve', side_effect=ValueError('offline')), patch('paperpilot.providers.generate') as model:
            job = self.wait_job(service.import_paper('2501.09747'))
        self.assertEqual(job['status'], 'completed', job.get('error'))
        paper = store.get('paper', job['result']['paper_id'])
        self.assertTrue(paper['title'].startswith('FAST:'))
        self.assertEqual(paper['publication_month'], '2025-01')
        model.assert_not_called()

    def test_source_metadata_does_not_replace_curated_identity_or_notes(self):
        paper = {'title': 'Curated title', 'original_title': 'Curated title', 'source_url': '',
                 'publication_month': '2020-01', 'publication_date_source': '手动填写', 'notes': 'My own notes'}
        collections.apply_metadata(paper, {'title': 'Another source title', 'published': '2021-09-01'})
        self.assertEqual(paper['title'], 'Curated title')
        self.assertEqual(paper['publication_month'], '2020-01')
        self.assertEqual(paper['notes'], 'My own notes')
