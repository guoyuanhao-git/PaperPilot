import json
from pathlib import Path
from unittest.mock import patch
import test_core
from paperpilot import classic_papers, historical, store, title_search, paper_identity

ALEX = 'ImageNet Classification with Deep Convolutional Neural Networks'
GAN = 'Generative Adversarial Networks'

def html(title, date, ident='', abstract='A verified source abstract.'):
    return f'<meta name="citation_title" content="{title}"><meta name="citation_author" content="Author"><meta name="citation_publication_date" content="{date}"><meta name="citation_date" content="{date}"><meta name="citation_arxiv_id" content="{ident}"><meta name="citation_pdf_url" content="https://arxiv.org/pdf/{ident}"><p class="paper-abstract"><p>{abstract}</p></p>'


class ClassicPapers(test_core.unittest.TestCase):
    setUp = test_core.Core.setUp
    tearDown = test_core.Core.tearDown

    def test_aliases_metadata_verified_and_wrong_page_refused(self):
        for query in ('GAN','Generative Adversarial Nets',GAN):
            with patch('paperpilot.discovery.public_fetch',return_value=html(GAN,'2014/06/10','1406.2661')):
                p=classic_papers.lookup(query)[0]
                self.assertEqual(p['title'],GAN)
                self.assertEqual(p['published'],'2014-06-10')
        with patch('paperpilot.discovery.public_fetch',return_value=html('Wrong paper','2014/06/10','1406.2661')):
            with self.assertRaises(ValueError):classic_papers.lookup('GAN')
        with patch('paperpilot.discovery.public_fetch',return_value=html(GAN,'2014/06/10','2401.00001')):
            with self.assertRaises(ValueError):classic_papers.lookup('GAN')
        with patch('paperpilot.discovery.public_fetch') as fetch:
            self.assertEqual(classic_papers.lookup('GAN training survey'),[])
            fetch.assert_not_called()

    def test_both_gan_title_forms_report_same_month_error(self):
        for title in (GAN,'Generative Adversarial Nets','GAN'):
            row=historical.parse('1412 | '+title+' | GAN','read')[0]
            with patch('paperpilot.discovery.public_fetch',return_value=html(GAN,'2014/06/10','1406.2661')),patch('paperpilot.providers.generate') as model:
                with self.assertRaisesRegex(ValueError,'核实年月为 2014-06.*2014-12') as caught:
                    historical.import_one(row,'read')
                self.assertIn(GAN,str(caught.exception))
                model.assert_not_called()
        self.assertEqual(store.all_objects('paper'),[])

    def test_classic_historical_metadata_does_not_download_pdf(self):
        for title, date, prefix, short in ((GAN,'2014/06/10','1406','GAN'),(ALEX,'2012','1212','AlexNet')):
            with patch('paperpilot.discovery.public_fetch',return_value=html(title,date,'1406.2661' if title==GAN else '')),patch('paperpilot.discovery.download') as download:
                p=historical.import_one(historical.parse(prefix+' | '+title+' | '+short,'read')[0],'read')
                self.assertEqual(paper_identity.label(p),prefix+' '+short)
                self.assertTrue(p['metadata_only'])
                self.assertEqual(p['read_status'],'已速览')
                download.assert_not_called()
                if title==ALEX:
                    self.assertIn('会期',p['publication_date_source'])
                    self.assertTrue(p['date_basis_url'])

    def test_title_search_can_verify_classics_when_model_unavailable(self):
        for query,title,date,ident in (('AlexNet',ALEX,'2012',''),('GAN',GAN,'2014/06/10','1406.2661')):
            with patch('paperpilot.discovery.public_fetch',return_value=html(title,date,ident)),patch('paperpilot.title_search.huggingface',return_value=[]),patch('paperpilot.title_search.papers_cool',return_value=[]),patch('paperpilot.title_search.arxiv',return_value=[]),patch('paperpilot.providers.generate',side_effect=ValueError('offline')):
                result=title_search.search(query)
                self.assertEqual(result['items'][0]['title'],title)
                self.assertEqual(result['items'][0]['match_type'],'alias')
                self.assertFalse(result['model_status']['ok'])
                self.assertTrue(result['source_status'][-1]['ok'])

    def test_cool_related_arxiv_result_does_not_hide_exact_venue_result(self):
        def card(title,ident):
            return f'<input id="search-query"><div class="paper" id="{ident}"><a href="https://example.org/{ident}">#1</a><a class="title-link" href="/venue/{ident}">{title}</a><p class="summary">Abstract</p></div>'
        with patch('paperpilot.discovery.public_fetch',side_effect=[card('HEp-2 Cell Image Classification with Deep Convolutional Neural Networks','related'),card(ALEX,'original')]) as fetch:
            rows=title_search.papers_cool(ALEX)
            self.assertEqual(fetch.call_count,2)
            self.assertIn('/venue/search?',fetch.call_args.args[0])
            self.assertTrue(any(title_search.same_title(p['title'],ALEX) for p in rows))
