import io,json,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from paperpilot import store,presentation_samples as samples,presentation_style,presentations,documents,paper_types
import test_core


def fake_pptx(path):
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')


def exemplar(label='Example'):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        z.writestr('ppt/presentation.xml','<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:sldSz cx="12192000" cy="6858000"/></p:presentation>')
        for i in range(1,4):
            z.writestr(f'ppt/slides/slide{i}.xml',f'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:rPr sz="2400"><a:latin typeface="Arial"/></a:rPr><a:t>{label} intuition, question, evidence and explanation {i}.</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>')
    return out.getvalue()


def style_response(config,system,messages,**kwargs):
    items=json.loads(messages[0]['content'])
    return {'value':{'rules':['Explain context.','Introduce concepts.','Compare mechanisms.','Use examples.','Discuss limits.'],
                     'snippets':[{'source_id':items[0]['id'],'text':items[0]['excerpt'][:100]}]},'provider':config['provider'],'model':'fixture','usage':{}}


def slide(index=1,layout='explain'):
    return {'index':index,'layout':layout,'title':'讲解目标','blocks':[{'heading':'核心想法','text':'理解动作生成的研究问题。','emphasis':'动作生成'}],
            'table':{'headers':[],'rows':[]},'steps':[],'figure_id':'','caption':'','equation':'','equation_meaning':'',
            'takeaway':'理解方法的作用和适用边界。','notes':'从学生熟悉的概念引入，接着解释这个例子，并指出原文证据的边界。',
            'pages':[1],'evidence_id':'p1-e1','evidence_quote':'Research motivation: action generation for robot manipulation.'}


