"""Compose a new teaching deck from paper evidence, then export editable slides."""
import copy
import hashlib
import json
import re
import shutil
import subprocess
import uuid
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from . import documents, store, providers, reasoning, presentation_samples, presentation_style, publication, paper_types
from .schemas import obj

TEXT={'type':'string'}
LAYOUTS=['cover','explain','columns','table','process','figure','equation','discussion']

def array(value,maximum=10):return {'type':'array','maxItems':maximum,'items':value}
def bounded(maximum):return {'type':'string','maxLength':maximum}


def slide_schema(evidence_ids=None):
    return obj({'index':{'type':'integer'},'title':bounded(180),'layout':{'type':'string','enum':LAYOUTS},
      'blocks':array(obj({'heading':bounded(38),'text':bounded(180),'emphasis':bounded(35)}),4),
      'table':obj({'headers':array(bounded(36),5),'rows':array(array(bounded(65),5),7)}),
      'steps':array(bounded(45),5),'figure_id':bounded(40),'caption':bounded(100),
      'equation':bounded(500),'equation_meaning':bounded(140),'takeaway':bounded(110),
      'notes':bounded(1800),'pages':array({'type':'integer'},8),
      'evidence_id':{'type':'string','enum':evidence_ids or ['']}})


def validate_slide(value,plan,pages,figures,evidence=None):
    if not isinstance(value,dict) or value.get('index')!=plan['index'] or value.get('layout')!=plan['layout']:
        raise ValueError('幻灯片编号或版式与计划不一致')
    if evidence is not None:
        ref=evidence.get(value.get('evidence_id'))
        if not ref:
            raise ValueError('请选择当前提供的原文证据编号 evidence_id，不要自行编写引文')
        if not isinstance(value.get('pages'),list) or ref['page'] not in value['pages']:
            raise ValueError('证据编号对应的 PDF 页码未包含在 pages 中')
        value={**value,'evidence_quote':ref['text']}
    for key,limit in [('title',180 if value['layout']=='cover' else 90),('caption',100),('equation',500),('equation_meaning',140),('takeaway',110),('notes',1800),('evidence_quote',320)]:
        if not isinstance(value.get(key),str) or len(value[key])>limit:raise ValueError('幻灯片文本过长或结构无效：'+key)
    if not value['title'].strip() or not value['notes'].strip():raise ValueError('每页应有标题和讲稿备注')
    refs=value.get('pages',[])
    if not isinstance(refs,list) or not refs or any(type(n)!=int or n not in pages for n in refs):raise ValueError('幻灯片没有有效原文依据')
    compact=lambda s:re.sub(r'\s+','',s)
    quote=compact(value['evidence_quote'])
    if len(quote)<8 or not any(quote in compact(pages[n]) for n in refs):raise ValueError('幻灯片证据摘录无法对应所给原文')
    blocks=value.get('blocks')
    if not isinstance(blocks,list) or len(blocks)>4:raise ValueError('每页最多4个讲解要点')
    for block in blocks:
        if not isinstance(block,dict) or any(not isinstance(block.get(k),str) or len(block[k])>limit for k,limit in [('heading',38),('text',180),('emphasis',35)]):raise ValueError('讲解要点超出排版容量')
        if block['emphasis'] and block['emphasis'] not in block['text']:raise ValueError('强调词必须来自本页正文')
    if sum(len(b['text'])+len(b['heading']) for b in blocks)>460:raise ValueError('本页文字过多，请将详细解释放入讲稿')
    table=value.get('table',{});heads=table.get('headers',[]);rows=table.get('rows',[])
    if not isinstance(heads,list) or not isinstance(rows,list) or len(heads)>5 or len(rows)>7:raise ValueError('表格过大，请拆为多页')
    if any(not isinstance(row,list) or len(row)!=len(heads) for row in rows) or any(not isinstance(cell,str) or len(cell)>65 for row in [heads]+rows for cell in row):raise ValueError('表格结构无效')
    steps=value.get('steps',[])
    if not isinstance(steps,list) or len(steps)>5 or any(not isinstance(s,str) or len(s)>45 for s in steps):raise ValueError('流程图最多5个步骤')
    figure=value.get('figure_id','')
    if figure and (figure not in figures or figure not in plan['figure_ids']):raise ValueError('幻灯片引用了未提供的图表')
    if value['layout']=='figure' and not figure:raise ValueError('图文页缺少图片')
    if value['layout']=='table' and (not heads or not rows):raise ValueError('表格页缺少表格内容')
    if value['layout']=='process' and len(steps)<2:raise ValueError('流程页缺少流程')
    if value['layout']=='equation' and not value['equation']:raise ValueError('公式页缺少公式')
    return value


