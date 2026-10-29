function knowledgeScheduleButton(){
 const s=state.knowledge_schedule||{},label={running:'更新中',failed:'需重试',pending:'待更新',synced:'已同步'}[s.state]||'未开启';
 return `<button id="knowledge-schedule-open" class="knowledge-schedule-button" aria-label="自动更新设置" title="每周自动更新 · ${s.enabled?label:'未开启'}"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="13" r="7.5"/><path d="M12 9v4l2.5 1.5M3 5l3-2m12 0 3 2M6.5 19l-1.5 2m12.5-2 1.5 2"/></svg>${s.enabled?`<span class="schedule-dot ${s.state}" aria-hidden="true"></span>`:''}</button>`;
}
async function openKnowledgeSchedule(){
 const s=await request('/api/knowledge-schedule');state.knowledge_schedule=s;
 $('#knowledge-schedule-dialog')?.remove();
 const weekdays=['周一','周二','周三','周四','周五','周六','周日'];
 const status={running:'正在整理图谱',failed:'上次更新未完成',pending:'有变化，等待更新',synced:'图谱已同步'}[s.state];
 document.body.insertAdjacentHTML('beforeend',`<dialog id="knowledge-schedule-dialog" class="schedule-dialog"><div class="dialog-head"><h2>每周自动更新</h2><button id="schedule-close" class="textbtn" aria-label="关闭">×</button></div><p class="hint">汇总一周变化，先更新领域图谱，再更新受影响的研究主线。</p><label class="schedule-enable"><span>自动整理知识库</span><input id="schedule-enabled" type="checkbox" ${s.enabled?'checked':''}></label><div class="schedule-fields"><label>每周<select id="schedule-weekday">${weekdays.map((d,i)=>`<option value="${i}" ${s.weekday===i?'selected':''}>${d}</option>`).join('')}</select></label><label>时间 · 北京时间<input id="schedule-time" type="time" value="${esc(s.time)}" required></label></div><div class="schedule-status"><strong>${esc(status)}</strong><p class="hint">${esc(s.progress||s.error||(s.pending_core?'领域图谱待更新；':'')+(s.pending_mainlines?.length?`${s.pending_mainlines.length} 条主线待更新。`:''))}</p>${s.last_success_at?`<p class="hint">最近完成 ${date(s.last_success_at)}</p>`:''}</div><p class="hint">应用关闭时不运行，重开后补上错过的周更；多周未打开也只整理一次。没有变化不调用模型。使用当前账户的模型配置。</p><div id="schedule-error" class="error" hidden></div><div class="schedule-actions">${s.state==='failed'&&s.enabled?'<button id="schedule-retry" class="textbtn">重试未完成部分</button>':'<span></span>'}<button id="schedule-save" class="primary">保存</button></div></dialog>`);
 const dialog=$('#knowledge-schedule-dialog');$('#schedule-close').onclick=()=>dialog.close();
 const toggle=()=>{$('#schedule-weekday').disabled=$('#schedule-time').disabled=!$('#schedule-enabled').checked};
 $('#schedule-enabled').onchange=toggle;toggle();
 const submit=async(retry)=>{
  const button=$(retry?'#schedule-retry':'#schedule-save');button.disabled=true;
  try{state.knowledge_schedule=await request(retry?'/api/knowledge-schedule-retry':'/api/knowledge-schedule',retry?{}:{enabled:$('#schedule-enabled').checked,weekday:Number($('#schedule-weekday').value),time:$('#schedule-time').value});const position=ViewContinuity.capture($('#app'));dialog.close();render(position);toast(retry?'已检查并重试未完成的图谱':'自动更新设置已保存');}
  catch(e){$('#schedule-error').textContent=e.message;$('#schedule-error').hidden=false}
  finally{button.disabled=false}
 };
 $('#schedule-save').onclick=()=>submit(false);if($('#schedule-retry'))$('#schedule-retry').onclick=()=>submit(true);
 dialog.showModal();
}
function confirmKnowledgeUpdate(rebuild=false){
 if(busy)return toast('当前任务还在进行，请等它完成');
 const atlas=selectedKnowledgeAtlas(),core=knowledgeScope==='starred',graph=core?atlas.starred_graph||atlas:atlas;
 const action=rebuild?(core?'重建领域骨架':'重建主线网络'):(graph.generated_at?'增量更新':core?'生成领域骨架':'生成主线图谱');
 const target=core?'领域图谱':atlas.mainline_title||'当前研究主线';
 const description=rebuild?(core?'重新审视收藏与喜欢论文之间的关系，重新分析领域骨架。依赖它的主线图谱将标记为待更新。':'先同步领域骨架，再重新分析当前主线的外围联系；不会重建领域论文之间的关系。'):(core?'复用未变论文与关系的分析，补充新增或发生变化的内容。':'先增量同步领域骨架，再更新当前主线的外围联系，复用未变内容的分析。');
 const payload={mainline:knowledgeMainline,scope:knowledgeScope,rebuild};
 $('#knowledge-confirm-dialog')?.remove();
 document.body.insertAdjacentHTML('beforeend',`<dialog id="knowledge-confirm-dialog" class="knowledge-confirm-dialog" aria-labelledby="knowledge-confirm-title" aria-describedby="knowledge-confirm-description"><div class="dialog-head"><h2 id="knowledge-confirm-title">${action}</h2><button id="knowledge-confirm-close" class="iconbtn" aria-label="关闭">×</button></div><p class="knowledge-confirm-target">${esc(target)}</p><p id="knowledge-confirm-description">${description}</p><div class="knowledge-confirm-note"><strong>将调用当前模型</strong><p>${rebuild?'重建通常比增量更新更耗时、消耗更多。日常补充论文建议使用增量更新。':'耗时与消耗取决于变化的论文数量及模型设置。'}${state.settings.provider==='codex'?'会消耗订阅额度。':'会产生 API 费用。'}</p></div><p class="hint">成功后保存新结果；失败保留原图谱。分阶段完成的领域骨架会独立保存。</p><div class="knowledge-confirm-actions"><button id="knowledge-confirm-cancel" class="secondary" autofocus>取消</button><button id="knowledge-confirm-start" class="primary">确认开始</button></div></dialog>`);
 const dialog=$('#knowledge-confirm-dialog');
 $('#knowledge-confirm-close').onclick=$('#knowledge-confirm-cancel').onclick=()=>dialog.close();
 let submitted=false;
 $('#knowledge-confirm-start').onclick=()=>{if(submitted)return;submitted=true;dialog.close();guard(()=>startJob('/api/knowledge-update',payload))};
 dialog.showModal();
}
let knowledgeSchedulePolling=false;
async function pollKnowledgeSchedule(){
 if(knowledgeSchedulePolling||document.hidden||view!=='knowledge'||busy||!state?.accounts?.active||$('#knowledge-schedule-dialog')?.open||$('#knowledge-confirm-dialog')?.open)return;
 knowledgeSchedulePolling=true;
 try{
  const previous=state.knowledge_schedule,s=await request('/api/knowledge-schedule');state.knowledge_schedule=s;
  if(s.finished_at&&s.finished_at!==previous?.finished_at){await reload();return;}
  const button=$('#knowledge-schedule-open');if(button){button.outerHTML=knowledgeScheduleButton();$('#knowledge-schedule-open').onclick=()=>guard(openKnowledgeSchedule);}
 }catch{/* Retry the read-only status check on the next interval. */}
 finally{knowledgeSchedulePolling=false}
}
setInterval(pollKnowledgeSchedule,15000);

