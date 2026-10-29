import json
from unittest.mock import patch
import test_core
from paperpilot import historical, store, title_search, user_profile, paper_identity

TITLE = 'pi0: A Vision-Language-Action Flow Model for General Robot Control'
INPUT = 'π₀: A Vision-Language-Action Flow Model for Genral Robot Control'
PAPER = {'id':'2410.24164', 'title':TITLE, 'abstract':'Verified public abstract.',
         'published':'2024-10-31', 'source_url':'https://arxiv.org/abs/2410.24164',
         'source':'papers_cool'}


class HistoricalResolution(test_core.unittest.TestCase):
    setUp = test_core.Core.setUp
    tearDown = test_core.Core.tearDown
    wait_job = test_core.Core.wait_job

    def model(self, titles):
        return patch('paperpilot.providers.generate', return_value={
            'value':{'candidates':[{'title':t} for t in titles]},
            'provider':'fixture', 'model':'fixture', 'usage':{}})

    def sources(self, hf, cool):
        return (patch('paperpilot.title_search.huggingface', side_effect=hf),
                patch('paperpilot.title_search.papers_cool', side_effect=cool),
                patch('paperpilot.title_search.arxiv', return_value=[]))

    def test_typo_resolves_from_online_evidence_preserves_input_and_skips_pdf(self):
        user_profile.save({'research_directions':'Robot learning'})
        hf, cool, arxiv = self.sources(lambda q:[], lambda q:[PAPER])
        with hf, cool as source, arxiv, self.model([TITLE]) as model:
            job = self.wait_job(historical.start('2410 | '+INPUT+' | π0', 'starred'))
            self.assertEqual(job['status'],'completed')
            self.assertTrue(job['result']['results'][0]['ok'], job['result'])
            self.assertEqual(job['result']['results'][0]['matched_title'], TITLE)
            paper = store.all_objects('paper')[0]
            self.assertEqual(paper['import_input_title'],INPUT)
            self.assertEqual(paper_identity.label(paper),'2410 π0')
            self.assertEqual(paper['read_status'],'已精读')
            self.assertTrue(paper['metadata_only'])
            self.assertEqual(source.call_count,1)  # Reuse online evidence when title is corrected.
            model.assert_called_once()
            payload = json.loads(model.call_args.args[2][0]['content'])
            self.assertIn('Robot learning',payload['research_context'])
            self.assertEqual(payload['publication_month'],'2024-10')
            self.assertEqual(payload['online_candidates'][0]['title'],TITLE)

    def test_model_title_is_searched_then_exactly_verified(self):
        hf, cool, arxiv = self.sources(lambda q:[PAPER] if q==TITLE else [],lambda q:[])
        with hf as source, cool, arxiv, self.model([TITLE]):
            result, month=historical.lookup(INPUT,month='2024-10',short='π0')
            self.assertEqual(month,'2024-10')
            self.assertEqual(result['title'],TITLE)
            self.assertEqual([c.args[0] for c in source.call_args_list],[INPUT,TITLE])

    def test_direct_symbol_match_has_no_model_cost(self):
        latex = {**PAPER,'title':TITLE.replace('pi0',r'$\pi_0$')}
        hf,cool,arxiv=self.sources(lambda q:[],lambda q:[latex])
        with hf,cool,arxiv,self.model([]) as model:
            self.assertEqual(historical.lookup(TITLE.replace('pi0','π₀'))[1],'2024-10')
            model.assert_not_called()

    def test_unverified_wrong_month_or_unrelated_model_titles_are_not_imported(self):
        for generated, rows, month in [(TITLE, [],'2024-10'),
                                                                            ('Completely unrelated paper',[PAPER],'2024-10')]:
            hf,cool,arxiv=self.sources(lambda q:rows,lambda q:[])
            with self.subTest(title=generated,month=month),hf,cool,arxiv,self.model([generated]):
                with self.assertRaisesRegex(ValueError,'未能核实'):
                    historical.lookup(INPUT,month=month,short='π0')
            self.assertEqual(store.all_objects('paper'),[])

    def test_corrected_title_is_identified_before_month_validation(self):
        hf,cool,arxiv=self.sources(lambda q:[PAPER],lambda q:[])
        with hf,cool,arxiv,self.model([TITLE]):
            row=historical.parse('2412 | '+INPUT+' | pi0','read')[0]
            with self.assertRaisesRegex(ValueError,'核实年月为 2024-10.*2024-12'):
                historical.import_one(row,'read')
            self.assertEqual(store.all_objects('paper'),[])

    def test_ambiguous_candidates_require_confirmation_before_month_validation(self):
        other_title=TITLE.replace('General','General-Purpose')
        other={**PAPER,'id':'2410.00002','title':other_title,'source_url':'https://arxiv.org/abs/2410.00002'}
        hf,cool,arxiv=self.sources(lambda q:[PAPER,other],lambda q:[])
        with hf,cool,arxiv,self.model([TITLE,other_title]):
            for published in ('2024-10-31','2025-04-01'):
                other['published']=published
                with self.assertRaisesRegex(ValueError,'多篇候选'):
                    historical.lookup(INPUT,month='2024-10')

    def test_model_failure_isolated_to_one_row_and_original_settings_preserved(self):
        hf,cool,arxiv=self.sources(lambda q:[],lambda q:[])
        before=store.settings()
        with hf,cool,arxiv,patch('paperpilot.providers.generate',side_effect=RuntimeError('secret internal failure')):
            job=self.wait_job(historical.start('2410 | '+INPUT+' | π0','read'))
            self.assertEqual(job['status'],'completed')
            row=job['result']['results'][0]
            self.assertFalse(row['ok'])
            self.assertIn('模型辨认未完成',row['error'])
            self.assertNotIn('secret',row['error'])
            self.assertEqual(store.settings(),before)
            self.assertEqual(store.all_objects('paper'),[])
