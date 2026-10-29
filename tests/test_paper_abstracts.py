import io
import copy
import unittest
from unittest.mock import patch
from reportlab.pdfgen import canvas
import test_core
from paperpilot import store, documents, paper_abstracts, collections, paper_info


class PaperAbstracts(unittest.TestCase):
    setUp = test_core.Core.setUp
    tearDown = test_core.Core.tearDown
    def test_import_freezes_abstract_and_translation_has_no_weekly_expiry(self):
        p = documents.ingest(test_core.pdf(), 'paper.pdf')
        original = 'This authoritative abstract is supplied by the paper metadata, without any introduction.'
        collections.apply_metadata(p, {'title':p['title'], 'abstract':original})
        self.assertEqual(p['abstract_record']['original'], original)
        store.save('paper', p)
        record = paper_abstracts.prepare(p)
        record.update(translation='这是完整的原文摘要。', fetched_at='2020-01-01T00:00:00+00:00')
        paper_abstracts.save_translation(p, record)
        with patch('paperpilot.documents.abstract_source', side_effect=AssertionError('should not re-extract')):
            again = paper_abstracts.prepare(store.get('paper', p['id']))
        self.assertEqual(again['translation'], record['translation'])
        self.assertEqual(again['fetched_at'], record['fetched_at'])

    def test_metadata_beats_unbounded_old_report_and_reuses_discovery_translation(self):
        p = documents.ingest(test_core.pdf(), 'paper.pdf')
        source = 'The actual abstract from discovery has a precise beginning and end.'
        p.update(abstract=source, report={'abstract':{'original': source+' EXTRA INTRODUCTION', 'translation':'错误的旧译文'}})
        store.save('abstract_translation', {'id':paper_abstracts.translation_key(source), 'source_text':source, 'text':'正确的摘要。'})
        result = paper_abstracts.prepare(p)
        self.assertEqual(result['original'], source)
        self.assertEqual(result['translation'], '正确的摘要。')
        p['abstract'] = source + ' A new version.'
        result = paper_abstracts.prepare(p)
        self.assertNotIn('translation', result)

    def test_two_column_abstract_does_not_include_right_column_introduction(self):
        stream = io.BytesIO(); c = canvas.Canvas(stream, pagesize=(600,800))
        c.setFont('Helvetica',10)
        c.drawString(40,600,'Abstract')
        sentences = ['We study an important research problem.', 'Our method makes a precise contribution.',
                     'We evaluate the method on several tasks.', 'The results support this limited claim.']
        for i, text in enumerate(sentences):
            c.drawString(40,580-i*15,text)
            c.drawString(330,580-i*15,'Unrelated introduction should stay out.')
        c.drawString(40,500,'1 Introduction');c.save()
        p = documents.ingest(stream.getvalue(), 'two-columns.pdf')
        original = p['abstract_record']['original']
        self.assertEqual(original, ' '.join(sentences))
        self.assertNotIn('Unrelated', original)

    def test_unbounded_abstract_is_not_the_entire_page(self):
        stream=io.BytesIO();c=canvas.Canvas(stream,pagesize=(600,800));c.setFont('Helvetica',11)
        c.drawString(40,700,'Abstract')
        c.drawString(40,680,'There is text here but no reliable boundary for its abstract.')
        c.save()
        p=documents.ingest(stream.getvalue(),'unbounded.pdf')
        self.assertEqual(p['abstract_record']['status'],'missing')

    def test_translation_survives_report_failure_and_source_change_cannot_overwrite(self):
        p=documents.ingest(test_core.pdf(),'paper.pdf')
        p['abstract']='The original paper abstract with enough words to identify the source.'
        p['report']={'summary':'Keep old report'}
        store.save('paper',p)
        a=paper_abstracts.prepare(p);a['translation']='已翻译的摘要。'
        paper_abstracts.save_translation(p,a)
        current=store.get('paper',p['id'])
        self.assertEqual(current['report'],p['report'])
        current['abstract']='A different abstract after the original PDF was revised by its author.'
        store.save('paper',current)
        with self.assertRaises(ValueError):paper_abstracts.save_translation(p,a)

    def test_author_metadata_never_queries_citation_counts(self):
        info={'original_title':'Title','authors':[{'name':'Alice Smith','affiliations':['Example University']}], 'organizations':['Example University']}
        with patch('paperpilot.paper_info.source_material',return_value=('Title Alice Smith Example University',[])), \
             patch('paperpilot.scholarly_metadata.venue',return_value=None), \
             patch('paperpilot.author_names.resolve',return_value=None), \
             patch('paperpilot.scholarly_metadata.fetch',side_effect=AssertionError('no citation lookup')):
            result=paper_info.extract({},lambda *args:{'value':copy.deepcopy(info)})
        self.assertNotIn('scholar',result['authors'][0])
