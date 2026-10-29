import copy
import json
import unittest
from unittest.mock import patch
from paperpilot import author_names, providers, reading, store


def block(ids):
    return {'paragraphs':['文字可以再次讨论 Figure 4，但图片只展示一次。'], 'highlights':[],
            'figures':ids, 'pages':[1], 'equations':[], 'data_tables':[]}


class ReadingModes(unittest.TestCase):
    def test_mathmatics_cross_chapter_figure_label_regression(self):
        # Same structure as the failed DeepSeek experiments stage: methods had
        # shown fig-4; experiments repeated its printed label, despite no new IDs.
        original = [block([]), block([]), block(['Figure 4'])]
        fixed = reading.reconcile_figures(original, [], [{'id':'fig-4','caption':'Figure 4. Pipeline'}], {'fig-4'})
        self.assertEqual([b['figures'] for b in fixed], [[],[],[]])
        self.assertEqual([b['paragraphs'] for b in fixed], [b['paragraphs'] for b in original])
        self.assertEqual(original[-1]['figures'], ['Figure 4'])

    def test_duplicate_image_keeps_all_text_and_unique_label_maps(self):
        source=[{'id':'crop-99','caption':'Figure 4: Pipeline'}]
        result=reading.reconcile_figures([block(['Figure 4']),block(['crop-99'])],['crop-99'],source)
        self.assertEqual([b['figures'] for b in result],[['crop-99'],[]])
        self.assertEqual(len(result),2)

    def test_unknown_unshown_and_ambiguous_never_silently_removed(self):
        source=[{'id':'a','caption':'Figure 4: First'},{'id':'b','caption':'Figure 4: Second'}]
        for value in ['Figure 4','Figure 400','a']:
            with self.assertRaisesRegex(ValueError,'未知'):
                reading.reconcile_figures([block([value])],[],source)
        with self.assertRaisesRegex(ValueError,'遗漏'):
            reading.reconcile_figures([block([])],['a'],source)

    def test_story_repairs_missing_once_and_keeps_expected_image(self):
        report={'sections':[{'key':k,'title':k} for k in ('motivation','method','experiments','conclusion')]}
        calls=[]
        def invoke(stage,prompt,schema):
            calls.append(stage)
            ids=['a'] if '修复方法' in stage else []
            return {'value':{'blocks':[block(ids)]}}
        result=reading.compose_story(report,[{'focus':'method','figures':['a']}],invoke,{'output_tokens':8192},[{'id':'a','caption':'Figure 1: Test'}])
        self.assertEqual(result[1]['figures'],['a'])
        self.assertEqual(len([s for s in calls if '修复' in s]),1)

    def test_conclusion_synthesizes_prior_story_without_new_figures(self):
        report={'sections':[{'key':k,'title':k} for k in ('motivation','method','experiments','conclusion')]}
        prompts=[]
        def invoke(stage,prompt,schema):
            prompts.append(prompt)
            return {'value':{'blocks':[block([])]}}
        chapters=reading.compose_story(report,[],invoke,{'output_tokens':8192})
        self.assertEqual([s['key'] for s in chapters],['motivation','method','experiments','conclusion'])
        self.assertIn('前面完整论证',prompts[-1])
        self.assertIn('回答开篇问题',prompts[-1])
        self.assertIn('meaning 用一句简洁中文概括这条公式的功能',prompts[1])
        self.assertIn('implementation 填空字符串',prompts[1])
        self.assertEqual(chapters[-1]['figures'],[])

    def test_per_mode_routing_and_optional_pro_vision(self):
        config=copy.deepcopy(store.DEFAULTS);config['provider']='deepseek'
        before=copy.deepcopy(config)
        for mode in ('overview','detailed','deep'):
            route=providers.reading_config(config,mode)
            self.assertEqual(route['deepseek']['model'],'deepseek-flash')
            self.assertEqual(route['deepseek']['thinking'],'low' if mode=='overview' else 'high')
        self.assertEqual(config,before)
        config['deepseek']['detail_model']='deepseek-v4-pro'
        route=providers.reading_config(config,'deep')
        self.assertEqual(route['deepseek']['model'],'deepseek-v4-pro')
        self.assertEqual(providers.image_config(route)['deepseek']['model'],'deepseek-flash')
        self.assertEqual(route['deepseek']['model'],'deepseek-v4-pro')
        config['provider']='codex';config['model']='gpt-6.1-sol'
        route=providers.reading_config(config,'deep')
        self.assertEqual(route['codex_reasoning_effort'],'high')
        self.assertEqual(config['codex_reasoning_effort'],'high')
        self.assertEqual(providers.reading_config(config,'overview')['codex_reasoning_effort'],'medium')
        config['reasoning_policy']={'custom_enabled':True,'overrides':{'study':'low'}}
        self.assertEqual(providers.reading_config(config,'detailed')['codex_reasoning_effort'],'low')
        self.assertEqual(providers.reading_config(config,'deep')['codex_reasoning_effort'],'low')

    def test_auxiliary_steps_skip_reasoning_without_changing_reading_preferences(self):
        config = providers.reading_config(dict(copy.deepcopy(store.DEFAULTS), provider='deepseek'), 'detailed')
        before = copy.deepcopy(config)
        for stage in ('翻译论文原始摘要', '整理作者、单位与项目链接', '修复 JSON 格式', '压缩方法正文（最多一次）'):
            routed = reading.stage_config(config, stage)
            self.assertEqual(routed['deepseek']['thinking'], 'disabled')
            self.assertEqual(providers.output_limit(routed), providers.output_limit(config))
        for stage in ('建立问题、方法与证据的阅读框架', '逐图阅读 1–3 / 12', '串联方法的图文论证 1/1', '形成助手判断与阅读建议'):
            self.assertEqual(reading.stage_config(config, stage)['deepseek']['thinking'], 'high')
        self.assertEqual(config, before)
        config['provider'] = 'codex'
        self.assertEqual(reading.stage_config(config, '修复 JSON 格式')['codex_reasoning_effort'], 'low')
        self.assertEqual(config['codex_reasoning_effort'], 'high')

    def test_textbook_preserves_concept_chapters_and_uses_source_not_overview(self):
        keys=['motivation','notation','intuition','method','training','implementation','experiments','navigation','conclusion']
        report={'sections':[{'key':k,'title':k} for k in keys]}
        prompts=[]
        def invoke(stage,prompt,schema):
            prompts.append(prompt)
            return {'value':{'blocks':[block([])]}}
        with patch('paperpilot.reading.math_style_examples',return_value='STYLE-SAMPLE'):
            chapters=reading.compose_textbook(report,[],invoke,{'output_tokens':16384},[],'ORIGINAL-SOURCE','GUIDE')
        self.assertEqual([s['key'] for s in chapters],keys)
        self.assertTrue(all(s['textbook'] for s in chapters))
        self.assertTrue(all('ORIGINAL-SOURCE' in p and 'STYLE-SAMPLE' in p for p in prompts))

    def test_each_mode_has_its_own_writing_constraints(self):
        self.assertIn('约 1000', reading.mode_guide('overview'))
        self.assertIn('500–900', reading.mode_guide('detailed'))
        self.assertIn('随机变量', reading.mode_guide('deep'))
        self.assertNotIn('正文严格保留', reading.mode_guide('deep'))
        self.assertNotIn('约 1000', reading.mode_guide('deep'))

    def test_known_chinese_name_only_no_fuzzy_name_guess(self):
        name=author_names.lookup('TERENCE TAO')
        self.assertEqual(name['name'],'陶哲轩')
        self.assertTrue(name['verified'])
        self.assertTrue(name['source_url'].startswith('https://'))
        for unknown in ('Tao','T. Tao','Unverified Author'):
            self.assertIsNone(author_names.lookup(unknown))

    def test_chinese_lookup_requires_same_full_name_and_employer(self):
        def claim(ident):
            return {'mainsnak':{'datavalue':{'value':{'id':ident}}}}
        author={'name':'Example Researcher','affiliations':['Example University']}
        values=[{'search':[{'id':'Q123','label':'Example Researcher'}]},
                {'entities':{'Q123':{'labels':{'en':{'value':'Example Researcher'},'zh':{'value':'已核实中文名'}},'claims':{'P31':[claim('Q5')],'P108':[claim('Q456')]}}}},
                {'entities':{'Q456':{'labels':{'en':{'value':'Example University'}}}}}]
        with patch('paperpilot.scholarly_metadata.fetch',side_effect=[json.dumps(v) for v in values]):
            self.assertEqual(author_names.resolve(author)['name'],'已核实中文名')
        author['affiliations']=['Different University']
        with patch('paperpilot.scholarly_metadata.fetch',side_effect=[json.dumps(v) for v in values]):
            self.assertIsNone(author_names.resolve(author))
        with patch('paperpilot.scholarly_metadata.fetch',side_effect=TimeoutError):
            self.assertIsNone(author_names.resolve(author))


if __name__ == '__main__':
    unittest.main()
