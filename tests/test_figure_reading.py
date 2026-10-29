import copy
import io
import json
from unittest.mock import patch
from reportlab.pdfgen import canvas
import test_core
from test_core import pdf, report
from paperpilot import documents, providers, reading, service, store
import unittest


def response(value):
    return {'value': value, 'usage': {'completion_tokens': 100}, 'provider': 'fixture', 'model': 'test'}


def generator(paper):
    def generate(config, system, messages, images=(), structured=False, schema=None):
        props = schema['properties']
        if 'type' in props:
            return response({'type':'research','reason':'原文提出并验证方法。'})
        if 'original_title' in props:
            return response({'original_title':'Research motivation: action generation for robot manipulation.', 'authors':[], 'project_url':'','code_url':''})
        if 'paragraphs' in props:
            return response({'paragraphs': ['这项设计值得借鉴，但证据仅限当前任务。', '建议先核对关键假设，再做一个小规模验证。']})
        if 'translation' in props:
            return response({'translation': '这是忠实翻译的原始摘要。'})
        if 'decisions' in props:
            catalog=json.loads(messages[0]['content'].split('全部候选：')[1])
            return response({'decisions':[{'id':f['id'],'include':f['region']!='appendix','reason':'关键证据或重复细节','caption':'简短中文图注','focus':'method'} for f in catalog]})
        if 'blocks' in props:
            ids=json.loads(messages[0]['content'].split('必须使用的图表 ID：')[1])
            return response({'blocks':[{'paragraphs':['问题引出方法，再通过证据检验。'], 'highlights':[], 'figures':ids, 'pages':[1], 'equations':[]}]})
        if 'items' not in props:
            return response(report(paper))
        catalog = json.loads(messages[0]['content'].split('本批目录：')[1].split('\n对应原文')[0])
        return response({'items': [{'id': f['id'], 'title': '图表的问题', 'caption': '中文图注' + '说明' * 155,
             'focus': 'method', 'include': f['region'] != 'appendix', 'reason': '正文图表保留，附录内容重复。',
             'paragraphs': ['看坐标与方法模块。结论需要实验条件。'], 'highlights': ['看坐标与方法模块']} for f in catalog]})
    return generate


