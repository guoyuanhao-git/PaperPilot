import io
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from reportlab.pdfgen import canvas

from paperpilot import discovery, documents, providers, service, store, assistant_memory, user_profile, credentials
from paperpilot.server import Handler, TOKEN
from http.server import ThreadingHTTPServer


def pdf():
    stream = io.BytesIO()
    c = canvas.Canvas(stream, pagesize=(600, 800), invariant=1)
    c.drawString(40, 750, 'Research motivation: action generation for robot manipulation.')
    c.drawString(40, 730, 'Method: train a velocity field. Results require comparable baselines.')
    c.rect(40, 410, 400, 230)
    c.drawString(40, 390, 'Figure 1. A test figure for validating crop extraction.')
    c.showPage()
    c.drawString(40, 750, 'Experiments: a fixture for software tests, not a published paper.')
    c.save()
    return stream.getvalue()


def report(paper):
    return {'title': 'Software test fixture', 'summary': 'This report is only a software fixture.', 'sections': [
        {'key': k, 'title': k, 'paragraphs': ['Sample paragraph.'], 'pages': [1], 'figures': [], 'equations': []}
        for k in ('motivation', 'method', 'experiments', 'conclusion')]}


class Core(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = store.DATA
        store.DATA = Path(self.tmp.name)
        providers.KEYS.clear()
        credentials.CACHE.clear()
        self.fake_secrets = {}
        def vault(action, service, key=None):
            if action == 'save': self.fake_secrets[service] = key
            if action == 'delete': self.fake_secrets.pop(service, None)
            return self.fake_secrets.get(service, '')
        patcher = patch('paperpilot.credentials.backend', side_effect=vault)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(credentials.CACHE.clear)
        store.init()

    def tearDown(self):
        store.DATA = self.old
        self.tmp.cleanup()
        providers.KEYS.clear()

    def test_store_limits_rows_before_decoding_without_changing_order(self):
        for i in range(6):
            store.save('route', {'id': str(i), 'text': str(i)})
        all_rows = store.all_objects('route')
        self.assertEqual(store.all_objects('route', limit=2), all_rows[:2])
        self.assertEqual(store.all_objects('route', limit=20), all_rows)
        self.assertEqual(store.all_objects('route', limit=0), [])
        self.assertEqual(store.all_objects('other', limit=2), [])
        for limit in (-1, True, '2', 1.5):
            with self.assertRaises(ValueError):
                store.all_objects('route', limit=limit)
        # An old large/malformed body outside the requested window is not decoded.
        with store.connect() as db:
            db.execute('UPDATE objects SET body=? WHERE kind=? AND id=?', ('invalid JSON', 'route', '0'))
        self.assertEqual(store.all_objects('route', limit=2), all_rows[:2])

    def test_pdf_dedup_text_and_crop(self):
        p = documents.ingest(pdf(), 'sample.pdf')
        self.assertEqual(p['page_count'], 2)
        self.assertEqual(len(p['figures']), 1)
        self.assertLess(p['figures'][0]['bbox'][3], .5)  # English caption begins below this boundary.
        image = documents.crop_figure(p['id'], p['figures'][0])
        self.assertGreater(image.stat().st_size, 100)
        f=p['figures'][0]
        different=documents.crop_figure(p['id'],{**f,'bbox':[.05,.05,.7,.5]})
        self.assertNotEqual(image,different)
        self.assertEqual(image,documents.crop_figure(p['id'],f))
        self.assertEqual(documents.ingest(pdf(), 'sample2.pdf')['page_count'], 2)
        text, scope = documents.context(p, 10000)
        self.assertIn('第 2 页', text)
        self.assertIn('全部 2 页', scope)
        with self.assertRaises(ValueError):
            documents.crop_figure(p['id'], {**p['figures'][0], 'bbox': [0, .8, 1, .2]})

    def test_legacy_crop_migration_keeps_manual_selection(self):
        p = documents.ingest(pdf(), 'sample.pdf')
        f = p['figures'][0]
        expected = f['bbox'][3]
        f['bbox'][3] = .56
        f.pop('crop_version')
        p['report'] = {'figures': [dict(f, bbox=list(f['bbox']))]}
        manual = dict(f, id='fig-2', auto_crop=False, bbox=[.1, .1, .8, .8])
        p['figures'].append(manual)
        p['figures'].append(dict(f, id='fig-3', caption='Figure 1a presents a prose reference', bbox=[.05, .1, .8, .7]))
        store.save('paper', p)
        documents.upgrade_library_figures()
        p = store.get('paper', p['id'])
        self.assertAlmostEqual(p['figures'][0]['bbox'][3], expected)
        self.assertAlmostEqual(p['report']['figures'][0]['bbox'][3], expected)
        self.assertEqual(p['figures'][1]['bbox'], manual['bbox'])
        self.assertEqual(len(p['figures']), 2)
        self.assertIsNone(documents.caption_number('Figure 3a shows a result'))
        self.assertIsNone(documents.caption_number('Figure 3 shows a result'))

    def test_delete_removes_files_and_keeps_only_opted_in_history(self):
        p = documents.ingest(pdf(), 'sample.pdf')
        p.update(notes='private thoughts', feedback='weak motivation', read_status='已速览', report={'summary': 'long content'}, messages=[{'content': 'secret chat'}])
        store.save('paper', p)
        drafts = store.DATA / 'drafts'
        drafts.mkdir()
        (drafts / (p['id'] + '-test.json')).write_text('draft')
        store.save('job', {'id': 'active', 'paper_id': p['id'], 'status': 'running'})
        with self.assertRaises(ValueError):
            service.delete_paper(p['id'], True)
        self.assertTrue(documents.directory(p['id']).exists())
        store.save('job', {'id': 'active', 'paper_id': p['id'], 'status': 'completed'})
        service.delete_paper(p['id'], True)
        self.assertEqual(store.all_objects('paper'), [])
        self.assertFalse(documents.directory(p['id']).exists())
        self.assertEqual(list(drafts.iterdir()), [])
        self.assertEqual(store.all_objects('job'), [])
        record = store.get('reading_history', p['id'])
        self.assertEqual(record['feedback'], 'weak motivation')
        self.assertFalse({'notes', 'report', 'messages', 'figures'} & record.keys())
        self.assertIn('weak motivation', store.feedback_context())
        p = documents.ingest(pdf(), 'sample.pdf')
        self.assertEqual(p['feedback'], 'weak motivation')
        self.assertEqual(store.all_objects('reading_history'), [])
        service.delete_paper(p['id'], False)
        self.assertEqual(store.all_objects('reading_history'), [])
        self.assertNotIn('weak motivation', store.feedback_context())

    def test_caption_rewrite_updates_report_and_validates_highlights(self):
        p = documents.ingest(pdf(), 'sample.pdf')
        p['report'] = report(p)
        p['report']['figures'] = p['figures']
        store.save('paper', p)
        result = {'value': {'figure_captions': [{'id': 'fig-1', 'caption': '用于裁剪验证的测试图'}]}, 'usage': {}}
        with patch('paperpilot.providers.generate', return_value=result):
            j = self.wait_job(service.translate_captions(p['id']))
        self.assertEqual(j['status'], 'completed', j.get('error'))
        saved = store.get('paper', p['id'])
        self.assertEqual(saved['report']['figures'][0]['caption_zh'], '用于裁剪验证的测试图')
        self.assertIn('Figure 1', saved['figures'][0]['caption'])
        r = report(p)
        r['sections'][0]['highlights'] = ['not present in text']
        with self.assertRaises(ValueError):
            service.validate_report(r, p)

    def test_provider_adapters_and_truncation(self):
        c = store.settings()
        c['provider'] = 'openai'
        with self.assertRaises(ValueError):
            providers.generate(c, 'json', [{'role': 'user', 'content': 'hi'}])
        c['provider'] = 'deepseek'
        providers.KEYS['deepseek'] = 'test-secret'
        data = {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":true}'}}]}
        with patch('paperpilot.providers.post_json', return_value=data) as api:
            self.assertTrue(providers.generate(c, 'json', [{'role': 'user', 'content': 'json'}], structured=True)['value']['ok'])
            self.assertEqual(api.call_args.args[1]['response_format'], {'type': 'json_object'})
        data['choices'][0]['finish_reason'] = 'length'
        with patch('paperpilot.providers.post_json', return_value=data), self.assertRaises(ValueError):
            providers.generate(c, 'json', [{'role': 'user', 'content': 'json'}])

    def test_codex_adapter_schema_and_inference_only_flags(self):
        import subprocess
        config=store.settings()
        schema={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False}
        def run(cmd,**kwargs):
            output=Path(cmd[cmd.index('--output-last-message')+1])
            output.write_text('{"ok":true}')
            schema_path=Path(cmd[cmd.index('--output-schema')+1])
            self.assertEqual(json.loads(schema_path.read_text()),schema)
            self.assertIn('web_search="disabled"',cmd)
            self.assertIn('model_reasoning_effort="high"',cmd)
            self.assertIn('--ignore-user-config',cmd)
            self.assertIn('model_provider="paperpilot-http"', cmd)
            self.assertIn('model_providers.paperpilot-http={name="OpenAI",wire_api="responses",'
                          'requires_openai_auth=true,supports_websockets=false}', cmd)
            self.assertEqual(cmd[cmd.index('--model')+1], 'gpt-6.1-sol')
            for feature in ('shell_tool','apps','plugins','multi_agent'):
                self.assertIn(feature,cmd)
            return subprocess.CompletedProcess(cmd,0,'','')
        with patch('paperpilot.providers.shutil.which',return_value='/test/codex'),patch('paperpilot.providers.subprocess.run',side_effect=run):
            response=providers.generate(config,'json',[{'role':'user','content':'json'}],structured=True,schema=schema)
        self.assertTrue(response['value']['ok'])
        self.assertEqual(response['usage']['transport'], 'https')
        self.assertEqual(response['usage']['reasoning_effort'], 'high')

    def test_codex_capacity_error_is_not_misreported_as_auth_failure(self):
        import subprocess
        c = store.settings()
        with patch('paperpilot.providers.shutil.which', return_value='/test/codex'), patch('paperpilot.providers.subprocess.run', return_value=subprocess.CompletedProcess([], 1, '', 'ERROR: Selected model is at capacity. Please try a different model.')):
            with self.assertRaisesRegex(ValueError, '当前满载'):
                providers.generate(c, 'json', [{'role': 'user', 'content': 'json'}], structured=True)

    def test_report_rejects_missing_sections_false_pages_and_figures(self):
        p = documents.ingest(pdf(), 'sample.pdf')
        r = report(p)
        service.validate_report(r, p)
        r['sections'][0]['pages'] = [99]
        with self.assertRaises(ValueError):
            service.validate_report(r, p)
        r['sections'][0]['pages'] = [1]
        r['sections'][0]['figures'] = ['invented']
        with self.assertRaises(ValueError):
            service.validate_report(r, p)
        with self.assertRaises(ValueError):
            service.validate_report({'title': 'x', 'summary': 'x', 'sections': []}, p)
        r=report(p)
        r['sections'][1]['figures']=[{'id':p['figures'][0]['id'],'explanation':'一个图表说明'}]
        service.validate_report(r,p)
        self.assertEqual(r['sections'][1]['figures'],[p['figures'][0]['id']])
        self.assertIn('一个图表说明',r['sections'][1]['paragraphs'][-1])

    def test_arxiv_urls_block_other_origins(self):
        self.assertEqual(discovery.arxiv_id('https://arxiv.org/abs/2210.02747v2'), '2210.02747v2')
        self.assertEqual(discovery.arxiv_id('https://arxiv.org/pdf/1503.03585.pdf'), '1503.03585')
        for url in ['http://localhost/private', 'https://arxiv.org.evil.test/pdf/2210.02747', 'file:///etc/passwd']:
            with self.assertRaises(ValueError):
                discovery.arxiv_id(url)

    def test_import_arxiv_id_and_url_normalize_to_official_https(self):
        for value in ('2603.16666', ' arXiv:2603.16666 ', 'https://arxiv.org/abs/2603.16666',
                      'https://arxiv.org/pdf/2603.16666.pdf', 'https://arXIv.org/2603.16666',
                      'http://arxiv.org/abs/2603.16666?download=1'):
            self.assertEqual(discovery.import_url(value), 'https://arxiv.org/abs/2603.16666')
        for ident in ('2603.16666v2', 'hep-th/9901001'):
            self.assertEqual(discovery.import_url(ident), 'https://arxiv.org/abs/' + ident)
        for value in (None, '', 'FastWAM', 'https://arxiv.org.evil.test/2603.16666',
                      'https://user:pass@arxiv.org/abs/2603.16666', 'file:///etc/passwd', '../2603.16666'):
            with self.assertRaises(ValueError): discovery.import_url(value)
        with patch('paperpilot.service.job', return_value={'id':'mock-job'}) as job:
            service.import_paper('2603.16666')
        with patch('paperpilot.discovery.download', side_effect=ValueError('stop before ingest')) as download:
            with self.assertRaisesRegex(ValueError, 'stop before ingest'):
                job.call_args.args[1](lambda message: None)
        self.assertEqual(download.call_args.args[0], 'https://arxiv.org/abs/2603.16666')

    def test_model_redirect_does_not_forward_secret(self):
        seen=[]
        from http.server import BaseHTTPRequestHandler
        class Redirect(BaseHTTPRequestHandler):
            def log_message(self,*_): pass
            def do_POST(self):
                self.send_response(302)
                self.send_header('Location','/other')
                self.end_headers()
            def do_GET(self):
                seen.append(self.headers.get('Authorization'))
                self.send_response(200)
                self.end_headers()
        server=ThreadingHTTPServer(('127.0.0.1',0),Redirect)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with self.assertRaises(ValueError) as error:
                providers.post_json('http://127.0.0.1:'+str(server.server_port),{},'PRIVATE-secret')
            self.assertNotIn('PRIVATE-secret',str(error.exception))
            self.assertEqual(seen,[])
        finally:
            server.shutdown();server.server_close()

    def test_legacy_schedule_never_automatically_calls_model(self):
        with patch('paperpilot.service.recommend') as recommend:
            service.schedule_tick()
            recommend.assert_not_called()
            c=store.settings()
            c['schedule'].update(enabled=True,next_run='2020-01-01T00:00:00+00:00')
            store.save_settings(c)
            service.schedule_tick()
            service.schedule_tick()
            self.assertEqual(recommend.call_count, 0)

    def wait_job(self, job):
        deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            current=store.get('job',job['id'])
            if current['status'] in ('completed','failed'):
                return current
            time.sleep(.03)
        self.fail('Background job did not finish')

    def test_analysis_chat_and_feedback_persistence(self):
        p=documents.ingest(pdf(),'sample.pdf')
        p['feedback']='方法动机解释清楚'
        store.save('paper',p)
        user_profile.save({'paper_taste':'方法动机解释清楚'})
        response={'value':report(p),'usage':{},'provider':'fixture','model':'test'}
        from test_figure_reading import generator
        with patch('paperpilot.providers.generate',side_effect=generator(p)) as generate:
            j=self.wait_job(service.analyze(p['id'],'overview'))
            self.assertEqual(j['status'],'completed',j.get('error'))
            self.assertIn('方法动机解释清楚',generate.call_args.args[1])
        response['value']='见 PDF 第 1 页；这是基于测试材料的解释。'
        with patch('paperpilot.providers.generate',return_value=response):
            j=self.wait_job(service.chat(p['id'],'方法的动机是什么？'))
            self.assertEqual(j['status'],'completed',j.get('error'))
        saved=store.get('paper',p['id'])
        self.assertEqual(len(saved['messages']),2)
        self.assertEqual(saved['feedback'],'方法动机解释清楚')
        self.assertIsNotNone(saved['report'])

    def test_recommendation_rejects_invented_paper_and_deduplicates_versions(self):
        candidate={'id':'2210.02747v2','title':'Verified candidate','source_url':'https://arxiv.org/abs/2210.02747v2','abstract':'Sample','authors':[]}
        response={'value':{'recommendations':[{'id':'invented','reason':'x','taste':'x','tracking':'x'}]},'usage':{},'provider':'fixture','model':'test'}
        with patch('paperpilot.discovery.search',return_value=[candidate]), patch('paperpilot.providers.generate',return_value=response):
            j=self.wait_job(service.recommend('query'))
            self.assertEqual(j['status'],'failed')
            self.assertEqual(store.all_objects('discovery'),[])
        store.save('reading_history',{'id':'previous','source_url':'https://arxiv.org/abs/2210.02747v1'})
        with patch('paperpilot.discovery.search',return_value=[candidate]), patch('paperpilot.providers.generate') as generate:
            j=self.wait_job(service.recommend('query'))
            self.assertEqual(j['status'],'completed')
            generate.assert_not_called()

    def test_chinese_request_is_translated_before_search(self):
        translated={'value':{'query':'all:"cloth manipulation"'},'usage':{},'provider':'fixture','model':'test'}
        ranked={'value':{'recommendations':[]},'usage':{},'provider':'fixture','model':'test'}
        candidate={'id':'2210.02747v2','title':'Candidate','abstract':'Sample'}
        with patch('paperpilot.discovery.search',return_value=[candidate]) as search, patch('paperpilot.providers.generate',side_effect=[translated,ranked]):
            j=self.wait_job(service.recommend('帮我找布料操作的数据生成论文'))
            self.assertEqual(j['status'],'completed',j.get('error'))
            self.assertEqual(search.call_args.args[0],'all:"cloth manipulation"')
            self.assertEqual(j['result']['resolved_query'],'all:"cloth manipulation"')

    def test_http_upload_persistence_csrf_and_secret_redaction(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        def post(path, value, token=TOKEN, raw=False):
            req=urllib.request.Request(base+path, value if raw else json.dumps(value).encode(), {'X-PaperPilot-Token': token})
            with urllib.request.urlopen(req) as r:
                return json.load(r)
        try:
            p=post('/api/upload', pdf(), raw=True)
            post('/api/paper-update', {'id': p['id'], 'feedback': 'Clear motivation'})
            with self.assertRaises(urllib.error.HTTPError) as failure:
                post('/api/paper-update', {'id': p['id'], 'read_status': '已速览'})
            self.assertEqual(failure.exception.code, 400)
            post('/api/paper-update', {'id': p['id'], 'notes': 'My own thoughts, not the model report'})
            saved = store.get('paper', p['id'])
            self.assertEqual(saved['notes'], 'My own thoughts, not the model report')
            self.assertTrue(saved['notes_updated_at'])
            from paperpilot import library
            saved.update(publication_month='2021-06', short_title='Fixture')
            saved['report'] = {'mode': 'overview', 'generated_at': service.now()}
            library.report_ready(saved)
            store.save('paper', saved)
            post('/api/paper-reading', {'id': p['id'], 'action': 'star', 'starred': True})
            finished = post('/api/paper-reading', {'id': p['id'], 'action': 'finish', 'report_at': saved['report']['generated_at'], 'mode': 'deep'})
            self.assertEqual(finished['read_status'], '已速览')  # The stored report decides the mode.
            self.assertTrue(finished['starred'])
            liked = post('/api/paper-reading', {'id': p['id'], 'action': 'preference', 'preference': 'liked'})
            self.assertTrue(liked['liked']); self.assertFalse(liked['starred'])
            self.assertEqual(liked['read_status'], '已速览')
            self.assertEqual(liked['reading_completions'], finished['reading_completions'])
            for i in range(25):
                store.save('job', {'id': str(i), 'status': 'completed'})
                store.save('route', {'id': str(i), 'text': 'Saved route'})
            store.save('discovery', {'id': 'legacy', 'recommendations': []})
            with urllib.request.urlopen(base+'/api/bootstrap') as r:
                bootstrap = json.load(r)
            self.assertEqual(bootstrap['reading_stats'], {'today': 1, 'week': 1})
            self.assertEqual(len(bootstrap['jobs']), 20)
            self.assertEqual(len(bootstrap['routes']), 5)
            self.assertNotIn('discoveries', bootstrap)
            self.assertEqual(len(store.all_objects('job')), 25)
            self.assertEqual(len(store.all_objects('route')), 25)
            self.assertTrue(store.get('discovery', 'legacy'))
            post('/api/settings', {'provider': 'deepseek', 'deepseek_key': 'SECRET-not-for-browser'})
            with urllib.request.urlopen(base+'/api/bootstrap') as r:
                data=r.read().decode()
            self.assertNotIn('SECRET-not-for-browser', data)
            self.assertNotIn('SECRET-not-for-browser', (store.DATA/'paperpilot.sqlite').read_bytes().decode(errors='ignore'))
            self.assertIn('Clear motivation', data)
            with self.assertRaises(urllib.error.HTTPError) as failure:
                post('/api/profile', {'text': 'bad'}, token='invalid')
            self.assertEqual(failure.exception.code, 403)
            req=urllib.request.Request(base+'/api/bootstrap',headers={'Host':'evil.test'})
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(req)
            with self.assertRaises(urllib.error.HTTPError):
                post('/api/paper-delete', {'id': p['id'], 'keep_history': True}, token='invalid')
            self.assertTrue(store.get('paper', p['id']))
            post('/api/paper-delete', {'id': p['id'], 'keep_history': True})
            with urllib.request.urlopen(base+'/api/bootstrap') as r:
                self.assertEqual(json.load(r)['reading_stats'], {'today': 0, 'week': 0})
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(base + '/files/' + p['id'] + '/source.pdf')
            post('/api/history-delete', {'id': p['id']})
            self.assertEqual(store.all_objects('reading_history'), [])
        finally:
            server.shutdown()
            server.server_close()


if __name__=='__main__':
    unittest.main()