let knowledgeScope='all', knowledgeQuery='', knowledgeFocus='', knowledgeRelationLimit=6, knowledgeZoom=null, historicalDraft='', historicalTarget='read', historicalOpen=false, historicalMode='pdf', historicalPdfId=null, historicalPdfTitle='', historicalPdfMonth='', historicalPdfShort='';
let knowledgeDimension='3d', knowledgeShowAll=false, knowledgeSceneData=null, knowledgeScene=null, knowledgeBundlePromise=null;
let knowledgeMainline='',knowledgeLoading=false,knowledgeLoadRevision=0;
async function loadKnowledgeMainline(key){
 const revision=++knowledgeLoadRevision, previous=state.knowledge?.mainline_key||'';
 knowledgeMainline=key;knowledgeLoading=true;knowledgeFocus='';knowledgeQuery='';knowledgeZoom=null;render();
 try{
  const graph=await request('/api/knowledge?'+new URLSearchParams({mainline:key}));
  if(revision===knowledgeLoadRevision&&knowledgeMainline===key)state.knowledge=graph;
 }catch(error){if(revision===knowledgeLoadRevision){knowledgeMainline=previous;throw error;}}
 finally{if(revision===knowledgeLoadRevision){knowledgeLoading=false;render();}}
}
function selectedKnowledgeAtlas(){
 const saved=state.knowledge||{nodes:[],edges:[],missing:[]};
 return (saved.mainline_key||'')===knowledgeMainline?saved:{nodes:[],edges:[],missing:[],total:saved.total||0,favorites:saved.favorites||0,mainline_options:saved.mainline_options||[]};
}

