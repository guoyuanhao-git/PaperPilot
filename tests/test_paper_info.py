import copy
from unittest.mock import patch
import test_core
from paperpilot import paper_info, providers, reading, publication

class PaperInfo(test_core.unittest.TestCase):
    def setUp(self):
        names = patch('paperpilot.author_names.resolve', return_value=None)
        names.start()
        self.addCleanup(names.stop)

    def test_original_title_and_missing_dates(self):
        paper={'title':'Original Title','source_url':'https://arxiv.org/abs/2109.00001','report':{'title':'中文标题','base_title':'中文标题'}}
        publication.apply(paper);publication.apply(paper)
        self.assertEqual(paper['report']['title'],'2109 · Original Title')
        paper['report']['paper_info']={'original_title':'Verified Original Title'}
        self.assertEqual(publication.apply(paper)['report']['title'],'2109 · Verified Original Title')

    def test_sole_author_is_not_inferred_corresponding_but_explicit_evidence_survives(self):
        for old_default in (False, True):
            author = {'name': 'Terence Tao', 'corresponding': old_default}
            if old_default:
                author['corresponding_source'] = 'last_author_default'
            info = {'authors': [author], 'corresponding_mentioned': False}
            paper_info.apply_defaults(info)
            self.assertFalse(author['corresponding'])
            self.assertNotIn('corresponding_source', author)
        explicit = {'authors': [{'name': 'Alice', 'corresponding': True,
                                 'corresponding_evidence': 'Alice: corresponding author'}]}
        paper_info.apply_defaults(explicit)
        self.assertTrue(explicit['authors'][0]['corresponding'])

    def test_table_data_overrides_pruning_without_adding_other_figures(self):
        f={'id':'fig-17','kind':'table','caption':'Table 2: Results.','page':3}
        block={'paragraphs':['Table 2 的准确率为 80%。'],'figures':[],'data_tables':['fig-17'],'pages':[]}
        r={'figure_captions':[],'figure_coverage':[{'id':'fig-17','included':False}], 'sections':[{'key':'experiments','blocks':[block],'figures':[]}]}
        reading.attach_cited_tables(r,[f],{'fig-17':'各方法的准确率对比。'})
        self.assertEqual(block['figures'],['fig-17']);self.assertEqual(r['figure_captions'][0]['caption'],'各方法的准确率对比。')
        self.assertTrue(r['figure_coverage'][0]['included'])
        reading.attach_cited_tables(r,[f]);self.assertEqual(block['figures'],['fig-17'])
        block['data_tables']=['Table 2']
        reading.attach_cited_tables(r,[f]);self.assertEqual(block['data_tables'],['fig-17'])
        block['data_tables']=['invented']
        with self.assertRaises(ValueError):reading.attach_cited_tables(r,[f])
        block['data_tables']=[];block['paragraphs']=['Table 99 的分数很高。']
        with self.assertRaises(ValueError):reading.attach_cited_tables(r,[f])

    def test_auto_limits_and_manual_override(self):
        c={'output_tokens':2000,'output_tokens_auto':True,'deepseek':{'thinking':'disabled'}}
        self.assertEqual(providers.output_limit(c),8192)
        c['deepseek']['thinking']='high';self.assertEqual(providers.output_limit(c),65536)
        c['output_tokens_auto']=False;self.assertEqual(providers.output_limit(c),2000)

    def test_metadata_drops_unverified_affiliations_and_links(self):
        source='A Real Paper\nAlice Smith\nTest University'
        value={'original_title':'A Real Paper','authors':[{'name':'Alice Smith','affiliations':['Test University','Invented Lab']}], 'project_url':'https://fake.example','code_url':'javascript:alert(1)'}
        with patch('paperpilot.paper_info.source_material',return_value=(source,[])),patch('paperpilot.scholarly_metadata.venue',return_value=None):
            result=paper_info.extract({},lambda *args:{'value':value})
        self.assertEqual(result['authors'][0]['affiliations'],['Test University']);self.assertEqual(result['project_url'],'');self.assertEqual(result['code_url'],'')
        self.assertFalse(paper_info.safe_url('javascript:alert(1)'))

    def test_corresponding_role_needs_source_evidence_not_author_position(self):
        source='A Real Paper\nAlice Smith Test University\nBob Jones* Test University\n* Corresponding author'
        value={'original_title':'A Real Paper','authors':[{'name':'Alice Smith','affiliations':[]},{'name':'Bob Jones','affiliations':[],'corresponding':True,'corresponding_evidence':'invented evidence'}], 'organizations':['Test University']}
        with patch('paperpilot.paper_info.source_material',return_value=(source,[])),patch('paperpilot.scholarly_metadata.venue',return_value=None):
            result=paper_info.extract({},lambda *args:{'value':value})
            self.assertFalse(result['authors'][-1]['corresponding'])
            value['authors'][-1]['corresponding_evidence']='Bob Jones*'
            result=paper_info.extract({},lambda *args:{'value':value})
            self.assertTrue(result['authors'][-1]['corresponding'])