class Presentations(unittest.TestCase):
    setUp=test_core.Core.setUp
    tearDown=test_core.Core.tearDown

    def test_survey_deck_does_not_inherit_report_sections(self):
        paper={'paper_type':'survey'}
        self.assertIn(paper_types.SURVEY_REPORT_GUIDE,paper_types.instruction(paper))
        guide=paper_types.instruction(paper,presentation=True)
        self.assertNotIn(paper_types.SURVEY_REPORT_GUIDE,guide)
        self.assertIn('建立领域地图',guide)
        self.assertIn('不同数据集',guide)

    def test_clean_master_declarations_preserves_real_parts_and_other_missing_assets(self):
        path=store.DATA/'deck.pptx'
        with zipfile.ZipFile(path,'w') as z:
            z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="master"/><Override PartName="/ppt/slideMasters/slideMaster2.xml" ContentType="master"/><Override PartName="/ppt/slides/slide2.xml" ContentType="slide"/></Types>')
            z.writestr('ppt/slideMasters/slideMaster1.xml',b'unchanged')
        presentations.clean_master_declarations(path)
        with zipfile.ZipFile(path) as z:
            types=z.read('[Content_Types].xml').decode()
            self.assertIn('<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"',types)
            self.assertIn('slideMaster1.xml',types)
            self.assertNotIn('slideMaster2.xml',types)
            self.assertIn('/ppt/slides/slide2.xml',types)
            self.assertEqual(z.read('ppt/slideMasters/slideMaster1.xml'),b'unchanged')
        before=path.read_bytes();presentations.clean_master_declarations(path)
        self.assertEqual(path.read_bytes(),before)

    def test_builtin_style_needs_no_examples_or_model_and_disabled_samples_fall_back(self):
        with patch('paperpilot.providers.generate') as model:
            default,theme,key=samples.context(store.settings())
            self.assertIn(presentation_style.RULES,default)
            self.assertEqual(theme,samples.DEFAULT_THEME)
            item=samples.upload(exemplar('Private example'),'sample.pptx')[0]
            samples.change(item['id'],'enable',False)
            for provider in ('codex','deepseek'):
                for mode in ('cached','direct'):
                    style,new_theme,_=samples.context(dict(store.settings(),provider=provider,ppt_style_mode=mode))
                    self.assertEqual((style,new_theme),(default,theme))
                    self.assertNotIn('Private example',style)
            model.assert_not_called()

    def test_user_style_takes_priority_in_both_modes_without_changing_builtin_rules(self):
        samples.upload(exemplar('My teaching example'),'sample.pptx')
        with patch('paperpilot.providers.generate',side_effect=style_response) as model:
            for mode in ('cached','direct'):
                style,theme,key=samples.context(dict(store.settings(),ppt_style_mode=mode))
                self.assertIn(presentation_style.RULES,style)
                self.assertIn('用户范例优先',style)
                self.assertIn('原文证据要求',style)
                self.assertEqual(theme['font'],'Arial')
                if mode=='cached':self.assertIn('Explain context.',style)
                else:self.assertIn('My teaching example',style)
            self.assertEqual(model.call_count,1)

    def test_reference_upload_pair_isolation_cache_and_direct_mode(self):
        a=store.DATA/'a';b=store.DATA/'b'
        with store.scope({'directory':a}):
            store.init();item=samples.upload(exemplar(),'../sample.pptx')[0]
            self.assertEqual(item['name'],'sample.pptx');self.assertEqual(item['slides'],3)
            samples.attach_source(item['id'],test_core.pdf(),'original.pdf')
            with patch('paperpilot.providers.generate',side_effect=style_response) as model:
                first=samples.ensure(dict(store.settings(),provider='codex'))
                second=samples.ensure(dict(store.settings(),provider='deepseek'))
                self.assertEqual(first,second);self.assertEqual(model.call_count,1)
                samples.set_mode('direct');self.assertIsNone(samples.start());self.assertIn('Example',samples.context(store.settings())[0]);self.assertEqual(model.call_count,1)
            samples.change(item['id'],'delete');self.assertEqual(samples.public(),[]);self.assertEqual(list(samples.directory().iterdir()),[])
            self.assertEqual(store.all_objects('ppt_style'),[])
        with store.scope({'directory':b}):store.init();self.assertEqual(samples.public(),[]);self.assertEqual(samples.mode(),'cached')

    def test_rejects_unknown_assets_and_unsubstantiated_quotes(self):
        item=slide();plan={'index':1,'layout':'explain','figure_ids':[]};pages={1:item['evidence_quote']}
        presentations.validate_slide(item,plan,pages,{})
        item['evidence_quote']='Invented experimental result'
        with self.assertRaisesRegex(ValueError,'证据摘录'):presentations.validate_slide(item,plan,pages,{})
        item=slide();item['figure_id']='external-file'
        with self.assertRaisesRegex(ValueError,'未提供'):presentations.validate_slide(item,plan,pages,{})
        with self.assertRaises(ValueError):samples.upload(b'bad','bad.pptx')

    def test_composes_new_deck_in_bounded_batches_using_current_paper(self):
        paper=documents.ingest(test_core.pdf(),'fixture.pdf');paper['report']=dict(test_core.report(paper),mode='detailed')
        plan=[{'index':i,'title':'讲解','purpose':'Explain evidence','layout':'cover' if i==1 else 'explain','pages':[1],'figure_ids':[]} for i in range(1,7)]
        def generate(config,system,messages,images=(),**kwargs):
            self.assertIn('Research motivation',messages[0]['content'])
            self.assertIn(presentation_style.RULES,messages[0]['content'])
            if '规划讲解' in messages[0]['content']:raise AssertionError('Unexpected')
            if '为原论文重新设计' in messages[0]['content']:value={'slides':plan}
            else:
                batch=json.loads(messages[0]['content'].split('只写本批：')[1].split('\n图表目录：')[0]);value={'slides':[slide(p['index'],p['layout']) for p in batch]}
            return {'value':value,'model':'fixture','provider':'codex','usage':{}}
        for provider in ('codex','deepseek'):
            for mode in (None,'overview','detailed'):
                paper['report']=dict(test_core.report(paper),mode=mode) if mode else None
                with self.subTest(provider=provider,mode=mode), patch('paperpilot.providers.generate',side_effect=generate) as model:
                    deck=presentations.generate(paper,dict(store.settings(),provider=provider),lambda _:None)
                    self.assertEqual(len(deck['slides']),6);self.assertEqual(model.call_count,3)
                    self.assertEqual(deck['provider'],provider);self.assertNotIn('report',deck)
                    planned=model.call_args_list[0].args[2][0]['content']
                    self.assertIn('直接依据原文独立备课',planned)
                    self.assertEqual('"report": null' in planned, mode is None)

    def test_export_checks_normalized_report_and_preserves_old_files_on_change(self):
        paper=documents.ingest(test_core.pdf(),'fixture.pdf');paper['report']=dict(test_core.report(paper),mode='detailed');paper['paper_type']='research';store.save('paper',paper)
        deck={'slides':[slide()],'theme':samples.DEFAULT_THEME,'style_key':samples.snapshot()[0],
              'coverage':'fixture','calls':[],'generated_at':'fixture','provider':'codex'}
        def render(args,**kwargs):
            from types import SimpleNamespace
            data=json.loads(Path(args[-1]).read_text());fake_pptx(data['output'])
            return SimpleNamespace(returncode=0,stderr='')
        with patch.object(presentations,'generate',return_value=deck),patch.object(presentations.shutil,'which',return_value='node'),patch.object(presentations.subprocess,'run',side_effect=render):
            result=presentations.export(paper,store.settings(),lambda _:None)
            self.assertEqual(store.get('paper',paper['id'])['exports'][0],result)
            self.assertTrue((documents.directory(paper['id'])/'exports'/result['filename']).exists())
        def changed(args,**kwargs):
            result=render(args,**kwargs);current=store.get('paper',paper['id']);current['report']['summary']='new report';store.save('paper',current);return result
        paper=store.get('paper',paper['id'])
        with patch.object(presentations,'generate',return_value=deck),patch.object(presentations.shutil,'which',return_value='node'),patch.object(presentations.subprocess,'run',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'已更新'):presentations.export(paper,store.settings(),lambda _:None)
        self.assertEqual(len(list((documents.directory(paper['id'])/'exports').glob('*.pptx'))),1)

    def test_independent_ppt_export_preserves_reading_state_and_pdf_still_requires_report(self):
        from paperpilot import exports
        paper=documents.ingest(test_core.pdf(),'fixture.pdf')
        self.assertFalse(paper.get('report'))
        paper['paper_type']='research';store.save('paper',paper)
        before=store.get('paper',paper['id'])
        deck={'slides':[slide()],'theme':samples.DEFAULT_THEME,'style_key':samples.snapshot()[0],
              'coverage':'fixture','calls':[],'generated_at':'fixture','provider':'codex'}
        def render(args,**kwargs):
            from types import SimpleNamespace
            data=json.loads(Path(args[-1]).read_text());fake_pptx(data['output'])
            return SimpleNamespace(returncode=0,stderr='')
        with patch.object(presentations,'generate',return_value=deck),patch.object(presentations.shutil,'which',return_value='node'),patch.object(presentations.subprocess,'run',side_effect=render):
            result=exports.export(paper['id'],'pptx',lambda _:None)
        after=store.get('paper',paper['id'])
        self.assertIsNone(result['source_report_at'])
        self.assertEqual(after.get('report'),before.get('report'))
        self.assertEqual(after.get('read_status'),before.get('read_status'))
        self.assertTrue((documents.directory(paper['id'])/'exports'/result['filename']).exists())
        with self.assertRaisesRegex(ValueError,'请先生成'):
            exports.export(paper['id'],'pdf',lambda _:None)

    def test_numbered_evidence_preserves_pdf_typography_without_model_copying(self):
        text='Efficient ﬂow matching uses closed-\nloop control and achieves 42.1% success.'
        evidence=presentations.evidence_catalog({1:text})
        item=slide();item['evidence_quote']='the model need not copy this'
        result=presentations.validate_slide(item,{'index':1,'layout':'explain','figure_ids':[]},{1:text},{},evidence)
        self.assertEqual(result['evidence_quote'],text)
        item['evidence_id']='made-up'
        with self.assertRaisesRegex(ValueError,'证据编号'):
            presentations.validate_slide(item,{'index':1,'layout':'explain','figure_ids':[]},{1:text},{},evidence)

    def test_failed_batch_resumes_only_unfinished_slides_and_scopes_cache(self):
        paper=documents.ingest(test_core.pdf(),'fixture.pdf')
        plan=[{'index':i,'title':'讲解','purpose':'Explain evidence','layout':'cover' if i==1 else 'explain','pages':[1],'figure_ids':[]} for i in range(1,7)]
        def response(config,system,messages,images=(),**kwargs):
            prompt=messages[0]['content']
            if '为原论文重新设计' in prompt:value={'slides':plan}
            else:
                batch=json.loads(prompt.split('只写本批：')[1].split('\n图表目录：')[0])
                value={'slides':[slide(p['index'],p['layout']) for p in batch]}
                if failing[0]:
                    for s in value['slides']:
                        if s['index']==3:s['evidence_id']='unknown'
            return {'value':value,'model':'fixture','provider':'codex','usage':{}}
        failing=[True]
        with patch('paperpilot.providers.generate',side_effect=response) as model:
            with self.assertRaisesRegex(ValueError,'第 3 页.*证据编号'):
                presentations.generate(paper,store.settings(),lambda _:None)
            self.assertEqual(model.call_count,3)
            self.assertEqual(model.call_args.args[2][-2]['role'],'assistant')
        checkpoint=json.loads((documents.directory(paper['id'])/'presentation-draft.json').read_text())
        self.assertEqual(set(checkpoint['slides']),{'1','2'})
        failing[0]=False
        with patch('paperpilot.providers.generate',side_effect=response) as model:
            deck=presentations.generate(paper,store.settings(),lambda _:None)
            self.assertEqual(model.call_count,2)
            self.assertNotIn('为原论文重新设计',model.call_args_list[0].args[2][0]['content'])
            self.assertEqual(len(deck['slides']),6)
        paper['reading_outline']=['背景','结果']
        with patch('paperpilot.providers.generate',side_effect=response) as model:
            presentations.generate(paper,store.settings(),lambda _:None)
            self.assertEqual(model.call_count,3)