function prepareKnowledgeRender(){
 if(!knowledgeScene)return;
 if(view!=='knowledge'||knowledgeDimension!=='3d'||knowledgeScene.user!==state.accounts?.active){knowledgeScene.api.destroy();knowledgeScene=null;}
 else knowledgeScene.host.remove();
}
function focusKnowledge(id){knowledgeFocus=id;knowledgeRelationLimit=6;knowledgeZoom=null;render();}
async function mountKnowledgeScene(){
 const slot=$('#knowledge-3d');if(!slot){if(knowledgeScene){knowledgeScene.api.destroy();knowledgeScene=null;}return;}
 const data=knowledgeSceneData;
 const key=JSON.stringify([state.accounts?.active,knowledgeScope==='starred'?'core':knowledgeMainline,knowledgeScope,data.revision]);
 if(knowledgeScene&&knowledgeScene.key!==key){knowledgeScene.api.destroy();knowledgeScene=null;}
 try{
  if(!window.PaperGraph3D){
   if(!knowledgeBundlePromise)knowledgeBundlePromise=new Promise((resolve,reject)=>{const script=document.createElement('script');script.src='/graph3d.bundle.js';script.onload=resolve;script.onerror=()=>{script.remove();knowledgeBundlePromise=null;reject(Error('三维组件加载失败'));};document.head.append(script);});
   await knowledgeBundlePromise;
  }
  if(!slot.isConnected)return;
  slot.replaceChildren();
  if(!knowledgeScene){const host=document.createElement('div');host.className='graph-3d-host';slot.append(host);knowledgeScene={host,key,user:state.accounts?.active,api:window.PaperGraph3D.create(host,data.nodes,data.edges,focusKnowledge,{scope:data.scope})};}
  else {slot.append(knowledgeScene.host);knowledgeScene.api.update(data.nodes,data.edges);}
  knowledgeScene.api.setFocus(knowledgeFocus);
 }catch(e){if(!slot.isConnected)return;knowledgeDimension='2d';render();toast('当前浏览器无法加载三维图谱，已切换二维视图',true);}
}
function knowledgeFocusCard(nodes,edges){
 const n=nodes.find(n=>n.id===knowledgeFocus);
 return n?`<section class="graph-focus-card"><div class="eyebrow">当前聚焦 · ${edges.length} 条联系</div><h3>${esc(n.label)}</h3><div class="graph-node-signals">${n.starred?'<span>★ 收藏</span>':n.liked?'<span>♥ 喜欢</span>':''}<span>${esc(n.readStatus||'未标记')}</span><span>${n.degree} 个邻居</span></div><p>${esc(n.title)}</p><p class="small muted">${esc(n.insight)}</p><div class="row"><button class="primary" data-paper="${esc(n.id)}">打开阅读 ↗</button><button id="knowledge-clear-focus" class="textbtn">取消聚焦</button></div></section>`:'<p class="graph-focus-hint">单击节点聚焦论文，查看它的邻近联系。在此处选择“打开阅读”进入论文。</p>';
}

