import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import test_core
from test_figure_reading import generator, response
from paperpilot import documents, paper_types, reading, reading_outline, service, store


class PaperTypes(unittest.TestCase):
    setUp = test_core.Core.setUp
    tearDown = test_core.Core.tearDown
    wait_job = test_core.Core.wait_job

    def paper(self):
        return documents.ingest(test_core.pdf(), 'survey-fixture.pdf')

    def test_independent_outlines_migrate_and_restore_without_changing_report(self):
        paper = self.paper()
        paper['reading_outline'] = ['关键假设', '如何复现']
        paper['report'] = test_core.report(paper)
        previous = copy.deepcopy(paper['report'])
        paper_types.update(paper, {'paper_type': 'survey'})
        self.assertEqual(paper['reading_outline'], paper_types.SURVEY_OUTLINE)
        paper_types.update(paper, {'reading_outline': ['分类依据', '路线比较']})
        paper_types.update(paper, {'paper_type': 'research'})
        self.assertEqual(paper['reading_outline'], ['关键假设', '如何复现'])
        paper_types.update(paper, {'paper_type': 'survey'})
        self.assertEqual(paper['reading_outline'], ['分类依据', '路线比较'])
        self.assertEqual(paper['report'], previous)
        for invalid in ('review', '', None):
            with self.assertRaises(ValueError):
                paper_types.validate(invalid)

    def test_default_and_legacy_types_never_call_model_or_read_source(self):
        paper = self.paper()
        source = documents.directory(paper['id']) / 'pages.json'
        source.unlink()
        for provider in ('codex', 'deepseek'):
            with patch('paperpilot.providers.generate') as model:
                prepared = paper_types.prepare(store.get('paper', paper['id']), dict(store.settings(), provider=provider), lambda _: None)
            model.assert_not_called()
            self.assertEqual(prepared['paper_type'], 'research')
            self.assertEqual(prepared['reading_outline'], reading_outline.DEFAULT)
        legacy = store.get('paper', paper['id'])
        legacy.update(paper_type='auto', paper_type_detection={'type':'survey', 'key':'old-source'})
        store.save('paper', legacy)
        with patch('paperpilot.providers.generate') as model:
            prepared = paper_types.prepare(legacy, store.settings(), lambda _: None)
        model.assert_not_called()
        self.assertEqual(prepared['paper_type'], 'survey')
        self.assertEqual(prepared['reading_outline'], paper_types.SURVEY_OUTLINE)
        self.assertEqual(store.get('paper', paper['id'])['paper_type'], 'survey')
        with self.assertRaises(ValueError): paper_types.validate('auto')

    def test_concurrent_edit_preserves_preferences(self):
        paper = self.paper()
        changed = copy.deepcopy(paper)
        paper_types.update(changed, {'paper_type': 'survey'})
        store.save('paper', changed)
        with self.assertRaisesRegex(ValueError, '已修改'):
            paper_types.prepare(paper, store.settings(), lambda _: None)
        self.assertEqual(store.get('paper', paper['id'])['paper_type'], 'survey')

    def test_manual_report_preparation_and_account_isolation(self):
        paper = self.paper()
        paper_types.update(paper, {'paper_type':'survey'})
        store.save('paper', paper)
        with patch('paperpilot.reading.build', return_value=({'figure_captions':[]}, [])) as build:
            job = self.wait_job(service.analyze(paper['id'], 'overview'))
        self.assertEqual(job['status'], 'completed', job.get('error'))
        self.assertEqual(build.call_args.args[0]['reading_outline'], paper_types.SURVEY_OUTLINE)
        with store.scope({'directory': Path(self.tmp.name)/'another-user'}):
            store.init()
            other = self.paper()
            with patch('paperpilot.providers.generate') as model:
                other = paper_types.prepare(other, store.settings(), lambda _:None)
            model.assert_not_called()
            self.assertEqual(other['reading_outline'], reading_outline.DEFAULT)
        self.assertEqual(store.get('paper', paper['id'])['paper_type'], 'survey')

    def test_survey_all_modes_use_type_specific_chapters_and_evidence(self):
        paper = self.paper()
        paper_types.update(paper, {'paper_type': 'survey'})
        specs = reading_outline.chapters(paper_types.SURVEY_OUTLINE)
        fallback = generator(paper)
        def model(config, system, messages, images=(), structured=False, schema=None):
            self.assertIn('当前是综述论文', system)
            props = schema['properties']
            if 'sections' in props:
                value = test_core.report(paper)
                value['sections'] = [dict(s, paragraphs=['分类依据与路线比较。'], figures=[], pages=[1], equations=[]) for s in specs]
                return response(value)
            value = fallback(config, system, messages, images, structured, schema)
            for field in ('items', 'decisions'):
                if field in props:
                    for item in value['value'][field]:
                        item['focus'] = specs[1]['key']
            return value
        for provider in ('codex', 'deepseek'):
            for mode in ('overview', 'detailed', 'deep'):
                with self.subTest(provider=provider, mode=mode), patch('paperpilot.providers.generate', side_effect=model), patch('paperpilot.reading.math_style_examples', return_value='参考风格'):
                    report, figures = reading.build(paper, mode, dict(store.settings(), provider=provider, vision=False),
                        lambda _: None, 'test', service.report_schema, service.validate_report)
                self.assertEqual(report['paper_type'], 'survey')
                self.assertEqual([s['title'] for s in report['sections'][1:-1]], paper_types.SURVEY_OUTLINE)
                self.assertEqual(report['sections'][0]['key'], 'abstract')
                self.assertEqual(report['sections'][-1]['key'], 'relevance')
                self.assertEqual(len(figures), 1)
                self.assertIn('不逐篇罗列', reading.mode_guide('overview', paper_types.SURVEY_OUTLINE, 'survey'))