def evidence_catalog(pages):
    """Immutable, verbatim source spans. Models select IDs instead of retyping PDF text."""
    result={}
    for page,text in pages.items():
        offset=0;index=1
        while offset<len(text):
            end=min(offset+300,len(text))
            if end<len(text):
                cut=max(text.rfind(c,offset+150,end) for c in ('\n','. ','; ','。',' '))
                if cut>=0:end=cut+1
            quote=text[offset:end].strip();offset=end
            if len(re.sub(r'\s+','',quote))>=8:
                result[f'p{page}-e{index}']={'page':page,'text':quote};index+=1
    return result


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def save_draft(path,value):
    # Drafts live beside the user's paper and are removed with that paper.
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False))
    temporary.replace(path)


def generate(paper,config,progress):
    from .service import system_prompt, now
    config=reasoning.for_task(copy.deepcopy(config),'detailed')
    if config['provider']=='deepseek':config['deepseek']['model']=config['deepseek'].get('detail_model') or config['deepseek']['model']
    progress('准备讲解风格与原论文，规划讲解故事')
    style,theme,style_key=presentation_samples.context(config)
    source,coverage=documents.context(paper,config['context_chars'])
    page_items=json.loads((documents.directory(paper['id'])/'pages.json').read_text())
    pages={p['page']:p['text'] for p in page_items}
    figures={f['id']:f for f in paper.get('figures',[]) if not f.get('duplicate_of')}
    system=system_prompt()+'\n本次编写中文课堂论文讲解PPT。你是讲解老师，每页回答一个问题，讲稿放notes。参考例文只学风格和格式，不得复制其论文事实。不得输出代码、HTML、外部图片URL。原文之外的例子要标注为帮助理解的示例；作者结论和讲解者判断要分开。'
    system += '\n' + paper_types.instruction(paper, presentation=True)
    system += ('\nPPT 的 blocks.heading 按本页实际概念、机制或比较维度命名，不套用阅读报告的固定栏目。'
               '不要每页重复“摘要／论文相关／助手判断”；材料覆盖限制放在讲稿或集中一页说明，不能用本批材料缺失推断论文遗漏。')
    if paper_types.effective(paper) == 'survey':
        system += ('\n综述讲解先提出领域问题、建立总地图，再展开主要分支并比较，最后回到地图说明未解问题。'
                   '不做每篇参考文献一页的流水账。参考范例只迁移讲解节奏、图文布局，不套用范例论文的领域分类。')
    draft_path=documents.directory(paper['id'])/'presentation-draft.json'
    cache_key=fingerprint([2,presentation_style.VERSION,source_snapshot(paper),pages,config,system,style,theme,style_key])
    try:
        draft=json.loads(draft_path.read_text())
        if draft.get('key')!=cache_key:draft={}
    except (OSError,ValueError):draft={}
    draft={'key':cache_key,'plan':draft.get('plan'),'slides':draft.get('slides',{}),'calls':draft.get('calls',[])}
    calls=draft['calls']
    def invoke(stage,prompt,schema,check,images=()):
        progress(stage)
        messages=[{'role':'user','content':prompt}]
        for attempt in range(2):
            try:
                result=providers.generate(providers.image_config(config) if images else config,system,messages,images,structured=True,schema=schema)
            except providers.StructuredOutputError as error:
                if attempt:raise
                messages.append({'role':'user','content':'上一轮JSON无效，请按schema重新输出。'});continue
            calls.append({'stage':stage,'model':result['model'],'usage':result['usage']})
            try:return check(result['value'])
            except (ValueError,KeyError,TypeError) as error:
                save_draft(draft_path,draft)
                if attempt:raise ValueError(stage+'未通过核对：'+str(error)+'。已核对页面保留，重试会从未完成部分继续。') from error
                messages.append({'role':'assistant','content':json.dumps(result['value'],ensure_ascii=False)})
                messages.append({'role':'user','content':'仅修正下述问题，保留正确页面；返回本批完整 JSON。不添加原文没有的事实。问题：'+str(error)[:1000]})
    plan_item=obj({'index':{'type':'integer'},'title':bounded(90),'purpose':bounded(180),'layout':{'type':'string','enum':LAYOUTS},
                   'pages':array({'type':'integer'},5),'figure_ids':array({'type':'string','enum':list(figures) or ['']},1)})
    def check_plan(value):
        items=value.get('slides',[])
        if not 6<=len(items)<=24:raise ValueError('讲解计划需要6–24页')
        for i,item in enumerate(items,1):
            if item['index']!=i or item['layout'] not in LAYOUTS or not item['pages'] or any(n not in pages for n in item['pages']):raise ValueError('计划页码或顺序无效')
            if any(f not in figures for f in item['figure_ids']):raise ValueError('计划图表无效')
            if item['layout']=='figure' and not item['figure_ids']:raise ValueError('图文页需要选择原图')
        if items[0]['layout']!='cover':raise ValueError('第一页应为封面')
        return items
    brief={'title':paper['title'],'paper_type':paper_types.effective(paper),'outline':paper_types.outline(paper),'report':paper.get('report'),
           'figures':[{k:f.get(k) for k in ('id','page','caption','kind')} for f in figures.values()]}
    plan=check_plan({'slides':draft['plan']}) if draft['plan'] else invoke('规划讲解顺序与每页目的','为原论文重新设计6–24页讲解PPT，按论文复杂度决定页数。不能把现有报告按段拆页。'
        '没有阅读报告时，直接依据原文独立备课；有报告时仅将其作为辅助，不受报告详略限制。'
        '参考范例的概念铺垫、对比、例子和信息密度。使用多种适当版式，若需要自己画机制流程图则用process。'
        '最后总结贡献、边界与讨论问题。用户叙述线作为关注重点，允许为教学插入概念解释。'
        '每页pages指定原文依据（最多5页），figure_ids最多1个；不要强迫使用全部原图。'
        '\n风格：'+style+'\n阅读材料（报告是二级解读，事实以原文为准）：'+json.dumps(brief,ensure_ascii=False)
        +'\n原文覆盖：'+coverage+'\n原文：'+source,obj({'slides':array(plan_item,24)}),check_plan)
    draft['plan']=plan;save_draft(draft_path,draft)
    if draft['slides']:progress(f'继续上次讲解，已保存 {len(draft["slides"])} / {len(plan)} 页')
    for start in range(0,len(plan),3):
        group=plan[start:start+3];nums=sorted({n for p in group for n in p['pages']})
        # Give each selected page a fair share; all pages remain explicitly labelled.
        allowance=max(1000,config['context_chars']//max(1,len(nums)))
        local={n:pages[n][:allowance] for n in nums}
        evidence=evidence_catalog(local)
        for item in group:
            saved=draft['slides'].get(str(item['index']))
            if saved:
                try:validate_slide(saved,item,local,figures,evidence)
                except (ValueError,TypeError,KeyError):draft['slides'].pop(str(item['index']),None)
        batch=[p for p in group if str(p['index']) not in draft['slides']]
        if not batch:continue
        selected={f:figures[f] for p in batch for f in p['figure_ids']}
        with documents.model_images(paper['id'], selected.values(), config.get('vision')) as images:
            def check_batch(value):
                items=value.get('slides',[])
                if [s.get('index') for s in items]!=[p['index'] for p in batch]:raise ValueError('本批幻灯片缺失或重复')
                checked=[];errors=[]
                for s,p in zip(items,batch):
                    try:
                        valid=validate_slide(s,p,local,figures,evidence)
                        checked.append(valid);draft['slides'][str(p['index'])]=valid
                    except (ValueError,TypeError,KeyError) as error:
                        previous=draft['slides'].get(str(p['index']))
                        if previous:checked.append(previous)
                        else:errors.append(f'第 {p["index"]} 页：{error}')
                save_draft(draft_path,draft)
                if errors:raise ValueError('；'.join(errors))
                return checked
            prompt=('编写本批幻灯片。结构字段全部给出，不适用用空字符串或空数组。每页标题简明，blocks最多4项，'
              'heading标识要点，text解释，emphasis是正文中的一个短语。每页正文不超过约300中文字，图文/流程/表格页更短。'
              'notes写教师的讲稿、例子、转场和限制，约200–450中文字，不仅重复幻灯片文字。'
              'table是可编辑表格（最多5列7行），只使用提供的原文数据并说明比较条件。process用steps描述机制，非实验事实的示意请标明。'
              'equation只填LaTeX并用equation_meaning解释用途。图表caption使用Figure/Table编号和中文说明。'
              '每页 evidence_id 必须从下方原文片段中选择一个最能支撑核心论断的编号，pages 包含该片段对应的 PDF 页码。'
              '不必抄写 evidence_quote，程序会自动附上对应原文；不能用范例或报告代替原文证据。'
              'takeaway是一句带走的认识，无需每页复述摘要。cover保留原论文英文标题。'
              +'\n风格：'+style+'\n全稿计划：'+json.dumps(plan,ensure_ascii=False)
              +'\n只写本批：'+json.dumps(batch,ensure_ascii=False)+'\n图表目录：'+json.dumps(list(selected.values()),ensure_ascii=False)
              +('\n附图顺序与目录一致。' if images else '\n未提供图片，只依据图注与正文，不声称看清图像细节。')
              +'\n原文片段（编号 → PDF页码与原文）：'+json.dumps(evidence,ensure_ascii=False))
            invoke(f'编写讲解与讲稿 {batch[0]["index"]}–{batch[-1]["index"]} / {len(plan)}',prompt,obj({'slides':array(slide_schema(list(evidence)),3)}),check_batch,images)
    slides=[draft['slides'][str(p['index'])] for p in plan]
    return {'slides':slides,'theme':theme,'style_key':style_key,'style_mode':config.get('ppt_style_mode','cached'),
            'paper_type':paper_types.effective(paper),'reading_outline':paper_types.outline(paper),
            'draft_key':cache_key,'coverage':coverage,'calls':calls,'generated_at':now(),'provider':config['provider']}


def source_snapshot(paper):
    # Only generation inputs invalidate a deck; notes and reading status may change independently.
    return {k:copy.deepcopy(paper.get(k)) for k in ('title','source_url','paper_type','paper_type_detection','reading_outlines','reading_outline','figures','report')}


def clean_master_declarations(path):
    """PptxGenJS 4 can declare unused masters; remove only absent master types.

    Keep all relationships and real parts intact. This does not mask missing
    slide assets or broken relationships, which must still fail validation.
    """
    with zipfile.ZipFile(path) as archive:
        names=set(archive.namelist())
        types=ET.fromstring(archive.read('[Content_Types].xml'))
        unused=[node for node in types if re.fullmatch(r'/ppt/slideMasters/slideMaster\d+\.xml',node.get('PartName',''))
                and node.get('PartName','').lstrip('/') not in names]
        if not unused:return
        for node in unused:types.remove(node)
        ET.register_namespace('', 'http://schemas.openxmlformats.org/package/2006/content-types')
        temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as output:
                for entry in archive.infolist():
                    output.writestr(entry,ET.tostring(types,encoding='utf-8',xml_declaration=True)
                                    if entry.filename=='[Content_Types].xml' else archive.read(entry.filename))
            temporary.replace(path)
        finally:temporary.unlink(missing_ok=True)


def export(paper,config,progress):
    from .service import SAVE_LOCK
    paper=publication.apply(copy.deepcopy(paper))
    directory=documents.directory(paper['id'])
    if not (directory/'source.pdf').is_file() or not (directory/'pages.json').is_file():
        raise ValueError('请先下载或上传原文 PDF，再生成讲解 PPT')
    source_hash=hashlib.sha256((directory/'pages.json').read_bytes()).hexdigest()
    node=shutil.which('node')
    if not node:raise ValueError('PPT 生成需要 Node.js，请安装后重试')
    paper=paper_types.prepare(paper,config,progress);snapshot=source_snapshot(paper)
    token=uuid.uuid4().hex[:12];directory=documents.directory(paper['id']);build=directory/('build-'+token);build.mkdir()
    deck=generate(paper,config,progress)
    figures={f['id']:f for f in paper.get('figures',[])}
    for slide in deck['slides']:
        if slide['figure_id']:
            target=build/(slide['figure_id']+'.png');target.write_bytes(documents.figure_bytes(paper['id'],figures[slide['figure_id']]))
            slide['image_path']=str(target)
    output=directory/'exports'/f'report-{token}.pptx';output.parent.mkdir(exist_ok=True)
    payload=build/'slides.json';payload.write_text(json.dumps(dict(deck,output=str(output),build=str(build),paper_title=paper['title'],source_url=paper.get('source_url','')),ensure_ascii=False))
    progress('排版可编辑幻灯片、公式与讲稿备注')
    try:result=subprocess.run([node,str(store.ROOT/'tools/presentation-export.mjs'),str(payload)],cwd=store.ROOT,capture_output=True,text=True,timeout=180)
    except subprocess.TimeoutExpired:raise ValueError('PPT 排版超时，已有文件保留') from None
    if result.returncode or not output.exists():
        (build/'error.log').write_text(result.stderr[-8000:]);raise ValueError('PPT 排版失败，已有文件保留；请检查 Node.js、浏览器和项目依赖')
    clean_master_declarations(output)
    with SAVE_LOCK,store.LOCK:
        current=publication.apply(store.get('paper',paper['id']))
        changed=[k for k,v in source_snapshot(current).items() if v!=snapshot.get(k)]
        if presentation_samples.snapshot()[0]!=deck['style_key']:changed.append('参考范例')
        if hashlib.sha256((directory/'pages.json').read_bytes()).hexdigest()!=source_hash:changed.append('原文')
        if changed:
            (build/'source-change.json').write_text(json.dumps({'changed_fields':changed},ensure_ascii=False))
            labels={'title':'题名','source_url':'原文地址','reading_outline':'叙述线','reading_outlines':'叙述线',
                    'paper_type':'论文类型','paper_type_detection':'论文类型','figures':'图表','report':'阅读报告'}
            output.unlink(missing_ok=True)
            raise ValueError('生成期间'+ '、'.join(labels.get(k,k) for k in changed)+'已更新，请重新生成 PPT')
        info={'format':'pptx','url':f'/files/{paper["id"]}/{output.name}','filename':output.name,'source_report_at':(snapshot.get('report') or {}).get('generated_at'),
              'generated_at':deck['generated_at'],'provider':deck['provider'],'slides':len(deck['slides']),
              'paper_type':deck.get('paper_type',paper_types.effective(paper))}
        current.setdefault('exports',[]).append(info);store.save('paper',current)
        draft_path=directory/'presentation-draft.json'
        try:
            if json.loads(draft_path.read_text()).get('key')==deck.get('draft_key'):draft_path.unlink()
        except (OSError,ValueError):pass
    return info
