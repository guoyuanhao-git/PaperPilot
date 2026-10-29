import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import test_core
from test_core import pdf, report
from test_figure_reading import generator, response
from paperpilot import documents, reading, reading_outline, service, store
from paperpilot.server import Handler, TOKEN


class ReadingOutline(unittest.TestCase):
    setUp = test_core.Core.setUp
    tearDown = test_core.Core.tearDown
    wait_job = test_core.Core.wait_job

    def test_input_bounds_and_default_compatibility(self):
        self.assertEqual(reading_outline.steps(), ['动机', '方法', '实验', '结论'])
        self.assertEqual(reading_outline.steps([' 为什么要做 ', '怎么复现']), ['为什么要做', '怎么复现'])
        for invalid in ([], '动机→方法', [''], ['方法', ' 方法 '], ['x'*81], ['摘要'], [str(i) for i in range(9)], [None]):
            with self.assertRaises(ValueError):
                reading_outline.validate(invalid)
        # Validation happens before creating a job or invoking a model.
        with patch('paperpilot.providers.generate') as model:
            with self.assertRaises(ValueError): service.analyze('unused', 'overview', outline=[])
            model.assert_not_called()

    def test_custom_order_is_enforced_without_reinstating_default_chapters(self):
        p = documents.ingest(pdf(), 'test.pdf')
        p['reading_outline'] = ['结论', '为什么有用', '复现要点']
        r = report(p)
        r['sections'] = [dict(s, paragraphs=['Evidence'], figures=[], pages=[], equations=[])
                         for s in reading_outline.chapters(p['reading_outline'])]
        self.assertEqual(service.validate_report(r, p)['sections'][0]['title'], '结论')
        for sections in (r['sections'][::-1], r['sections'][:-1], r['sections']+[dict(r['sections'][0])]):
            with self.assertRaises(ValueError): service.validate_report(dict(r, sections=sections), p)
        for mode in ('overview', 'detailed', 'deep'):
            guide = reading.mode_guide(mode, p['reading_outline'])
            self.assertIn('结论 → 为什么有用 → 复现要点', guide)
            self.assertNotIn('正文严格保留', guide)
            self.assertNotIn('2. 动机', guide)

    def test_custom_chapters_and_figures_flow_through_all_modes_and_providers(self):
        p = documents.ingest(pdf(), 'test.pdf')
        p['reading_outline'] = ['问题背景', '复现与关键证据', '我能借鉴什么']
        specs = reading_outline.chapters(p['reading_outline'])
        fallback = generator(p)
        prompts = []
        def generate(config, system, messages, images=(), structured=False, schema=None):
            props = schema['properties']
            prompts.append(messages[0]['content'])
            if 'sections' in props:
                value = report(p)
                value['sections'] = [dict(s, paragraphs=['核对当前论文的证据。'], figures=[], pages=[1], equations=[]) for s in specs]
                return response(value)
            result = fallback(config, system, messages, images, structured, schema)
            for field in ('items', 'decisions'):
                if field in props:
                    self.assertEqual(props[field]['items']['properties']['focus']['enum'], [s['key'] for s in specs])
                    for entry in result['value'][field]: entry['focus'] = specs[1]['key']
            return result
        for provider in ('codex', 'deepseek'):
            for mode in ('overview', 'detailed', 'deep'):
                with self.subTest(provider=provider, mode=mode), patch('paperpilot.providers.generate', side_effect=generate), patch('paperpilot.reading.math_style_examples', return_value=''):
                    result, figures = reading.build(p, mode, dict(store.settings(), provider=provider, vision=False), lambda _:None,
                        'test', service.report_schema, service.validate_report)
                self.assertEqual([s['key'] for s in result['sections']], ['abstract', *[s['key'] for s in specs], 'relevance'])
                self.assertEqual([s['title'] for s in result['sections'][1:-1]], p['reading_outline'])
                self.assertEqual(result['reading_outline'], p['reading_outline'])
                self.assertEqual(result['sections'][2]['figures'], [p['figures'][0]['id']])
                self.assertEqual(len(figures), 1)
                self.assertEqual(result['sections'][2].get('textbook', False), mode=='deep')
        self.assertTrue(any('问题背景 → 复现与关键证据 → 我能借鉴什么' in p for p in prompts))

    def test_outline_api_persists_without_changing_existing_report(self):
        p = documents.ingest(pdf(), 'test.pdf')
        p['report'] = report(p)
        store.save('paper', p)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
        def post(value):
            req = urllib.request.Request(f'http://127.0.0.1:{server.server_port}/api/paper-update', json.dumps(value).encode(), {'X-PaperPilot-Token':TOKEN})
            with urllib.request.urlopen(req) as result: return json.load(result)
        try:
            value = post({'id':p['id'], 'reading_outline':['关键假设', '适用边界']})
            self.assertEqual(value['reading_outline'], ['关键假设', '适用边界'])
            self.assertEqual(value['report'], p['report'])
            with self.assertRaises(urllib.error.HTTPError): post({'id':p['id'], 'reading_outline':['']})
            self.assertEqual(store.get('paper',p['id'])['reading_outline'], ['关键假设', '适用边界'])
            survey = post({'id':p['id'], 'paper_type':'survey'})
            self.assertEqual(survey['reading_outline'][0], '领域问题')
            post({'id':p['id'], 'reading_outline':['分类', '路线'], 'reading_outline_type':'survey'})
            restored = post({'id':p['id'], 'paper_type':'research'})
            self.assertEqual(restored['reading_outline'], ['关键假设', '适用边界'])
            self.assertEqual(restored['report'], p['report'])
            with self.assertRaises(urllib.error.HTTPError): post({'id':p['id'], 'paper_type':'invalid'})
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_failed_generation_keeps_report_and_saved_outline_can_translate_captions(self):
        p = documents.ingest(pdf(), 'test.pdf');p['report'] = report(p);store.save('paper',p)
        with patch('paperpilot.providers.generate', side_effect=ValueError('fixture failure')):
            job = self.wait_job(service.analyze(p['id'], 'overview', outline=['核心思想', '边界']))
        self.assertEqual(job['status'], 'failed')
        saved = store.get('paper',p['id'])
        self.assertEqual(saved['report'], p['report'])
        self.assertEqual(saved['reading_outline'], ['核心思想', '边界'])
        with patch('paperpilot.providers.generate', return_value=response({'figure_captions':[{'id':f['id'],'caption':'核对后的中文图注'} for f in saved['figures']]})):
            result = self.wait_job(service.translate_captions(p['id']))
        self.assertEqual(result['status'], 'completed', result)
