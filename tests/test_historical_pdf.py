from unittest.mock import patch
import test_core
from paperpilot import documents, historical_pdf, store, library, paper_identity

class HistoricalPDF(test_core.unittest.TestCase):
    setUp=test_core.Core.setUp
    tearDown=test_core.Core.tearDown
    wait_job=test_core.Core.wait_job

    def upload(self):return documents.ingest(test_core.pdf(),'original.pdf')
    def response(self,abstract='An original abstract.',month='',evidence=''):
        return {'value':{'title':'Verified PDF Paper: A Representation Method','abstract':abstract,
                'authors':['An Author'],'publication_month':month,'date_evidence':evidence},
                'provider':'fixture','model':'fixture'}

    def recognize(self,p):
        with patch('paperpilot.providers.generate',return_value=self.response()) as model:
            job=self.wait_job(historical_pdf.extract(p['id']))
            self.assertEqual(job['status'],'completed',job.get('error'))
            model.assert_called_once()
            self.assertIn('Research motivation',model.call_args.args[2][0]['content'])
        return store.get('paper',p['id'])

    def test_pdf_import_reuses_local_file_manual_identity_and_no_today_count(self):
        p=self.upload();directory=documents.directory(p['id']);original=(directory/'source.pdf').read_bytes()
        p=self.recognize(p)
        self.assertEqual(p['read_status'],'未标记')
        for target,status,starred in [('read','已速览',False),('starred','已精读',True)]:
            with self.subTest(target=target):
                current=store.get('paper',p['id']);current.update(read_status='未标记',starred=False,historical_metadata=p['historical_metadata']);store.save('paper',current)
                saved=historical_pdf.finish(p['id'],'User Confirmed Title','2021-09','MyName',target)
                self.assertEqual(saved['read_status'],status)
                self.assertEqual(saved['starred'],starred)
                self.assertEqual(paper_identity.label(saved),'2109 MyName')
                self.assertEqual(saved['title'],'User Confirmed Title')
                self.assertEqual(saved['abstract'],'An original abstract.')
                self.assertNotIn('historical_metadata',saved)
                self.assertEqual(library.statistics([saved]),{'today':0,'week':0})
                self.assertEqual((directory/'source.pdf').read_bytes(),original)

    def test_missing_identity_duplicate_or_unfinished_metadata_not_imported(self):
        p=self.recognize(self.upload())
        for month,short in [('', 'Name'),('2021-09','')]:
            with self.assertRaises(ValueError):historical_pdf.finish(p['id'],'Title',month,short,'read')
        store.save('paper',{'id':'other','title':'Same Title','publication_month':'2021-09','short_title':'Taken'})
        with self.assertRaisesRegex(ValueError,'同题'):
            historical_pdf.finish(p['id'],'Same Title','2021-09','Another','read')
        with self.assertRaisesRegex(ValueError,'年月＋短标题'):
            historical_pdf.finish(p['id'],'Different Title','2021-09','Taken','read')
        self.assertEqual(store.get('paper',p['id'])['read_status'],'未标记')

    def test_failure_retains_pdf_and_pending_draft_can_retry(self):
        p=self.upload()
        with patch('paperpilot.providers.generate',return_value=self.response(abstract='')):
            job=self.wait_job(historical_pdf.extract(p['id']))
            self.assertEqual(job['status'],'failed')
        self.assertTrue((documents.directory(p['id'])/'source.pdf').is_file())
        self.assertTrue(store.get('paper',p['id'])['historical_metadata']['pending'])
        self.recognize(p)

    def test_date_lookup_uses_existing_sources_without_second_model_call(self):
        p=self.recognize(self.upload())
        record={'title':p['historical_metadata']['title'],'published':'2021-09-14','abstract':'Metadata',
                'source_url':'https://arxiv.org/abs/2109.00001'}
        with patch('paperpilot.title_search.huggingface',return_value=[record]),patch('paperpilot.providers.generate') as model:
            job=self.wait_job(historical_pdf.find_date(p['id'],record['title']))
            self.assertEqual(job['status'],'completed')
            self.assertEqual(store.get('paper',p['id'])['historical_metadata']['publication_month'],'2021-09')
            model.assert_not_called()
        with patch('paperpilot.title_search.huggingface',return_value=[]),patch('paperpilot.title_search.papers_cool',return_value=[]),patch('paperpilot.title_search.arxiv',return_value=[]):
            job=self.wait_job(historical_pdf.find_date(p['id'],record['title']))
            self.assertEqual(job['status'],'failed')
            self.assertIn('手动填写',job['error'])
        self.assertEqual(store.get('paper',p['id'])['read_status'],'未标记')

    def test_existing_read_paper_or_report_not_overwritten(self):
        p=self.upload();p.update(read_status='已速览',notes='My own notes');store.save('paper',p)
        with self.assertRaisesRegex(ValueError,'已在论文库'):
            historical_pdf.extract(p['id'])
        self.assertEqual(store.get('paper',p['id'])['notes'],'My own notes')

    def test_year_only_or_invented_date_evidence_does_not_fill_month(self):
        p=self.upload()
        for evidence in ('Copyright 2021','September 2021 not present in the PDF'):
            with patch('paperpilot.providers.generate',return_value=self.response(month='2021-09',evidence=evidence)):
                job=self.wait_job(historical_pdf.extract(p['id']))
                self.assertEqual(job['status'],'completed')
                self.assertEqual(store.get('paper',p['id'])['historical_metadata']['publication_month'],'')