class FigureReading(unittest.TestCase):
    setUp = test_core.Core.setUp
    tearDown = test_core.Core.tearDown
    wait_job = test_core.Core.wait_job

    def test_caption_continuation_and_unlabeled_abstract(self):
        lines = [{'text':'Table 2 | Success Rate on AlfWorld and', 'x0':350, 'top':87, 'bottom':99.8},
                 {'text':'ScienceWorld (%).', 'x0':350, 'top':100.8, 'bottom':111.7},
                 {'text':'Body text should not be included.', 'x0':350, 'top':130, 'bottom':141}]
        self.assertEqual(documents.full_caption(lines,lines[0]),
                         'Table 2 | Success Rate on AlfWorld and ScienceWorld (%).')
        for bold in (True,False):
            stream=io.BytesIO();c=canvas.Canvas(stream,pagesize=(600,800))
            c.setFont('Helvetica-Bold',20);c.drawString(50,740,'Paper title')
            c.setFont('Helvetica-Bold' if bold else 'Helvetica',11)
            source=['This is an introductory summary of the paper and its research problem.',
                    'It explains why existing memory systems fail as the environment changes.',
                    'The proposed method compiles context according to the current agent state.',
                    'A lightweight executor receives relevant information at each action step.',
                    'Experiments compare the approach with static memory and no-memory agents.',
                    'The paper reports task success, limitations, and computational efficiency.']
            for i,line in enumerate(source):c.drawString(50,630-i*15,line)
            c.setFont('Helvetica',11);c.drawString(50,500,'1 Introduction')
            c.save();p=documents.ingest(stream.getvalue(),'unlabeled-abstract.pdf')
            result=documents.abstract_source(p)
            self.assertEqual(result['original'],' '.join(source) if bold else '')
            self.assertEqual(result['status'],'extracted_unlabeled' if bold else 'missing')

    def test_table_below_caption_and_above_caption_with_pipe_labels(self):
        stream = io.BytesIO(); c = canvas.Canvas(stream, pagesize=(600,800)); c.setFont('Helvetica',9)
        c.drawString(40,760,'A synthetic paper with caption placement and column regressions.')
        # Right caption follows unrelated text that extends across the page midpoint.
        c.drawString(40,700,'Neighboring prose continues through this wider left hand column')
        c.drawString(355,700,'Table 1 | Results.')
        for y in (680,660,600): c.line(355,y,560,y)
        c.drawString(360,630,'Model A   12.5')
        # A centered table whose caption is substantially wider and BELOW its data.
        for y in (500,480,430): c.line(190,y,410,y)
        c.drawString(195,486,'Model       Score')
        c.drawString(195,455,'Model B   27.5')
        c.drawCentredString(300,412,'Table 2: This wider caption describes the result of the second table.')
        c.drawString(40,370,'The text below the caption must never be substituted for the table.')
        c.rect(40,150,180,140); c.drawString(40,130,'Figure 1 | Diagram.')
        c.save(); p=documents.ingest(stream.getvalue(),'caption-positions.pdf')
        active=[f for f in p['figures'] if not f.get('duplicate_of')]
        self.assertEqual({documents.figure_label(f['caption']) for f in active}, {('table','1'),('table','2'),('figure','1')})
        first=next(f for f in active if documents.figure_label(f['caption'])==('table','1'))
        second=next(f for f in active if documents.figure_label(f['caption'])==('table','2'))
        self.assertGreater(first['bbox'][0],.55)
        self.assertLess(first['bbox'][3]*800,210)
        self.assertLess(second['bbox'][1]*800,305)
        self.assertLess(second['bbox'][3]*800,380)
        self.assertGreater(second['bbox'][0]*600,180)
        second.update(auto_crop=False,bbox=[.1,.1,.4,.4],selected=False)
        p['figure_inventory_version']=9;documents.inventory(p)
        self.assertEqual(second['bbox'],[.1,.1,.4,.4]);self.assertFalse(second['selected'])

    def test_judgment_required_even_for_unrelated_papers_and_all_modes(self):
        for mode in ('overview','detailed','deep'):
            def invoke(stage,prompt,schema):
                self.assertIn('没有直接关系',prompt)
                self.assertIn('不要牵强绑定',prompt)
                return response({'paragraphs':['这篇论文提供了有用的研究方法，但证据边界需要辨清。',
                                               '与当前课题没有直接关系，建议先读论证部分以拓展视野。']})
            result=reading.compose_judgment({'mode':mode,'summary':'Unrelated topic'},[],invoke)
            self.assertEqual(result['key'],'relevance');self.assertEqual(len(result['paragraphs']),2)
        with self.assertRaisesRegex(ValueError,'助手判断'):
            reading.compose_judgment({'summary':'test'},[],lambda *args:response({'paragraphs':[]}))

    def test_parallel_tables_use_actual_columns_and_preserve_manual_crops(self):
        stream=io.BytesIO();c=canvas.Canvas(stream,pagesize=(612,792));c.setFont('Helvetica',9)
        c.drawString(100,740,'Sufficient source text for a synthetic table extraction fixture.')
        for number,x0,x1 in [(5,108,232),(6,249,363),(7,384,498)]:
            c.drawString(x0+3,600,f'Table {number}: Results.')
            for y in (585,565,520):c.line(x0,y,x1,y)
            c.drawString(x0+3,548,'Model A     3.28')
        c.save();p=documents.ingest(stream.getvalue(),'parallel.pdf')
        tables=[f for f in p['figures'] if f.get('kind')=='table']
        self.assertEqual(len(tables),3)
        for f in tables:
            self.assertEqual(f['caption'].count('Table'),1)
            self.assertLess((f['bbox'][2]-f['bbox'][0])*612,135)
            self.assertLess((f['bbox'][3]-f['bbox'][1])*792,75)
        tables[0].update(auto_crop=False,bbox=[.1,.1,.2,.2])
        p['figure_inventory_version']=8;documents.inventory(p)
        self.assertEqual(tables[0]['bbox'],[.1,.1,.2,.2])

    def test_math_build_expands_concepts_and_detailed_retains_story(self):
        p=documents.ingest(pdf(),'modes.pdf')
        fallback=generator(p)
        def generate(config,system,messages,images=(),structured=False,schema=None):
            if 'sections' in schema['properties'] and '教材式数学精读目录' in messages[0]['content']:
                value=report(p)
                template=value['sections'][1]
                value['sections']=[dict(copy.deepcopy(template),key=k,title=k) for k in ('motivation','notation','intuition','method','training','implementation','experiments','navigation','conclusion')]
                return response(value)
            return fallback(config,system,messages,images,structured,schema)
        for mode,expected in [('deep',11),('detailed',6)]:
            stages=[]
            with patch('paperpilot.providers.generate',side_effect=generate):
                r,_=reading.build(p,mode,store.settings(),stages.append,'test',service.report_schema,service.validate_report)
            self.assertEqual(len(r['sections']),expected)
            self.assertEqual(r['sections'][0]['key'],'abstract')
            if mode=='deep':
                self.assertTrue(all(s.get('textbook') for s in r['sections'][1:-1]))
                self.assertTrue(any('教材式展开' in s for s in stages))
                self.assertFalse(any('串联' in s for s in stages))
            else:
                self.assertEqual([s['key'] for s in r['sections'][1:]],['motivation','method','experiments','conclusion','relevance'])

    def test_all_images_batched_abstract_and_legacy_selection_preserved(self):
        p = documents.ingest(pdf(), 'test.pdf')
        p['figures'] = [dict(p['figures'][0], id=f'fig-{i+1}', selected=i<6, region='appendix' if i==8 else 'main') for i in range(9)]
        p['abstract'] = 'An original abstract with sufficient length for a source extraction test.'
        store.save('paper',p)
        config=store.settings();config.update(vision=True,output_tokens=7000,output_tokens_auto=False)
        with patch('paperpilot.providers.generate',side_effect=generator(p)) as model:
            r, figs=reading.build(p,'overview',config,lambda _:None,'test',service.report_schema,service.validate_report)
        self.assertEqual(r['image_count'],9)
        self.assertEqual([s['key'] for s in r['sections']], ['abstract','motivation','method','experiments','conclusion','relevance'])
        self.assertTrue(r['sections'][2]['blocks'])
        self.assertEqual(len(r['sections'][2]['figures']),8)
        self.assertEqual(len(r['figure_coverage']),9)
        self.assertEqual(len(figs),8)
        self.assertTrue(all(f['selected'] for f in figs))
        self.assertFalse(store.get('paper',p['id'])['figures'][6]['selected'])
        self.assertEqual(sum(len(c.args[3]) for c in model.call_args_list),9)
        self.assertEqual(r['sections'][0]['key'],'abstract')
        self.assertIn('original abstract',r['abstract']['original'])
        self.assertLessEqual(len(r['figure_captions'][0]['caption']),160)
        self.assertTrue(all(c.args[0]['output_tokens']==7000 for c in model.call_args_list))

    def test_new_pdf_no_six_figure_limit_and_tables(self):
        stream=io.BytesIO();c=canvas.Canvas(stream,pagesize=(600,800))
        for i in range(8):
            c.drawString(40,750,'This is sufficient text content for a software fixture paper.')
            c.rect(40,410,400,230);c.drawString(40,390,f'Figure {i+1}: Diagram caption.')
            c.drawString(40,340,f'Table {i+1}: Experimental results.')
            for y in (320,300,250):c.line(40,y,440,y)
            c.drawString(50,270,'Model A     5.0     7.2');c.showPage()
        c.save();p=documents.ingest(stream.getvalue(),'many.pdf')
        self.assertEqual(len(p['figures']),16)

        self.assertEqual(sum(f['selected'] for f in p['figures']),16)
        self.assertEqual(sum(f.get('kind')=='table' for f in p['figures']),8)
        manual=p['figures'][0];manual.update(auto_crop=False,selected=False,bbox=[.1,.1,.7,.4])
        p.pop('figure_inventory_version');before=copy.deepcopy(manual)
        documents.inventory(p)
        self.assertEqual(p['figures'][0],before)
        self.assertEqual(len(p['figures']),16)

    def test_overview_can_omit_main_figures_and_keep_later_evidence(self):
        figures=[{'id':f'fig-{i}', 'caption':f'Figure {i}: evidence', 'page':i, 'region':'main'} for i in range(1,10)]
        evidence=[{'figures':[f['id']], 'paragraphs':['已核对证据'], 'focus':'method'} for f in figures]
        decisions=[{'id':f['id'], 'include':f['id'] in ('fig-2','fig-9'), 'reason':'核心或重复证据', 'caption':'中文主题', 'focus':'method'} for f in figures]
        invoke=lambda *args: response({'decisions':decisions})
        selected,captions,coverage=reading.curate_overview({'summary':'核心'},evidence,figures,invoke)
        self.assertEqual([c['id'] for c in captions],['fig-2','fig-9'])
        self.assertEqual(len(coverage),9)
        self.assertFalse(coverage[0]['included'])
        self.assertEqual(len(selected),2)
        decisions.pop()
        with self.assertRaisesRegex(ValueError,'未覆盖'):
            reading.curate_overview({'summary':'核心'},evidence,figures,invoke)

    def test_truncation_counts_and_explicit_thinking(self):
        config=store.settings();config['provider']='deepseek';providers.KEYS['deepseek']='test-secret'
        config['deepseek']['thinking']='disabled'
        payload={'choices':[{'message':{'content':'partial','reasoning_content':'private reasoning'},'finish_reason':'length'}],
                 'usage':{'completion_tokens':7000,'completion_tokens_details':{'reasoning_tokens':6900}}}
        with patch('paperpilot.providers.post_json',return_value=payload) as post:
            with self.assertRaises(providers.GenerationLimitError) as caught:
                providers.generate(config,'test',[{'role':'user','content':'test'}])
        self.assertEqual(post.call_args.args[1]['thinking'],{'type':'disabled'})
        self.assertEqual(caught.exception.diagnostic['reasoning_tokens'],6900)
        self.assertNotIn('private reasoning',str(caught.exception.diagnostic))
        config['deepseek']['thinking']='low'
        payload['choices'][0]['finish_reason']='stop'
        with patch('paperpilot.providers.post_json',return_value=payload) as post:
            providers.generate(config,'test',[{'role':'user','content':'test'}])
        self.assertEqual(post.call_args.args[1]['reasoning_effort'],'low')

    def test_incomplete_batch_keeps_previous_report(self):
        p=documents.ingest(pdf(),'test.pdf');p['report']=report(p);store.save('paper',p)
        with patch('paperpilot.providers.generate',side_effect=[response(report(p)),response({'items':[]})]):
            job=self.wait_job(service.analyze(p['id'],'overview'))
        self.assertEqual(job['status'],'failed')
        self.assertEqual(store.get('paper',p['id'])['report'],p['report'])

    def test_bounded_json_repair_and_optional_highlights(self):
        p=documents.ingest(pdf(),'test.pdf')
        base=report(p)
        base['sections'][0]['highlights']=['not verbatim']
        item={'id':'fig-1','title':'图 1','caption':'测试图','focus':'method','include':True,'reason':'正文图表','paragraphs':['可核对的图表解释。']}
        with patch('paperpilot.providers.generate',side_effect=[providers.StructuredOutputError('broken JSON',{'completion_tokens':32},'JSON invalid'),response(base),response({'items':[item]}), response({'decisions':[dict(item,caption='测试图')]}), *[response({'blocks':[{'paragraphs':['证据串联。'],'highlights':[],'figures':ids,'pages':[1],'equations':[]}]}) for ids in ([],['fig-1'],[],[])], response({'paragraphs':['判断依据来自当前证据。','建议先核对假设再尝试复现。']}), response({'original_title':'Research motivation: action generation for robot manipulation.','authors':[],'project_url':'','code_url':''})]) as model:
            r,figs=reading.build(p,'overview',store.settings(),lambda _:None,'test',service.report_schema,service.validate_report)
        self.assertEqual(model.call_count,10)
        self.assertEqual(len(figs),1)
        self.assertEqual(r['sections'][1]['highlights'],[])
        self.assertEqual(r['usage']['completion_tokens'],932)
        with patch('paperpilot.providers.generate',side_effect=[providers.StructuredOutputError('broken',{},'JSON invalid')]*2) as model:
            with self.assertRaises(providers.StructuredOutputError):
                reading.build(p,'overview',store.settings(),lambda _:None,'test',service.report_schema,service.validate_report)
        self.assertEqual(model.call_count,2)

    def test_column_caption_and_figure_reference_are_not_lost_or_duplicated(self):
        stream=io.BytesIO();c=canvas.Canvas(stream,pagesize=(600,800))
        c.drawString(40,750,'A B C')
        c.drawString(40,720,'Introduction with sufficiently long material for extraction.')
        c.rect(340,460,180,180)
        c.drawString(40,440,'Unrelated left-column text')
        c.drawString(330,440,'Figure 1: Column diagram.')
        c.drawString(330,427,'Caption continuation.')
        c.drawString(40,400,'Table 1: Results.')
        for y in (380,360,310):c.line(40,y,260,y)
        c.drawString(40,325,'A       5.0')
        c.drawString(40,200,'Figure 1. This prose refers to the diagram.')
        c.save();p=documents.ingest(stream.getvalue(),'columns.pdf')
        figures=[f for f in p['figures'] if not f.get('duplicate_of')]
        self.assertEqual(len(figures),2)
        self.assertTrue(all(f['region']=='main' for f in figures))
        self.assertTrue(any('Column diagram' in f['caption'] for f in figures))

    def test_story_rejects_missing_evidence_and_invalid_block_pages(self):
        p=documents.ingest(pdf(),'test.pdf')
        evidence=[{'focus':'method','figures':['fig-1'],'paragraphs':['test']}]
        invoke=lambda *args:response({'blocks':[{'paragraphs':['test'],'highlights':[],'figures':[],'pages':[1],'equations':[]}]})
        with self.assertRaisesRegex(ValueError,'遗漏'):
            reading.compose_story(report(p),evidence,invoke,store.settings())
        r=report(p)
        r['sections'][0]['blocks']=[{'paragraphs':['test'],'highlights':[],'figures':[],'pages':[999],'equations':[]}]
        with self.assertRaisesRegex(ValueError,'页码'):
            service.validate_report(r,p)

    def test_empty_compression_keeps_original_chapter_and_empty_core_is_rejected(self):
        p=documents.ingest(pdf(),'test.pdf')
        original='有依据的结论与适用边界。'*80
        def invoke(stage,*args):
            text=[] if stage.startswith('压缩') else [original]
            return response({'blocks':[{'paragraphs':text,'figures':[],'highlights':[],
                                         'pages':[],'equations':[],'data_tables':[]}]})
        chapters=reading.compose_story(report(p),[],invoke,dict(store.settings(),output_tokens=8192))
        self.assertTrue(all(s['blocks'][0]['paragraphs']==[original] for s in chapters))
        r=report(p);r['sections']=chapters
        service.validate_report(r,p)
        chapters[-1]['blocks'][0]['paragraphs']=[]
        with self.assertRaisesRegex(ValueError,'正文为空'):service.validate_report(r,p)
        with self.assertRaisesRegex(ValueError,'正文为空'):reading.reconcile_figures([{'paragraphs':[],'figures':[]}],[],[])
