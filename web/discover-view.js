const foldStates=new Map();
function foldKey(section){return 'paperpilot-'+section+'-open:'+(state?.accounts?.active||'local')}
function foldExpanded(section,defaultOpen=false){const key=foldKey(section);if(foldStates.has(key))return foldStates.get(key);try{const saved=localStorage.getItem(key);return saved===null?defaultOpen:saved==='true'}catch{return defaultOpen}}
function setFoldExpanded(section,expanded){const key=foldKey(section);foldStates.set(key,expanded);try{localStorage.setItem(key,String(expanded))}catch{}}
function foldPanel(id,title,meta,body,{defaultOpen=false,className=''}={}){const open=foldExpanded(id,defaultOpen);return `<details class="panel fold-panel ${className}" id="${esc(id)}" data-fold-key="${esc(id)}" ${open?'open':''}><summary><span class="fold-title">${esc(title)}${meta?` <span class="count">${esc(meta)}</span>`:''}</span><span class="fold-action"><span id="${esc(id)}-action" data-fold-action>${open?'收起':'展开'}</span><svg viewBox="0 0 20 20" aria-hidden="true"><path d="m5 7 5 5 5-5"/></svg></span></summary><div class="fold-content">${body}</div></details>`}
/* Hotspot browsing and three parallel paper-search workflows. */
function discover(){
 const d=discoveryDraft||(discoveryDraft={query:'',days:'30',count:'2',sources:state.settings.discovery_sources,routeGoal:''});
 const favorites=(state.favorites||[]);
 cardRefs=[];
 return head('PAPER SEARCH','论文检索','从一个检索条件、论文标题，或一段研究想法开始。')+`
 <section class="panel search-panel"><div class="search-mode-tabs" role="group" aria-label="论文查找方式">${[['filter','按需筛选'],['title','按论文名搜索'],['model','模型推荐']].map(([mode,label])=>`<button class="${discoveryMode===mode?'primary':'secondary'}" data-search-mode="${mode}" aria-pressed="${discoveryMode===mode}">${label}</button>`).join('')}</div>${discoveryMode==='model'?modelDiscussion():discoveryMode==='title'?`<form id="title-search-form"><label>论文标题或简称<input id="title-query" maxlength="300" placeholder="完整标题、简称或前几个词，例如 FasterWAM、ResNet" value="${esc(titleQuery)}" required></label><div class="title-search-options"><button id="title-search" type="submit" class="primary" ${titleLoading?'disabled':''}>${titleLoading?'搜索中…':'搜索论文'}</button><button id="title-google" type="button" class="textbtn">在 Google Scholar 中搜索 ↗</button></div></form>${titleLoading?`<p class="hint" role="status">${esc(titleProgress)}</p>`:''}${titleError?`<p class="error" role="alert">${esc(titleError)}</p>`:''}`:`<div class="source-options">${sourceOptions(d.sources,'discover-source')}</div><label>检索需求<input id="search-query" placeholder='例如："world action model" OR "cloth manipulation"' value="${esc(d.query)}"></label><div class="search-options"><label>论文时间<select id="search-days">${[[30,'近 30 天'],[7,'近 7 天'],[90,'近 90 天'],[0,'不限日期']].map(([v,t])=>`<option value="${v}" ${String(v)===d.days?'selected':''}>${t}</option>`).join('')}</select></label><label>推荐条目数<input id="search-count" type="number" min="1" max="20" step="1" value="${esc(d.count)}"></label><button id="recommend" class="primary" data-task>筛选并推荐</button></div>`}</section>
 ${discoveryMode==='title'&&titleResult?`<section class="panel search-results title-results"><div class="section-head"><h2>标题搜索结果 <span class="count">${titleResult.items.length} 篇</span></h2><button id="clear-title-search" class="textbtn">清除结果</button></div><div class="runhead">${esc(titleResult.query)}</div>${titleSearchStatus(titleResult)}${titleResult.items.map(p=>paperCard(p,'title-search',titleResult.id)).join('')||`<p class="muted">${titleResult.source_status.some(s=>s.ok)?'没有找到匹配论文，可尝试完整标题或 Google Scholar。':'暂时无法读取搜索来源，请稍后重试或使用 Google Scholar 网页搜索。'}</p>`}</section>`:''}
 ${discoveryMode==='model'?modelResults():''}
 ${discoveryMode==='filter'&&searchResult?`<section class="panel search-results"><div class="section-head"><h2>本次筛选 <span class="count">${searchResult.recommendations.length} / ${searchResult.requested_count||d.count} 篇</span></h2><button id="clear-search" class="textbtn">清除结果</button></div><div class="runhead">${date(searchResult.created_at)} · ${esc(searchResult.query)}</div>${sourceStates(searchResult)}${searchResult.recommendations.map(p=>paperCard(p,'discovery',searchResult.id)).join('')||'<p class="muted">没有符合要求的候选，请调整检索条件或查看来源状态。</p>'}</section>`:''}
 ${foldPanel('waiting-list','待读清单',favorites.length+' 篇',favorites.map(f=>paperCard(f.paper,'favorite','',f)).join('')||'<p class="muted">想读的论文可以先加入这里，成功导入论文库后自动移出。</p>',{className:'favorites-panel'})}
 <div class="section-head"><h2>为当前问题安排学习路线</h2></div><section class="panel"><div class="fieldrow"><input id="route-goal" value="${esc(d.routeGoal)}" placeholder="描述学习目标，结合研究档案与上方来源"><button id="route" class="secondary" data-task>生成路线</button></div>${state.routes.map(r=>foldPanel('route-'+r.id,r.question||'已保存的学习路线',date(r.created_at),sourceStates(r)+`<div class="route-content">${esc(r.text)}</div>`,{className:'saved-route'})).join('')}</section>`;
}