const paperLabel=p=>[p.publication_month?p.publication_month.slice(2,4)+p.publication_month.slice(5,7):'',p.short_title||'· 待补短标题'].filter(Boolean).join(' ');
function identityFields(p){return `<section class="panel"><h3>论文标识</h3><label>发表年月<input id="publication-month" type="month" value="${esc(p.publication_month||'')}" max="${new Date().toISOString().slice(0,7)}"></label><label>短标题<input id="paper-short-title" maxlength="60" value="${esc(p.short_title||'')}" placeholder="例如 LoRA"></label><button id="save-publication-month" class="secondary">保存标识</button><p class="hint">${esc(paperLabel(p))} · 喜欢、收藏和阅读完毕前需填写。同月短标题不可重复。</p></section>`}
function historicalForm(){
 const result=state.historical_import;
 const p=state.papers.find(p=>p.id===historicalPdfId)||state.papers.find(p=>p.historical_metadata?.pending);
 const d=p?.historical_metadata;
 if(p&&!historicalPdfId){historicalPdfId=p.id;historicalPdfTitle=d?.title||p.title;historicalPdfMonth=d?.publication_month||p.publication_month||'';}
 const ready=Boolean(d?.title&&d?.abstract);
 return `<details class="panel historical-import" ${historicalOpen?'open':''}><summary>导入曾读论文</summary><div class="historical-body"><div class="row">${[['pdf','上传 PDF'],['text','按题名批量导入']].map(([id,label])=>`<button class="${historicalMode===id?'primary':'secondary'}" data-historical-mode="${id}">${label}</button>`).join('')}</div><label>导入到<select id="historical-target"><option value="read" ${historicalTarget==='read'?'selected':''}>已读论文</option><option value="starred" ${historicalTarget==='starred'?'selected':''}>我的收藏</option></select></label>
 ${historicalMode==='pdf'?`<label>论文 PDF<input id="historical-pdf-file" type="file" accept="application/pdf" ${busy?'disabled':''}></label>${p?`<p class="small muted">${esc(p.filename)}</p><label>完整标题<input id="historical-pdf-title" maxlength="300" value="${esc(historicalPdfTitle)}"></label><div class="fieldrow"><label>发表年月<input id="historical-pdf-month" type="month" value="${esc(historicalPdfMonth)}" max="${new Date().toISOString().slice(0,7)}"></label><label>短标题<input id="historical-pdf-short" maxlength="60" value="${esc(historicalPdfShort)}" placeholder="手动填写，例如 GAN"></label></div>${d?.date_source?`<p class="small muted">${esc(d.date_source)}</p>`:''}${ready?`<details class="abstract"><summary>核对识别的原文摘要</summary><p>${esc(d.abstract)}</p></details>`:''}<p class="hint">核对标题、摘要和年月，短标题由你填写。确认后进入所选分类。</p><div class="row"><button id="historical-pdf-recognize" class="secondary" data-task>${ready?'重新识别':'识别元信息'}</button><button id="historical-pdf-date" class="textbtn" ${ready?'':'disabled'} data-task>查询发表年月</button><button id="historical-pdf-finish" class="primary" ${ready&&!busy?'':'disabled'}>确认导入</button></div>`:'<p class="hint">上传后使用当前模型提取元信息，不生成论文解读。</p>'}`:`<label>每行一篇：年月 | 完整标题 | 短标题<textarea id="historical-text" rows="4" maxlength="60000" placeholder="2106 | LoRA: Low-Rank Adaptation of Large Language Models | LoRA">${esc(historicalDraft)}</textarea></label><p class="hint">支持 YYMM 或 YYYY-MM；最多 100 篇。按现有论文来源核对，未命中时可改用 PDF 导入。</p><button id="historical-submit" class="secondary" data-task>核对并导入</button>`}
 ${result?`<details class="import-results" open><summary>上次导入 · 成功 ${result.results.filter(r=>r.ok).length}/${result.total}</summary>${result.results.map(r=>`<p class="${r.ok?'':'error'}">${r.ok?`<button class="textbtn" data-paper="${r.paper_id}">${esc(r.label)} ↗</button>${r.matched_title?`<span class="small muted"> · ${esc(r.matched_title)}</span>`:''}${r.matched_source?` <a class="small" href="${esc(r.matched_source)}" target="_blank" rel="noopener">核实来源 ↗</a>`:''}${r.warning?`<span class="small muted"> · ${esc(r.warning)}</span>`:''}`:`${esc(r.title)}：${esc(r.error)}`}</p>`).join('')}</details>`:''}</div></details>`;
}
function compactPaper(p){return `<article class="compact-paper" tabindex="0" data-paper="${p.id}" title="${esc(p.title)}"><strong>${esc(paperLabel(p))}</strong><div class="row">${preferenceButtons(p)}<button class="textbtn danger small" data-delete="${p.id}" aria-label="移除 ${esc(p.title)}">移除</button>${newPaperPage(p)}</div></article>`}
function metadataPaper(p){return readerBack()+head('PAPER READING',esc(paperLabel(p)),esc(p.title),`<div class="row">${separateReader?'':newPaperPage(p)}${preferenceButtons(p)}<button class="secondary danger" data-delete="${p.id}">移除论文</button></div>`)+`<div class="workspace"><div class="reading-column"><article class="reading"><div class="abstract-section">${esc(p.abstract)}</div><p class="small muted">${esc(p.read_status)} · 历史导入</p>${p.date_basis_url?`<p class="small muted">${esc(p.publication_date_source)} · <a href="${esc(p.date_basis_url)}" target="_blank" rel="noopener">日期依据 ↗</a></p>`:''}<div class="row">${/^https:\/\/arxiv\.org\/abs\//.test(p.source_url||'')?`<button id="download-paper" class="primary" data-task>${p.pdf_cached?'提取原文图表':'下载原文 PDF'}</button>${p.pdf_cached?`<a href="/files/${esc(p.id)}/source.pdf" target="_blank" rel="noopener">打开原文 PDF ↗</a>`:''}`:p.pdf_url?`<a class="primary" href="${esc(p.pdf_url)}" target="_blank" rel="noopener">打开原文 PDF ↗</a>`:''}${p.source_url?`<a href="${esc(p.source_url)}" target="_blank" rel="noopener">论文来源 ↗</a>`:''}</div><p class="hint">arXiv 原文可按需下载；会议论文可打开原文 PDF 后上传。</p><label class="secondary attach-pdf">上传对应 PDF<input id="attach-pdf" type="file" accept="application/pdf"></label></article><section class="panel personal-notes"><h2>我的思考 / 评价</h2><span id="notes-status" class="muted small">${notesDrafts.has(p.id)?'尚未保存':'已保存'}</span><textarea id="personal-notes" rows="7" maxlength="20000">${esc(notesDrafts.get(p.id)??p.notes??'')}</textarea><button id="save-notes" class="primary">保存我的思考</button></section></div><aside class="toolcol">${identityFields(p)}<section class="panel"><h3>阅读状态</h3><span>${esc(p.read_status)}</span>${LibraryView.done(p)?'<button id="start-reading" class="textbtn">开始阅读</button>':''}</section></aside></div>`}
function graphLayout(nodes,edges){
 const adjacent=new Map(nodes.map(n=>[n.id,[]]));edges.forEach(e=>{adjacent.get(e.source)?.push(e.target);adjacent.get(e.target)?.push(e.source)});
 const seen=new Set(),components=[];
 for(const n of [...nodes].sort((a,b)=>Number(b.starred)-Number(a.starred)||a.label.localeCompare(b.label))){if(seen.has(n.id))continue;const ids=[],queue=[n.id];seen.add(n.id);for(let i=0;i<queue.length;i++){const id=queue[i];ids.push(id);for(const next of adjacent.get(id)){if(!seen.has(next)){seen.add(next);queue.push(next)}}}components.push(ids)}
 const positions=new Map();
 if(nodes.length<=12&&components.length===1){const favorites=nodes.filter(n=>n.starred),rest=nodes.filter(n=>!n.starred),center=290;const ring=(items,radius,offset=0)=>items.forEach((n,i)=>{const angle=2*Math.PI*i/items.length+offset;positions.set(n.id,{x:center+radius*Math.cos(angle),y:center+radius*Math.sin(angle)})});if(favorites.length&&rest.length){ring(favorites,favorites.length===1?0:85,-Math.PI/2);ring(rest,195,0)}else ring(nodes,nodes.length===1?0:180,-Math.PI/2);return {positions,width:580,height:570}}
 const byId=new Map(nodes.map(n=>[n.id,n]));let y=85;const cols=Math.max(3,Math.min(10,Math.ceil(Math.sqrt(nodes.length))));
 for(const component of components){const sorted=component.map(id=>byId.get(id)).sort((a,b)=>Number(b.starred)-Number(a.starred)||a.month.localeCompare(b.month)||a.label.localeCompare(b.label));sorted.forEach((n,i)=>positions.set(n.id,{x:135+(i%cols)*240,y:y+Math.floor(i/cols)*125}));y+=Math.ceil(sorted.length/cols)*125+65}
 return {positions,width:Math.min(cols,Math.max(1,nodes.length))*240+60,height:Math.max(460,y)};
}
function knowledge(){
 const atlas=selectedKnowledgeAtlas();const g=knowledgeScope==='starred'&&atlas.starred_graph?atlas.starred_graph:atlas;
 const rawNodes=g.nodes.filter(n=>knowledgeScope==='all'||n.starred||n.liked),ids=new Set(rawNodes.map(n=>n.id));
 const rawEdges=GraphNavigation.clean(rawNodes,g.edges.filter(e=>ids.has(e.source)&&ids.has(e.target)));
 const primary=GraphNavigation.backbone(rawNodes,rawEdges,g.backbone_pairs);
 const neighborCounts=new Map(rawNodes.map(n=>[n.id,0]));
 for(const e of rawEdges){neighborCounts.set(e.source,neighborCounts.get(e.source)+1);neighborCounts.set(e.target,neighborCounts.get(e.target)+1);}
 const focusOptions=GraphMetrics.decorate(rawNodes,Array.isArray(g.backbone_pairs)?primary:rawEdges.filter(e=>e.priority===3),state.papers,knowledgeScope).map(n=>({...n,degree:neighborCounts.get(n.id)}));
 if(knowledgeFocus&&!ids.has(knowledgeFocus))knowledgeFocus='';
 const plan=GraphNavigation.plan(focusOptions,rawEdges,{scope:knowledgeScope,focus:knowledgeFocus,query:knowledgeQuery,all:knowledgeShowAll,limit:knowledgeRelationLimit,pairs:g.backbone_pairs,roles:g.node_roles});
 const nodes=plan.nodes,edges=plan.edges;
 knowledgeSceneData={nodes,edges,scope:knowledgeScope,focus:knowledgeFocus,revision:[g.generated_at,g.provider]};
 const visible=new Map(focusOptions.map(n=>[n.id,n])),layout=graphLayout(focusOptions,rawEdges),relationEdges=knowledgeFocus?edges:[];
 return head('YOUR KNOWLEDGE ATLAS',`<span class="knowledge-title">知识库${knowledgeScheduleButton()}</span>`,knowledgeScope==='starred'?'长期领域骨架 · 收藏与喜欢，按研究方向组织。':'主线研究地图 · 按当前研究主线连接收藏、喜欢与已读论文。',`<div class="row knowledge-actions"><button id="knowledge-update" class="secondary" title="更新当前图谱" data-task ${knowledgeLoading?'disabled':''}>${g.generated_at?'增量更新':knowledgeScope==='starred'?'生成领域骨架':'生成主线图谱'}</button>${g.generated_at?`<button id="knowledge-rebuild" class="secondary" title="${knowledgeScope==='starred'?'重建长期领域骨架':'保留领域骨架，重建当前主线的外围网络'}" data-task ${knowledgeLoading?'disabled':''}>${knowledgeScope==='starred'?'重建领域骨架':'重建主线网络'}</button>`:''}</div>`)+`
 ${knowledgeScope==='all'?`<div class="knowledge-mainline-picker"><label for="knowledge-mainline">研究主线</label><select id="knowledge-mainline" ${busy?'disabled':''}>${!(atlas.mainline_options||[]).length?'<option value="">请先填写研究主线</option>':''}${(atlas.mainline_options||[]).map(line=>`<option value="${esc(line.key)}" ${line.key===knowledgeMainline?'selected':''}>${esc(line.title)}</option>`).join('')}</select>${knowledgeLoading?'<span class="small muted">正在读取图谱…</span>':''}</div>`:''}
 <div class="knowledge-toolbar"><div class="library-tabs" role="tablist" aria-label="知识图谱范围">${[['starred','领域图谱',atlas.favorites||0],['all','主线图谱',atlas.total||0]].map(([id,label,count])=>`<button role="tab" aria-selected="${knowledgeScope===id}" data-knowledge-scope="${id}" class="${knowledgeScope===id?'active':''}">${label}<span class="count">${count} 篇</span></button>`).join('')}</div><span class="small muted">${g.generated_at?(g.stale?'待更新':'已同步'):'未生成'}${g.generated_at?' · '+date(g.generated_at):''} · ${({low:'轻量思考',medium:'标准思考',high:'深入思考'})[state.settings.knowledge_deep_thinking?'high':(state.settings.reasoning?.knowledge||'medium')]}</span></div>
 ${g.missing?.length?`<section class="panel"><p>这些论文还需要补充年月或短标题：</p>${g.missing.map(p=>`<button class="textbtn" data-paper="${p.id}">${esc(p.title)} ↗</button>`).join(' ')}</section>`:''}
 ${g.nodes.length?`<div class="knowledge-controls"><input id="knowledge-search" placeholder="查找简称、标题或主题" value="${esc(knowledgeQuery)}" aria-label="搜索知识图谱"><div class="graph-view-switch" role="group" aria-label="图谱维度">${[['3d','三维'],['2d','二维']].map(([id,label])=>`<button class="${knowledgeDimension===id?'primary':'secondary'}" data-graph-dimension="${id}" aria-pressed="${knowledgeDimension===id}">${label}</button>`).join('')}</div>${knowledgeDimension==='2d'?`<label>缩放 <input id="knowledge-zoom" type="range" min="0.1" max="1.6" step="0.05" value="${knowledgeZoom||1}"></label>`:''}<button id="knowledge-fit" class="textbtn small">适应窗口</button><div class="graph-view-switch" role="group" aria-label="地图范围">${[['overview','总览'],['all','全部']].map(([id,label])=>`<button data-knowledge-map="${id}" class="${(id==='all')===knowledgeShowAll?'primary':'secondary'}" aria-pressed="${(id==='all')===knowledgeShowAll}">${label}</button>`).join('')}</div><span class="small muted" id="knowledge-map-count">${knowledgeFocus?'局部地图':plan.mode==='search'?'搜索结果':knowledgeShowAll?'完整地图':'主干总览'} · ${nodes.length} / ${rawNodes.length} 篇 · ${edges.length} 条联系</span><span class="small muted">${knowledgeDimension==='3d'?'拖动空白处旋转 · 滚轮缩放 · 右键拖动平移 · 拖动节点调整位置':'★ 收藏 · ♥ 喜欢 · 点击连线查看依据'} · 单击节点聚焦</span><span class="graph-importance-legend small" title="显示权重优先考虑当前研究用途，结合阅读深度和主干联系；不是论文质量或引用量排名"><i></i>节点越大、色阶越靠右，当前图谱中的权重越高 · ★ 收藏 · ♥ 喜欢</span></div><div class="knowledge-workspace"><div class="graph-viewport ${knowledgeDimension==='3d'?'is-3d':''}" tabindex="0" aria-label="论文知识图谱">${knowledgeDimension==='3d'?'<div id="knowledge-3d"><p class="graph-loading">正在加载三维图谱…</p></div>':`<svg id="knowledge-svg" role="group" aria-label="论文关系图" viewBox="0 0 ${layout.width} ${layout.height}" style="width:${layout.width*(knowledgeZoom||1)}px;height:${layout.height*(knowledgeZoom||1)}px">${edges.map((e,i)=>{const a=layout.positions.get(e.source),b=layout.positions.get(e.target);return `<path tabindex="0" role="button" aria-label="${esc(visible.get(e.source).label+' 与 '+visible.get(e.target).label+'：'+e.relation)}" class="graph-edge" data-edge-source="${e.source}" data-edge-target="${e.target}" d="M${a.x},${a.y} Q${(a.x+b.x)/2},${Math.min(a.y,b.y)-35} ${b.x},${b.y}"><title>${esc(e.relation)}</title></path>`}).join('')}${nodes.map(n=>{const pos=layout.positions.get(n.id);return `<g class="graph-node ${n.starred?'core':''} ${n.id===knowledgeFocus?'is-focused':''}" transform="translate(${pos.x},${pos.y})" tabindex="0" role="button" data-knowledge-focus="${n.id}" aria-label="聚焦 ${esc(n.label)}"><circle r="${n.graphRadius}" style="fill:${n.id===knowledgeFocus?'#563775':n.graphColor}"/><text y="43" text-anchor="middle">${((n.starred?'★ ':n.liked?'♥ ':'')+n.label).match(/.{1,22}/gu).map((part,i)=>`<tspan x="0" dy="${i?18:0}">${esc(part)}</tspan>`).join('')}</text><title>${esc(n.title+'\n'+n.insight)}</title></g>`}).join('')}</svg>`}${!nodes.length?`<p class="empty">${plan.mode==='overview'?'当前没有突出相关的论文，可搜索或查看全部。':'没有匹配的论文'}</p>`:''}</div><aside class="knowledge-relations" data-scroll-key="relations-${esc(knowledgeMainline)}-${knowledgeScope}-${esc(knowledgeFocus)}">${knowledgeFocusCard(focusOptions,relationEdges)}${knowledgeFocus?`<button id="knowledge-return-overview" class="textbtn small">返回总览</button>`:''}${knowledgeFocus?`<h3>相关联系 <small>${relationEdges.length}</small></h3>`:''}<select id="knowledge-focus" aria-label="查看某篇论文的局部图谱"><option value="">选择论文（含总览隐藏项）</option>${focusOptions.map(n=>`<option value="${n.id}" ${n.id===knowledgeFocus?'selected':''}>${esc(n.label)}</option>`).join('')}</select><div id="knowledge-edge-detail"></div>${relationEdges.slice(0,knowledgeRelationLimit).map(e=>relationCard(e,visible)).join('')||(knowledgeFocus?'<p class="muted">当前没有足够依据建立有用联系，论文仍保留在图中。</p>':'<p class="graph-empty-focus">总览呈现核心论文与主干联系。选择论文，展开局部地图；搜索可找到隐藏的论文。</p>')}${plan.totalRelations>relationEdges.length?'<div class="row"><button id="knowledge-more" class="secondary">展开更多联系</button><button id="knowledge-all-neighbors" class="textbtn small">展开全部联系</button></div>':''}</aside></div><p class="hint">${knowledgeScope==='starred'?'领域骨架以长期研究方向组织。':'收藏与喜欢保留领域关系，外围联系围绕当前主线。'}${g.evidence_coverage?` · 联网原文 ${g.evidence_coverage.web} 篇 · 本地原文 ${g.evidence_coverage.local} 篇 · 未取得原文 ${g.evidence_coverage.unavailable} 篇 · 阅读报告 ${g.evidence_coverage.report||0} 篇 · 引言 ${g.evidence_coverage.introduction||0} 篇`:''}</p>`:`<section class="panel empty"><div class="empty-icon">⌘</div><h2>让读过的论文彼此连接</h2><p>喜欢、收藏或完成阅读后，点击生成知识图谱。也可以先导入以前读过的论文。</p></section>`}${historicalForm()}`;
}
function relationCard(e,nodes){
 const excerpt=side=>{const source=e['source_'+side]||{},url=source.url||'',label=source.kind==='web'?'联网原文':source.kind==='local'?'本地原文':source.section==='introduction'?'引言':source.section==='opening'?'正文开头':source.kind==='notes'?'个人思考':source.kind==='report'?'阅读报告（模型解读）':'摘要';return `<blockquote>${esc(e['quote_'+side])}<div class="small muted">${/^https:\/\/arxiv\.org\/html\//.test(url)?`<a href="${esc(url)}" target="_blank" rel="noopener">${label} ↗</a>`:label}</div></blockquote>`};
 return `<article class="relation-card"><div><button class="textbtn small" data-knowledge-focus="${e.source}">${esc(nodes.get(e.source)?.label||'')}</button><span> ↔ </span><button class="textbtn small" data-knowledge-focus="${e.target}">${esc(nodes.get(e.target)?.label||'')}</button></div><strong>${esc(e.relation)}</strong>${e.priority?`<span class="relation-priority">${(e.layer==='core'?['','背景基础','方法关联','核心关联']:['','背景线索','方法借鉴','主线关键'])[e.priority]||''}</span>`:''}<p>${esc(e.reason)}</p>${e.research_use?`<p class="relation-use">${esc(e.research_use)}</p>`:''}<details><summary>查看依据</summary>${excerpt('a')}${excerpt('b')}</details></article>`;
}
function bindKnowledge(){
 const on=(s,fn)=>{const e=$(s);if(e)e.onclick=()=>guard(fn)};
 const fit=()=>{if(knowledgeDimension==='3d'){knowledgeScene?.api.fit();return;}const svg=$('#knowledge-svg');if(!svg)return;const box=svg.viewBox.baseVal;knowledgeZoom=Math.max(.1,Math.min(1,(svg.parentElement.clientWidth-16)/box.width));svg.style.width=box.width*knowledgeZoom+'px';svg.style.height=box.height*knowledgeZoom+'px';$('#knowledge-zoom').value=knowledgeZoom};
 if(knowledgeZoom===null&&knowledgeDimension==='2d')fit();on('#knowledge-fit',fit);
 mountKnowledgeScene();
 document.querySelectorAll('[data-graph-dimension]').forEach(b=>b.onclick=()=>{knowledgeDimension=b.dataset.graphDimension;knowledgeZoom=null;render()});
 document.querySelectorAll('[data-knowledge-focus]').forEach(el=>{el.onclick=()=>focusKnowledge(el.dataset.knowledgeFocus);el.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();el.onclick()}}});
 on('#knowledge-clear-focus',()=>focusKnowledge(''));
 document.querySelectorAll('[data-knowledge-map]').forEach(b=>b.onclick=()=>{knowledgeShowAll=b.dataset.knowledgeMap==='all';knowledgeFocus='';knowledgeQuery='';knowledgeZoom=null;render()});
 on('#knowledge-return-overview',()=>{knowledgeShowAll=false;knowledgeQuery='';focusKnowledge('')});
 on('#knowledge-more',()=>{knowledgeRelationLimit+=6;knowledgeZoom=null;render()});
 on('#knowledge-all-neighbors',()=>{knowledgeRelationLimit=Number.MAX_SAFE_INTEGER;knowledgeZoom=null;render()});
 on('#knowledge-schedule-open',openKnowledgeSchedule);
 on('#knowledge-update',()=>confirmKnowledgeUpdate());
 on('#knowledge-rebuild',()=>confirmKnowledgeUpdate(true));
 if($('#knowledge-mainline'))$('#knowledge-mainline').onchange=e=>{guard(()=>loadKnowledgeMainline(e.target.value));};
 document.querySelectorAll('[data-knowledge-scope]').forEach(b=>b.onclick=()=>{knowledgeScope=b.dataset.knowledgeScope;knowledgeFocus='';knowledgeQuery='';knowledgeShowAll=false;knowledgeZoom=null;render()});
 if($('#knowledge-search'))$('#knowledge-search').onchange=e=>{knowledgeQuery=e.target.value;knowledgeFocus='';knowledgeZoom=null;render()};
 if($('#knowledge-zoom'))$('#knowledge-zoom').oninput=e=>{knowledgeZoom=Number(e.target.value);const svg=$('#knowledge-svg'),box=svg.viewBox.baseVal;svg.style.width=box.width*knowledgeZoom+'px';svg.style.height=box.height*knowledgeZoom+'px'};
 if($('#knowledge-focus'))$('#knowledge-focus').onchange=e=>focusKnowledge(e.target.value);
 document.querySelectorAll('[data-edge-source]').forEach(el=>{el.onclick=()=>{knowledgeFocus=el.dataset.edgeSource;render();const atlas=selectedKnowledgeAtlas(),graph=knowledgeScope==='starred'&&atlas.starred_graph?.generated_at?atlas.starred_graph:atlas;const e=graph.edges.find(e=>e.source===el.dataset.edgeSource&&e.target===el.dataset.edgeTarget);if(e){$('#knowledge-edge-detail').innerHTML=relationCard(e,new Map(graph.nodes.map(n=>[n.id,n])));$('#knowledge-edge-detail').scrollIntoView({block:'nearest'});$('#knowledge-edge-detail').querySelectorAll('[data-knowledge-focus]').forEach(b=>b.onclick=()=>focusKnowledge(b.dataset.knowledgeFocus))}};el.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();el.onclick()}}});
 if($('.historical-import'))$('.historical-import').ontoggle=e=>historicalOpen=e.target.open;
 if($('#historical-text'))$('#historical-text').oninput=e=>historicalDraft=e.target.value;
 if($('#historical-target'))$('#historical-target').onchange=e=>historicalTarget=e.target.value;
 document.querySelectorAll('[data-historical-mode]').forEach(b=>b.onclick=()=>{historicalMode=b.dataset.historicalMode;render()});
 if($('#historical-pdf-title'))$('#historical-pdf-title').oninput=e=>historicalPdfTitle=e.target.value;
 if($('#historical-pdf-month'))$('#historical-pdf-month').oninput=e=>historicalPdfMonth=e.target.value;
 if($('#historical-pdf-short'))$('#historical-pdf-short').oninput=e=>historicalPdfShort=e.target.value;
 if($('#historical-pdf-file'))$('#historical-pdf-file').onchange=()=>guard(async()=>{
  const f=$('#historical-pdf-file').files[0];if(!f||busy)return;
  $('#historical-pdf-file').disabled=true;
  try{const p=await request('/api/upload',f,true,{'X-Filename':encodeURIComponent(f.name)});
   historicalPdfId=p.id;historicalPdfTitle=p.title;historicalPdfMonth=p.publication_month||'';historicalPdfShort='';
   await reload();await startJob('/api/historical-pdf-metadata',{id:p.id});
  }finally{if($('#historical-pdf-file'))$('#historical-pdf-file').disabled=false;}
 });
 on('#historical-pdf-recognize',()=>startJob('/api/historical-pdf-metadata',{id:historicalPdfId}));
 on('#historical-pdf-date',()=>startJob('/api/historical-pdf-date',{id:historicalPdfId,title:historicalPdfTitle}));
 on('#historical-pdf-finish',()=>guard(async()=>{
  if(busy)return;
  await request('/api/historical-pdf-finish',{id:historicalPdfId,title:historicalPdfTitle,month:historicalPdfMonth,short_title:historicalPdfShort,target:historicalTarget});
  historicalPdfId=null;historicalPdfTitle='';historicalPdfMonth='';historicalPdfShort='';await reload();toast('已导入'+(historicalTarget==='starred'?'我的收藏':'已读论文'));
 }));
 on('#historical-submit',()=>startJob('/api/historical-import',{text:historicalDraft,target:historicalTarget}));
 on('#download-paper',()=>startJob('/api/paper-download',{id:selected.id}));
 if($('#attach-pdf'))$('#attach-pdf').onchange=()=>guard(async()=>{const f=$('#attach-pdf').files[0];if(!f)return;acceptPaperUpdate(await request('/api/upload',f,true,{'X-Filename':encodeURIComponent(f.name),'X-Paper-Id':selected.id}));await reload();toast('原文已保存，可以生成解读')});
}
