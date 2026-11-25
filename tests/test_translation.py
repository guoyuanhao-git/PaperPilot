import unittest
from unittest.mock import patch
import test_core
from paperpilot import documents, store, translation, service

class Translation(unittest.TestCase):
    def setUp(self):
        test_core.Core.setUp(self)
        # Identity parsing has separate tests; these fixtures contain no author block.
        from paperpilot import report_cache
        patcher=patch('paperpilot.paper_info.extract',return_value={
            'original_title':'Synthetic paper','authors':[], 'organizations':[],
            'fetched_at':report_cache.now()})
        patcher.start();self.addCleanup(patcher.stop)
    tearDown = test_core.Core.tearDown
    wait_job = test_core.Core.wait_job

    def test_shared_caption_preserves_crops_and_unrelated_snapshots(self):
        paper={'figures':[{'id':'fig-1','caption':'Figure 2. Text','caption_zh':'手动中文'}],
               'report':{'figures':[{'id':'fig-1','caption':'Figure 2. Text','bbox':[0,0,1,1]}]},
               'translation':{'figures':[{'id':'fig-1','caption':'Figure 2. Text','image_file':'kept.png'},
                                         {'id':'fig-2','caption':'Old','caption_zh':'历史图注'}]}}
        documents.sync_captions(paper)
        self.assertEqual(paper['report']['figures'][0]['caption_zh'],'手动中文')
        self.assertEqual(paper['report']['figures'][0]['bbox'],[0,0,1,1])
        self.assertEqual(paper['translation']['figures'][0]['caption_zh'],'手动中文')
        self.assertEqual(paper['translation']['figures'][0]['image_file'],'kept.png')
        self.assertEqual(paper['translation']['figures'][1]['caption_zh'],'历史图注')

    def test_independent_report_and_resumable_chunks(self):
        paper=documents.ingest(test_core.pdf(), 'fixture.pdf')
        paper['report']={'summary':'existing'}
        store.save('paper',paper)
        result={'value':{'translation':'正文译文 $x_i$','omitted':'图注','warning':'','caption':'Figure 1. 测试图注','overview':'全文结构','terminology':'术语表','constraints':'不增补'},'usage':{},'model':'fixture','provider':'fixture'}
        with patch('paperpilot.providers.generate',side_effect=[result,ValueError('interrupted')]):
            failed=self.wait_job(service.analyze(paper['id'],'translation'))
        self.assertEqual(failed['status'],'failed')
        self.assertEqual(store.get('paper',paper['id'])['report'],paper['report'])
        with patch('paperpilot.providers.generate',return_value=result) as model:
            completed=self.wait_job(service.analyze(paper['id'],'translation'))
        self.assertEqual(completed['status'],'completed',completed.get('error'))
        self.assertEqual(model.call_count,2)
        saved=store.get('paper',paper['id'])
        self.assertEqual(saved['report'],paper['report'])
        self.assertEqual(len(saved['translation']['sections']),1)

    def test_released_pdf_rejected(self):
        paper=documents.ingest(test_core.pdf(),'fixture.pdf')
        paper['pdf_released']=True
        with self.assertRaises(ValueError):translation.source(paper)

    def test_translated_figures_survive_pdf_release_and_report_deletion(self):
        from paperpilot import paper_storage, image_cache
        from paperpilot.reading_checkpoint import digest
        paper=documents.ingest(test_core.pdf(), 'fixture.pdf')
        response={'value':{'translation':'正文','omitted':'','warning':'','caption':'Figure 1. 中文图注','overview':'全文结构','terminology':'术语表','constraints':'不增补'},
                  'usage':{},'provider':'fixture','model':'fixture'}
        with patch('paperpilot.providers.generate',return_value=response):
            job=self.wait_job(service.analyze(paper['id'],'translation'))
        self.assertEqual(job['status'],'completed',job.get('error'))
        paper=store.get('paper',paper['id'])
        figures=paper['translation']['figures']
        self.assertTrue(figures)
        self.assertEqual(figures[0]['caption_zh'],'Figure 1. 中文图注')
        self.assertIn(figures[0]['id'],paper['translation']['sections'][0]['figures'])
        original=documents.figure_bytes(paper['id'],figures[0])
        paper['report']={'figures':figures,'summary':'independent report'}
        store.save('paper',paper)
        paper_storage.release(paper['id'])
        with patch.object(image_cache,'LIMIT_BYTES',0):image_cache.trim()
        paper_storage.delete_report(paper['id'],digest(paper['report']))
        saved=store.get('paper',paper['id'])
        self.assertEqual(documents.figure_bytes(paper['id'],saved['translation']['figures'][0]),original)
        paper_storage.restore_bytes(paper['id'],test_core.pdf(),'restored.pdf')
        saved=store.get('paper',paper['id'])
        with patch.object(image_cache,'LIMIT_BYTES',0):image_cache.trim()
        self.assertEqual(documents.figure_bytes(paper['id'],saved['translation']['figures'][0]),original)

    def test_real_adapter_parses_body_and_caption_json(self):
        import json
        from paperpilot import providers
        paper=documents.ingest(test_core.pdf(),'fixture.pdf')
        config=store.settings();config['provider']='deepseek';store.save_settings(config)
        calls=[]
        def response(url,body,key,timeout):
            calls.append(body)
            self.assertEqual(body.get('response_format'),{'type':'json_object'})
            if 'overview' in body['messages'][0]['content']:
                value={'overview':'全文结构','terminology':'术语表','constraints':'不增补'}
            elif 'caption 字段' in body['messages'][0]['content']:
                value={'caption':'Figure 1. 中文图注','overview':'全文结构','terminology':'术语表','constraints':'不增补'}
            else:
                value={'translation':'完整译文','omitted':'图内文字','warning':''}
            return {'choices':[{'message':{'content':json.dumps(value)},'finish_reason':'stop'}],'usage':{}}
        with patch.object(providers,'api_key',return_value='synthetic-test-key'), patch.object(providers,'post_json',side_effect=response):
            job=self.wait_job(service.analyze(paper['id'],'translation'))
        self.assertEqual(job['status'],'completed',job.get('error'))
        result=store.get('paper',paper['id'])['translation']
        self.assertEqual(result['sections'][0]['translation'],'完整译文')
        self.assertEqual(result['figures'][0]['caption_zh'],'Figure 1. 中文图注')
        self.assertGreaterEqual(len(calls),2)

    def test_both_adapters_complete_and_preserve_previous_translation_on_bad_json(self):
        import json
        import subprocess
        from pathlib import Path
        from contextlib import ExitStack
        from paperpilot import providers
        for provider in ('codex', 'deepseek'):
            with self.subTest(provider=provider):
                paper=documents.ingest(test_core.pdf(),'fixture.pdf')
                config=store.settings();config['provider']=provider;store.save_settings(config)
                broken=False
                stages=[]
                def payload(schema):
                    stages.append(set(schema['properties']))
                    if broken:return '{invalid JSON'
                    if 'overview' in schema['properties']:
                        return json.dumps({'overview':'全文结构','terminology':'术语表','constraints':'不增补'})
                    value=({'caption':'Figure 1. 图注译文'} if 'caption' in schema['properties'] else
                           {'translation':'忠实译文 $x_i$','omitted':'图内文字','warning':''})
                    return json.dumps(value,ensure_ascii=False)
                def cli(cmd,**kwargs):
                    schema=json.loads(Path(cmd[cmd.index('--output-schema')+1]).read_text())
                    self.assertIn('model_reasoning_effort="medium"',cmd)
                    Path(cmd[cmd.index('--output-last-message')+1]).write_text(payload(schema))
                    return subprocess.CompletedProcess(cmd,0,'','')
                def http(url,body,key,timeout):
                    self.assertEqual(body['response_format'],{'type':'json_object'})
                    self.assertEqual(body['thinking'],{'type':'enabled'})
                    contract=body['messages'][0]['content'].split('输出 JSON 必须符合以下结构约束：\n')[1]
                    return {'choices':[{'message':{'content':payload(json.loads(contract))},'finish_reason':'stop'}],'usage':{}}
                with ExitStack() as stack:
                    stack.enter_context(patch('paperpilot.providers.api_key',return_value='synthetic-key'))
                    stack.enter_context(patch('paperpilot.providers.post_json',side_effect=http))
                    stack.enter_context(patch('paperpilot.providers.shutil.which',return_value='/synthetic/codex'))
                    stack.enter_context(patch('paperpilot.codex_runtime.command',return_value=['/synthetic/codex']))
                    stack.enter_context(patch('paperpilot.codex_account.auth_options',return_value=[]))
                    stack.enter_context(patch('paperpilot.codex_account.environment',return_value={}))
                    stack.enter_context(patch('paperpilot.cancellation.run_process',side_effect=cli))
                    job=self.wait_job(service.analyze(paper['id'],'translation'))
                    self.assertEqual(job['status'],'completed',job.get('error'))
                    previous=store.get('paper',paper['id'])['translation']
                    self.assertEqual(previous['sections'][0]['translation'],'忠实译文 $x_i$')
                    self.assertEqual(previous['figures'][0]['caption_zh'],'Figure 1. 图注译文')
                    if provider == 'codex':
                        self.assertIn({'caption'},stages)
                    else:
                        self.assertNotIn({'caption'},stages)  # Reuse captions across providers.
                    broken=True
                    job=self.wait_job(service.analyze(paper['id'],'translation'))
                    self.assertEqual(job['status'],'failed')
                    self.assertEqual(store.get('paper',paper['id'])['translation'],previous)

    def test_cross_page_sentence_and_shared_abstract_excluded(self):
        import json
        paper=documents.ingest(test_core.pdf(),'fixture.pdf')
        pages=[{'page':1,'text':'Title\nAbstract\nAn abstract.\n1 Introduction\nThe method applies the'},
               {'page':2,'text':'same operation to all inputs.\nReferences\nNot body.'}]
        (documents.directory(paper['id'])/'pages.json').write_text(json.dumps(pages))
        chunks=translation.source(paper)
        self.assertEqual(len(chunks),1)
        self.assertIn('applies the\nsame operation',chunks[0]['text'])
        self.assertNotIn('An abstract',chunks[0]['text'])
        self.assertNotIn('Not body',chunks[0]['text'])
        self.assertEqual(chunks[0]['pages'],[1,2])

    def test_shared_abstract_and_identity_reused_without_model(self):
        from paperpilot import paper_abstracts, report_cache
        paper=documents.ingest(test_core.pdf(),'fixture.pdf')
        paper['abstract']='This is a sufficiently long synthetic abstract used only to test reuse.'
        store.save('paper',paper)
        abstract=paper_abstracts.prepare(paper)
        abstract.update(translation='已保存的摘要翻译',fetched_at=report_cache.now())
        paper_abstracts.save_translation(paper,abstract)
        paper=store.get('paper',paper['id'])
        paper['report']={'paper_info':{'original_title':'Synthetic','authors':[], 'fetched_at':report_cache.now()}}
        store.save('paper',paper)
        with patch('paperpilot.providers.generate',side_effect=AssertionError('Unexpected model call')):
            saved=translation.prepare_shared(paper,store.settings(),lambda text:None)
        self.assertEqual(saved['abstract_record']['translation'],'已保存的摘要翻译')
        self.assertEqual(report_cache.recent(saved,'paper_info')['original_title'],'Synthetic')

    def test_full_read_precedes_translation_and_guides_captions(self):
        from paperpilot import providers, reasoning
        paper=documents.ingest(test_core.pdf(),'fixture.pdf')
        stages=[]
        def model(config,system,messages,**kwargs):
            schema=kwargs['schema'];prompt=messages[0]['content']
            if 'overview' in schema['properties']:
                stages.append('read')
                self.assertIn('Experiments:',prompt)  # last page, not just the opening
                value={'overview':'full overview','terminology':'UNIFIED_TERM','constraints':'no invention'}
            elif 'caption' in schema['properties']:
                stages.append('caption');self.assertIn('UNIFIED_TERM',prompt)
                value={'caption':'Figure 1. 图注'}
            else:
                self.assertEqual(stages[0],'read');stages.append('body')
                self.assertIn('UNIFIED_TERM',prompt)
                self.assertIn('前文上下文（不重复翻译）',prompt)
                value={'translation':'译文','omitted':'','warning':''}
            return {'value':value,'usage':{},'provider':'fixture','model':'fixture'}
        with patch.object(providers,'generate',side_effect=model):
            result,checkpoint=translation.build(paper,reasoning.for_task(store.settings(),'translation'),lambda _:None)
        checkpoint.finish(True)
        self.assertEqual(stages,['read','body','caption'])
        self.assertEqual(result['translation_guide']['terminology'],'UNIFIED_TERM')

    def test_translation_policy_independent_override(self):
        from paperpilot import reasoning
        config=store.settings()
        recommended=reasoning.for_task(config,'translation')
        self.assertEqual(recommended['codex_reasoning_effort'],'medium')
        self.assertEqual(recommended['deepseek']['thinking'],'low')
        config['reasoning_policy']={'custom_enabled':True,'overrides':{'translation':'high'}}
        self.assertEqual(reasoning.for_task(config,'translation')['codex_reasoning_effort'],'high')
        self.assertEqual(reasoning.for_task(config,'overview')['codex_reasoning_effort'],'medium')