let hotspotSkippedOpen=false;
const hotspotRestored=new Map();
function hotspotIdentity(item,kind='paper'){
 const value=String(item.paper_url||item.source_url||item.id||'');
 if(kind==='paper'){
  const match=value.match(/(?:arxiv\.org\/(?:abs|pdf)\/|huggingface\.co\/papers\/|papers\.cool\/arxiv\/)(\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?\/\d{7})(?:v\d+)?/i);
  if(match)return 'paper:arxiv:'+match[1].toLowerCase();
  if(/^https?:\/\/(?:dx\.)?doi\.org\//i.test(value))return 'paper:doi:'+value.replace(/^https?:\/\/(?:dx\.)?doi\.org\//i,'').toLowerCase();
 }
 try{const url=new URL(value);url.hash='';return kind+':'+url.href}catch{return kind+':'+value}
}
function hotspotIsSkipped(item,kind='paper'){clearExpiredHotspots();const key=hotspotIdentity(item,kind);return (state.hotspot_skips||[]).some(entry=>entry.identity===key)}
function hotspotSkipButton(item,origin,runId=''){
 const ref=cardRefs.push({paper:item,origin,runId})-1;
 return `<button type="button" class="textbtn hotspot-skip" data-skip-hotspot="${ref}" title="收起这条内容，可从已略过中恢复">略过</button>`;
}
function skippedHotspots(){
 if(!hotspotSkippedOpen)return '';
 const entries=[...(state.hotspot_skips||[]),...hotspotRestored.values()];
 return `<section class="panel skipped-hotspots" aria-label="已略过的热点"><div class="section-head"><div><h3>已略过</h3></div><button id="close-skipped-hotspots" class="textbtn small">收起</button></div><div class="daily-list" data-scroll-key="hotspot-skipped">${entries.map(entry=>{
  const item=entry.item,restored=hotspotRestored.has(entry.id),url=item.paper_url||item.source_url;
  return `<article class="skipped-hotspot-row" data-view-anchor="skipped-${esc(entry.id)}"><div class="skipped-hotspot-title"><div><span class="small muted">${entry.kind==='article'?'推文':'论文'} · ${sourceLabel(item.source||'arxiv')}</span><h3><a href="${esc(url)}" target="_blank" rel="noopener">${esc(item.title)} ↗</a></h3></div><button class="textbtn small" data-restore-hotspot="${esc(entry.id)}" ${restored?'disabled':''}>${restored?'已恢复':'恢复'}</button></div>${entry.kind==='paper'?`<details class="skipped-paper-details"><summary>摘要与阅读操作</summary>${paperCard(item,restored?'hotspot-recovered':'hotspot-skipped',entry.id)}</details>`:''}</article>`;
 }).join('')||'<p class="muted">还没有略过的内容。</p>'}</div></section>`;
}
async function skipHotspot(button){
 const ref=cardRefs[Number(button.dataset.skipHotspot)],context=navigationContext();
 button.disabled=true;
 try{
  const entry=await request('/api/hotspot-skip',{origin:ref.origin,run_id:ref.runId,paper_id:ref.paper.id,url:ref.paper.source_url});
  state.hotspot_skips=(state.hotspot_skips||[]).filter(e=>e.id!==entry.id).concat(entry);
  hotspotRestored.delete(entry.id);
  if(stillAt(context))render();
 }finally{button.disabled=false}
}
async function restoreHotspot(button){
 const context=navigationContext();button.disabled=true;
 try{
  const entry=await request('/api/hotspot-restore',{id:button.dataset.restoreHotspot});
  state.hotspot_skips=(state.hotspot_skips||[]).filter(e=>e.id!==entry.id);
  hotspotRestored.set(entry.id,entry);
  if(stillAt(context))render();
 }finally{button.disabled=false}
}

function hotspots(){
 clearExpiredHotspots();
 cardRefs=[];
 return head('RESEARCH RADAR','热点发现','',`<button id="show-skipped-hotspots" class="secondary hotspot-skipped-entry" aria-expanded="${hotspotSkippedOpen}">已略过 <span class="count">${(state.hotspot_skips||[]).length}</span></button>`)+`
 <div class="section-head"><div class="paper-feed-control"><span class="hf-brand">🤗 HF</span><select id="paper-feed" aria-label="论文来源"><option value="embodied" ${paperFeed==='embodied'?'selected':''}>具身日报</option><option value="hf" ${paperFeed==='hf'?'selected':''}>全量列表</option></select></div></div>
 ${skippedHotspots()}
 ${paperFeed==='embodied'?embodiedPanel():''}
 ${paperFeed==='hf'?`<section class="panel search-panel"><h3 class="hotspot-section-title">全量列表</h3><div class="search-options hf-options"><label>列表时间<select id="hf-days" ${hfLoading||busy?'disabled':''}>${[[1,'近一天'],[3,'近三天']].map(([v,t])=>`<option value="${v}" ${String(v)===hfDays?'selected':''}>${t}</option>`).join('')}</select></label><button id="hf-list" class="secondary" ${hfLoading||busy?'disabled':''}>${hfLoading?'正在读取…':hfResult?.days===Number(hfDays)?'刷新列表':'查看列表'}</button></div>${hfError?`<p class="error">${esc(hfError)}</p>`:''}</section>
 ${hfResult?hfResults():''}`:''}
`;
}

function hfResearchContext(){return {research_directions:state.profile?.research_directions||'',mainlines:state.profile?.mainlines||[]}}
function hfResults(){
 const context=hfResearchContext(),current=JSON.stringify(hfResult.research_context)===JSON.stringify(context);
 if(!current)hfOnlyRelevant=false;
 const items=hfResult.items.filter(p=>!hotspotIsSkipped(p)).map(p=>({...p,classification:current?p.classification:null}));
 const classified=items.filter(p=>p.classification),hasContext=Boolean(context.research_directions.trim()||context.mainlines.length);
 const onlyMine=hfOnlyRelevant&&hasContext;
 const visible=items.filter(p=>!onlyMine||p.classification?.relevant);
 const relevantCount=classified.filter(p=>p.classification.relevant).length;
 return foldPanel('hf-results',`论文 · ${hfResult.days===1?'近一天':'近三天'}`,`${visible.length} / ${items.length} 篇`,`<div class="section-head"><span class="small muted">${esc([...hfResult.dates].reverse().join(' — '))}</span><div class="row"><button id="hf-classify" class="secondary" data-task ${busy||hfLoading||!items.length||classified.length===items.length?'disabled':''}>${classified.length===items.length?'已筛选':classified.length?'继续筛选':'AI 筛选'}</button><button id="clear-hf-list" class="textbtn small" ${busy?'disabled':''}>清除列表</button></div></div>
 ${classified.length?`<div class="hf-personal-filter" role="group" aria-label="论文筛选"><button class="${!onlyMine?'primary':'secondary'}" id="hf-all" aria-pressed="${!onlyMine}">全部 <span>${items.length}</span></button><button class="${onlyMine?'primary':'secondary'}" id="hf-mine" aria-pressed="${onlyMine}">为我精选 <span>${relevantCount}</span></button>${classified.length<items.length?`<span class="small muted">已筛选 ${classified.length} / ${items.length}</span>`:''}</div>`:''}
 ${!hfResult.complete?'<p class="error">部分日期未读取完整，可刷新重试。</p>':''}<details class="coverage"><summary>读取状态</summary>${sourceStates(hfResult)}</details><div class="daily-list" data-scroll-key="hf-${hfResult.id}">${visible.map(p=>paperCard({...p,reason:p.classification?.reason||''},'hf-listing',hfResult.id)).join('')||`<div class="empty"><p>${onlyMine?'暂无匹配论文，可切换全部。':'暂无待浏览论文。'}</p></div>`}</div>`,{defaultOpen:true,className:'hf-results'});
}

function modelDiscussion(){
 const chat=state.recommendation_chat||{messages:[],candidates:[]}, name=state.profile?.display_name?.trim()||'我';
 return `<div class="section-head"><h3>和助手一起找论文</h3><button id="reset-model-discussion" class="textbtn" ${modelPending||!chat.messages.length?'disabled':''}>重新讨论</button></div>
 <div id="recommendation-messages" data-scroll-key="recommendation-messages" data-scroll-follow="end" class="recommendation-messages" role="log" aria-label="论文推荐对话" tabindex="0">${chat.messages.map(m=>`<div class="message ${m.role}">${messageAuthor(m.role,name)}<div class="message-body">${m.role==='assistant'?ChatView.render(m.content,(latex,display)=>window.katex?katex.renderToString(latex,{throwOnError:false,displayMode:display,trust:false}):esc(latex)):esc(m.content)}</div>${m.model?`<small>${esc(names[m.provider]||m.provider)} · ${esc(m.model)}</small>`:''}</div>`).join('')}${modelQuestion?`<div class="message user">${messageAuthor('user',name)}<div>${esc(modelQuestion)}</div></div>`:''}${!chat.messages.length&&!modelQuestion?'<div class="emptychat"><h3>从正在思考的问题聊起</h3><p>告诉助手你的想法、遇到的困难或想补的基础，再一起缩小阅读范围。</p></div>':''}</div>
 <form id="model-discussion-form" class="recommendation-composer"><label class="sr-only" for="model-question">研究需求与想法</label><textarea id="model-question" rows="3" maxlength="6000" placeholder="例如：我想了解如何把少量真实数据与布料仿真结合，优先寻找方法简洁的工作…">${esc(modelDraft)}</textarea><p id="model-progress" class="small muted" role="status">${modelPending?'正在处理…':''}</p>${modelError?`<p class="error" role="alert">${esc(modelError)}</p>`:''}<div class="composer-actions"><span class="small muted">${esc(names[state.settings.provider])} · 对话保存在本机</span><div class="row"><button type="submit" class="primary" ${modelPending?'disabled':''}>发送</button><button id="generate-model-recommendations" type="button" class="secondary" ${modelPending||!chat.candidates.length?'disabled':''}>整理推荐${chat.candidates.length?' · '+chat.candidates.length+' 篇':''}</button></div></div></form>`;
}
function modelResults(){
 const chat=state.recommendation_chat, r=chat?.result;
 if(!r)return '';
 const missing=r.candidates.filter(c=>!c.verified);
 return `<section class="panel search-results model-results"><div class="section-head"><h2>模型推荐结果 <span class="count">${r.items.length} 篇</span></h2><span class="small muted">${date(r.created_at)}</span></div>${r.revision!==chat.revision?'<p class="hint">对话已继续更新，可点击“整理推荐”更新此清单。</p>':''}<details class="coverage"><summary>论文核实与来源状态</summary>${sourceStates(r)}${missing.length?`<p>以下候选尚未核实，未生成论文卡片：</p><ul>${missing.map(c=>`<li>${esc(c.title)}</li>`).join('')}</ul>`:''}</details>${r.items.map(p=>paperCard(p,'model-recommendation',r.id)).join('')||'<p class="muted">尚未核实到对应论文，可补充完整标题后重试。</p>'}</section>`;
}
function restoreModelTask(){
 const job=state.recommendation_chat?.last_task;
 if(!job)return;
 if(job.status==='failed'){
  modelError=job.error||'本轮未完成，已有对话保留';
  if(!modelDraft&&job.question)modelDraft=job.question;
 }else if(['queued','running'].includes(job.status))modelQuestion=job.question||'';
}
async function followModelJob(job){
 modelPending=true;modelError='';if(view==='discover'&&discoveryMode==='model')render();
 const question=job.question||modelQuestion;
 try{
  while(['queued','running'].includes(job.status)){
   const elapsed=Math.max(0,Math.floor((Date.now()-Date.parse(job.created_at))/1000));
   if($('#model-progress'))$('#model-progress').textContent=(job.status==='queued'?'排队中':job.progress||'正在处理…')+(Number.isFinite(elapsed)?` · 已等待 ${elapsed} 秒`:'');
   await new Promise(r=>setTimeout(r,1200));
   for(let attempt=0;;attempt++){
    try{job=await request('/api/job/'+job.id);break}
    catch(e){if(attempt>=2||/用户|会话/.test(e.message))throw Error('进度连接中断，后台可能仍在处理。刷新页面可继续查看。'+e.message);await new Promise(r=>setTimeout(r,1200))}
   }
  }
  if(job.status!=='completed')throw Error(job.error||'本轮未完成，请重试');
  state.recommendation_chat=job.result;
 }catch(e){
  modelError=e.message;
  if(!modelDraft&&question)modelDraft=question;
  throw e;
 }finally{modelPending=false;modelQuestion='';if(view==='discover'&&discoveryMode==='model')render()}
}
async function sendRecommendationMessage(){
 if(modelPending)return;
 const q=modelDraft.trim();if(!q)return;
 modelError='';modelQuestion=q;modelDraft='';modelPending=true;render();
 try{await followModelJob(await request('/api/model-discuss',{question:q,revision:state.recommendation_chat.revision}))}
 catch(e){modelError=e.message;if(!modelDraft)modelDraft=q}
 finally{modelPending=false;modelQuestion='';if(view==='discover')render()}
}
function bindDiscovery(){
 bindEmbodied();
 document.querySelectorAll('[data-fold-key]').forEach(el=>el.ontoggle=()=>{setFoldExpanded(el.dataset.foldKey,el.open);const action=el.querySelector(':scope > summary [data-fold-action]');if(action)action.textContent=el.open?'收起':'展开'});

 if($('#model-question')){
  $('#model-question').oninput=e=>modelDraft=e.target.value;
  $('#model-question').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();guard(sendRecommendationMessage)}};
  $('#model-discussion-form').onsubmit=e=>{e.preventDefault();guard(sendRecommendationMessage)};
  $('#generate-model-recommendations').onclick=()=>guard(async()=>{
   if(modelPending)return;modelPending=true;modelError='';render();
   try{await followModelJob(await request('/api/model-recommendations',{revision:state.recommendation_chat.revision}))}
   catch(e){modelError=e.message}finally{modelPending=false;if(view==='discover')render()}
  });
  $('#reset-model-discussion').onclick=()=>guard(async()=>{if(modelPending)return;state.recommendation_chat=await request('/api/model-discussion-reset',{});modelDraft='';modelError='';render()});
  const list=$('#recommendation-messages');list.scrollTop=list.scrollHeight;
 }
}

function hotspotBrowsingDay(moment=Date.now()){
 const value=new Date(moment).getTime();
 if(!Number.isFinite(value))return '';
 return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value-8*60*60*1000));
}
function clearExpiredHotspots(){
 if(!state)return;
 const day=hotspotBrowsingDay(),entryDay=e=>e.day||hotspotBrowsingDay(e.created_at);
 state.hotspot_skips=(state.hotspot_skips||[]).filter(e=>entryDay(e)===day&&e.kind!=='article');
 for(const [id,e] of hotspotRestored)if(entryDay(e)!==day)hotspotRestored.delete(id);
}
let hotspotCalendarDay=hotspotBrowsingDay();
function checkHotspotDay(){const today=hotspotBrowsingDay();if(today===hotspotCalendarDay)return;hotspotCalendarDay=today;clearExpiredHotspots();if(state&&view==='hotspots')render()}
setInterval(checkHotspotDay,30000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)checkHotspotDay()});
