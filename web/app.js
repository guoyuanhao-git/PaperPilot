let state, view = 'library', selected = null, busy = false, draftProvider = null, crop = null;
const $ = s => document.querySelector(s);
const separateReader=new URLSearchParams(location.search).has('paper');
const analysisObservers=new Map(),analysisSubmitting=new Set();
function updateWeekday(now=new Date()){
 const label=$('#today-weekday');if(!label)return;
 label.textContent=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',weekday:'long'}).format(now);
 label.dateTime=now.toISOString();
 label.title=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'full'}).format(now);
}
updateWeekday();
setInterval(updateWeekday,60000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)updateWeekday()});
const notesDrafts = new Map();
const chatDrafts=new Map(), chatPending=new Map(), chatErrors=new Map();
let paperChatOpen=false, sidebarCollapsed=false;
try{sidebarCollapsed=localStorage.getItem('paperpilot-sidebar-collapsed')==='true'}catch{}
function applySidebar(){
 document.body.classList.toggle('sidebar-collapsed',sidebarCollapsed);
 const button=$('#sidebar-toggle');button.setAttribute('aria-expanded',String(!sidebarCollapsed));
 button.querySelector('.sidebar-chevron').setAttribute('d',sidebarCollapsed?'M13 9l3 3-3 3':'M16 9l-3 3 3 3');
 button.setAttribute('aria-label',sidebarCollapsed?'展开导航栏':'收起导航栏');button.title=button.getAttribute('aria-label');
 $('.sidebar').inert=sidebarCollapsed;
}
function togglePaperChat(open){
 const anchor=ReadingChatEntry.capture($('.reading-column'),paperChatOpen);
 paperChatOpen=open;
 if(open)sidebarCollapsed=true;else{try{sidebarCollapsed=localStorage.getItem('paperpilot-sidebar-collapsed')==='true'}catch{sidebarCollapsed=false}}
 render();
 // Cancel the old layout's delayed image correction before transferring position.
 ViewContinuity.capture($('#app'));
 ReadingChatEntry.restore($('.reading-column'),anchor,open);
 if(open){$('#chatmessages').scrollTop=$('#chatmessages').scrollHeight;$('#question').focus({preventScroll:true})}
 ViewContinuity.settleImages($('#app'),ViewContinuity.capture($('#app')));
}
function messageAuthor(role,name){
 const icon=ChatView.authorIcon(role,state.profile?.gender);
 const avatar=icon!=='saixiaoxi'?`<span class="author-icon avatar-portrait" aria-hidden="true"><img src="/icons/${icon}-approved-front.png" width="56" height="56" alt="" decoding="async"></span>`:`<span class="author-icon avatar-sprite avatar-${icon}" aria-hidden="true"></span>`;
 return `<span class="message-author">${avatar}<span>${role==='user'?esc(name):'助手'}</span></span>`;
}
function paperChat(p){
 const pending=chatPending.get(p.id),error=chatErrors.get(p.id),displayName=state.profile?.display_name?.trim()||'我';
 return `<aside class="paper-chat" aria-label="和助手聊论文"><header class="paper-chat-header"><div><h2>和助手聊论文</h2><span class="small muted">${esc(names[state.settings.provider])} · 当前论文</span></div><button id="close-paper-chat" class="iconbtn" aria-label="关闭论文交流">✕</button></header>
 <div class="chatmessages" id="chatmessages" role="log" aria-label="论文对话记录" tabindex="0">${p.messages.map(m=>`<div class="message ${m.role}">${messageAuthor(m.role,displayName)}<div class="message-body">${m.role==='assistant'?ChatView.render(m.content,(latex,display)=>window.katex?katex.renderToString(latex,{throwOnError:false,displayMode:display,trust:false}):esc(latex)):esc(m.content)}</div>${m.role==='assistant'?`<small>${esc(names[m.provider]||'历史接入')} · ${esc(m.model||'')}</small>`:''}</div>`).join('')}${pending?`<div class="message user">${messageAuthor('user',displayName)}<div>${esc(pending.question)}</div></div><div class="message assistant pending" role="status"><span class="spinner"></span> ${pending.stopping?'正在停止回答…':'正在阅读论文并组织回答…'}</div>`:!p.messages.length?'<div class="emptychat"><h3>从一个问题开始</h3><p>这篇论文的关键假设是什么？<br>这个公式在方法中起什么作用？<br>如何把它用于我的研究？</p></div>':''}</div>
 <form id="paper-chat-form" class="chat-composer">${error?`<p class="error" role="alert">${esc(error)}<br>问题已保留，可以重新发送。</p>`:''}<textarea id="question" class="chatinput" rows="3" maxlength="6000" aria-label="论文问题" placeholder="围绕这篇论文，继续追问…">${esc(chatDrafts.get(p.id)||'')}</textarea><div class="composer-actions"><span class="small muted">Enter 发送 · Shift + Enter 换行</span>${pending?`<button id="stop-paper-answer" type="button" class="secondary" ${pending.stopping?'disabled':''}>${pending.stopping?'正在停止…':'■ 停止并编辑'}</button>`:'<button id="ask" type="submit" class="primary">发送 ↑</button>'}</div></form></aside>`;
}
async function refreshPaperMessages(id,pending){
 const fresh=await request('/api/bootstrap?'+new URLSearchParams({knowledge_mainline:knowledgeMainline}));
 if(pending&&chatPending.get(id)!==pending)return;
 state.papers=fresh.papers;
 if(selected?.id===id)selected=state.papers.find(p=>p.id===id)||selected;
}
function restorePaperQuestion(id,question){
 const draft=chatDrafts.get(id)||'';
 chatDrafts.set(id,!draft||draft===question?question:question+'\n\n'+draft);
}
async function sendPaperMessage(){
 const id=selected.id,q=(chatDrafts.get(id)||'').trim();
 if(!q||chatPending.has(id))return;
 const pending={question:q,stopping:false};
 chatPending.set(id,pending);chatErrors.delete(id);chatDrafts.delete(id);
 pending.ready=request('/api/chat',{id,question:q});
 render();$('#question')?.focus({preventScroll:true});
 await followPaperMessage(id,pending);
}
async function followPaperMessage(id,pending){
 const q=pending.question;pending.observing=true;
 try{
  let job=await pending.ready;
  while(chatPending.get(id)===pending){
   if(pending.stopping){await new Promise(r=>setTimeout(r,100));continue}
   if(!['queued','running'].includes(job.status))break;
   await new Promise(r=>setTimeout(r,1200));
   if(chatPending.get(id)!==pending)return;
   if(pending.stopping)continue;
   job=await request('/api/job/'+job.id);
  }
  if(chatPending.get(id)!==pending)return;
  if(job.status==='cancelled'){restorePaperQuestion(id,q);return}
  if(job.status!=='completed')throw Error(job.error||'回答未完成');
  await refreshPaperMessages(id,pending);
 }catch(e){
  if(chatPending.get(id)===pending&&!pending.stopping){chatErrors.set(id,e.message);restorePaperQuestion(id,q)}
 }finally{
  pending.observing=false;
  if(chatPending.get(id)===pending&&!pending.stopping){chatPending.delete(id);if(view==='paper'&&selected?.id===id)render()}
 }
}
async function stopPaperMessage(){
 const id=selected.id,pending=chatPending.get(id);
 if(!pending||pending.stopping)return;
 pending.stopping=true;chatErrors.delete(id);render();
 try{
  let job;
  try{job=await pending.ready}catch(error){
   if(chatPending.get(id)===pending){restorePaperQuestion(id,pending.question);chatPending.delete(id);chatErrors.set(id,'未能确认请求是否提交成功，请刷新查看任务状态。')}
   return;
  }
  const result=await request('/api/chat-cancel',{job_id:job.id});
  if(chatPending.get(id)!==pending)return;
  if(result.status==='completed')await refreshPaperMessages(id,pending);
  restorePaperQuestion(id,pending.question);chatPending.delete(id);
  toast(result.status==='completed'?'回答已在停止前完成，原问题已放回输入框':'已停止回答，可以修改后重新发送');
 }catch(error){pending.stopping=false;chatErrors.set(id,'停止未成功：'+error.message);if(!pending.observing&&chatPending.get(id)===pending)void followPaperMessage(id,pending)}
 finally{
  if(view==='paper'&&selected?.id===id){render();$('#question')?.focus({preventScroll:true})}
 }
}

let deleting = null, libraryTab='reading';
const names = {codex:'Codex 订阅',deepseek:'DeepSeek API'};
const readingScopes=new Map(), readingModes=new Map(), readingOutlines=new Map(), editingOutlines=new Set();
const defaultReadingOutline=['动机','方法','实验','结论'];
const surveyReadingOutline=['领域问题','分类框架','技术路线','对比与评测','挑战与展望'];
function paperType(p){return p.paper_type&&p.paper_type!=='auto'?p.paper_type:(p.paper_type_detection?.type||'research')}
function defaultOutline(p){return paperType(p)==='survey'?surveyReadingOutline:defaultReadingOutline}
function outlineKey(p){return p.id+':'+paperType(p)}
let profileDraft=null, profileDirty=false, discoveryDraft=null, displayDraft=null;
let searchResult=null, dailyLoading=false, dailyError='';
let hfDays='1', hfResult=null, hfLoading=false, hfError='', hfOnlyRelevant=false;

let discoveryMode='filter', titleQuery='', titleResult=null, titleLoading=false, titleError='', titleProgress='';
let cardRefs=[];
const abstractLanguages=new Map(), abstractOpen=new Set(), abstractPending=new Map(), abstractErrors=new Map();
let hotspotDay=0, hotspotTab='articles', dailyByDay={}, modelDraft='', modelPending=false, modelQuestion='', modelError='';
const labels = {knowledge:'知识库',library:'论文库',hotspots:'热点发现',discover:'论文检索',profile:'研究档案',settings:'设置',conferences:'会议日程',paper:'论文阅读'};
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const date = value => value ? new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}) : '';
function math(latex){try{return window.katex ? katex.renderToString(latex,{throwOnError:false,displayMode:true,trust:false}) : esc(latex)}catch{return esc(latex)}}
function toast(text,error=false){$('#toast').textContent=text;$('#toast').classList.toggle('error',error);$('#toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('#toast').hidden=true,error?12000:5000)}
function accountHeaders(){const a=state?.accounts;return a?.enabled?{'X-PaperPilot-User':a.active||'','X-PaperPilot-Revision':a.revision}:{};}
function scopedFile(url){if(!url?.startsWith('/files/')||!state?.accounts?.enabled)return url;const u=new URL(url,location.origin);u.searchParams.set('user',state.accounts.active);u.searchParams.set('session',state.accounts.revision);return u.pathname+u.search;}
function accountReload(){notesDrafts.clear();chatDrafts.clear();profileDirty=false;document.querySelectorAll('dialog[open]').forEach(d=>d.close());$('#app').replaceChildren();location.reload();}
async function request(path,body,raw=false,headers={},retry=true){
 const response=await fetch(path,{method:body===undefined?'GET':'POST',headers:{...accountHeaders(),...(body===undefined?{}:{'X-PaperPilot-Token':state.token,...(raw?{}:{'Content-Type':'application/json'})}),...headers},...(body===undefined?{}:{body:raw?body:JSON.stringify(body)})});
 const result=await response.json();
 if(result.account_changed){accountReload();throw Error('用户已切换，正在刷新');}
 if(response.status===403&&result.error==='会话已失效，请刷新页面'&&retry){
  const fresh=await (await fetch('/api/bootstrap')).json();
  if(state?.accounts?.enabled&&(fresh.accounts?.active!==state.accounts.active||fresh.accounts?.revision!==state.accounts.revision)){accountReload();throw Error('用户会话已更新');}
  state.token=fresh.token;return request(path,body,raw,headers,false);
 }
 if(!response.ok)throw Error(result.error||'请求失败');return result;
}
let navigationRevision=0, renderedPageKey='';
function pageKey(){return JSON.stringify([state?.accounts?.revision,view,view==='paper'?selected?.id:null])}
function navigationContext(){return {revision:navigationRevision,key:pageKey(),mode:discoveryMode,mainline:knowledgeMainline,scope:knowledgeScope}}
function stillAt(context){return context.revision===navigationRevision&&context.key===pageKey()&&(view!=='discover'||context.mode===discoveryMode)&&(view!=='knowledge'||(context.mainline===knowledgeMainline&&context.scope===knowledgeScope))}
function acceptPaperUpdate(paper){
 const index=state.papers.findIndex(p=>p.id===paper.id);
 if(index>=0)state.papers[index]=paper;
 if(selected?.id===paper.id)selected=paper;
 return paper;
}
async function reload(renderPage=true){
 const requestedMainline=knowledgeMainline;
 const fresh=await request('/api/bootstrap?'+new URLSearchParams({knowledge_mainline:requestedMainline}));
 if(state?.accounts?.enabled&&(fresh.accounts?.active!==state.accounts.active||fresh.accounts?.revision!==state.accounts.revision)){accountReload();return;}
 if(requestedMainline!==knowledgeMainline)fresh.knowledge=state.knowledge;
 else knowledgeMainline=fresh.knowledge?.mainline_key||'';
 state=fresh;$('#provider-badge').textContent=names[state.settings?.provider]||'选择模型接入';
 if(selected)selected=state.papers?.find(p=>p.id===selected.id)||null;if(renderPage)render();
}
function head(eyebrow,title,subtitle,action=''){return `<div class="pagehead"><div><div class="eyebrow">${eyebrow}</div><h1>${title}</h1><p class="muted">${subtitle}</p></div>${action}</div>`}
function setView(next){navigationRevision++;if(paperChatOpen){paperChatOpen=false;try{sidebarCollapsed=localStorage.getItem('paperpilot-sidebar-collapsed')==='true'}catch{sidebarCollapsed=false}}view=next;history.replaceState(null,'',location.pathname);draftProvider=null;render();window.scrollTo(0,0);if(next==='hotspots')enterHotspots();if(next==='knowledge')guard(reload)}
function render(continuityOverride){
 if(!state)return;
 const retainedConference=view==='conferences'&&renderedPageKey===pageKey()?$('#conference-root'):null;
 if(!retainedConference)disconnectConference();
 ReadingChatEntry.disconnect();
 const continuity=renderedPageKey===pageKey()?(continuityOverride||ViewContinuity.capture($('#app'))):null;
 prepareKnowledgeRender();
 const account=state.accounts?.users.find(u=>u.id===state.accounts.active);
 $('#manage-users').textContent=account?account.name+' ▾':'创建用户';
 if(state.accounts?.enabled&&!account){$('nav').inert=true;$('#mainline-title').textContent='填写你的研究主线';$('#app').innerHTML=head('WELCOME TO PAPERPILOT','创建你的科研工作区','论文、研究档案与模型记忆按用户独立保存。')+'<section class="panel onboarding"><h2>第一次使用</h2><p class="muted">创建用户后，选择 Codex 订阅或配置自己的 DeepSeek API Key。</p><button id="first-user" class="primary">创建用户</button></section>';$('#first-user').onclick=openUsers;return;}
 $('nav').inert=false;
 applyWorkspaceNavigation();
 const questionFocused=document.activeElement?.id==='question',selectionStart=$('#question')?.selectionStart,selectionEnd=$('#question')?.selectionEnd;
 const readingScroll=$('.reading-column')?.scrollTop||0,chat=$('#chatmessages');
 const chatScroll=chat?.scrollTop||0,chatBottom=!chat||chat.scrollHeight-chat.scrollTop-chat.clientHeight<100;
 document.body.classList.toggle('separate-reader',separateReader);
 if(separateReader){const route=ReaderState.route(location.search,state.accounts?.active,state.papers||[]);if(route?.error){document.title='论文不可用 · PaperPilot';$('#app').innerHTML=head('PAPERPILOT','论文不可用',esc(route.error),'<a class="secondary" href="/">返回工作台</a>');return}}
 document.title=view==='paper'&&selected?LibraryView.title(selected)+' · PaperPilot':'PaperPilot · 个人科研助手';
 document.body.classList.toggle('paper-discussion',view==='paper'&&paperChatOpen);applySidebar();
 const mainlineTitles=(state.profile?.mainlines||[]).map(line=>line.title).filter(Boolean);
 $('#mainline-more').hidden=mainlineTitles.length<=2;$('#mainline-more').textContent=`还有 ${Math.max(0,mainlineTitles.length-2)} 条主线 ↗`;
 $('#mainline-title').textContent=mainlineTitles.length?mainlineTitles.slice(0,2).map((title,i)=>mainlineTitles.length>1?`${i+1}. ${title}`:title).join('\n'):state.profile?.mainline||'填写你的研究主线';
 if(selected){const index=state.papers.findIndex(p=>p.id===selected.id);if(index>=0)state.papers[index]=selected}
 $('nav').querySelectorAll('button').forEach(b=>b.classList.toggle('active',b.dataset.view===(view==='paper'?'library':view)));
 $('#breadcrumb').textContent=labels[view];
 const renderer={conferences:conferencesView,knowledge:knowledge,library:library,hotspots:hotspots,discover:discover,profile:profile,settings:settings,paper:paper};
 $('#app').innerHTML=renderer[view]();if(retainedConference)$('#conference-root')?.replaceWith(retainedConference);ViewContinuity.restoreContent($('#app'),continuity);bind();ReaderSplit.connect(paperChatOpen&&view==='paper'?$('.workspace'):null,state.accounts?.active);ViewContinuity.restorePosition($('#app'),continuity);ViewContinuity.settleImages($('#app'),continuity);ReadingChatEntry.connect($('#open-paper-chat'),$('#floating-paper-chat'),()=>togglePaperChat(true));renderedPageKey=pageKey();try{ReaderState.save(sessionStorage,state.accounts?.active,view,selected?.id)}catch{}if(paperChatOpen&&view==='paper'){$('.reading-column').scrollTop=readingScroll;const chat=$('#chatmessages');chat.scrollTop=chatBottom?chat.scrollHeight:chatScroll;if(questionFocused){$('#question').focus({preventScroll:true});$('#question').setSelectionRange(selectionStart,selectionEnd)}}if(busy)$('#app').querySelectorAll('[data-task]').forEach(b=>b.disabled=true);
}
function newPaperPage(p){return `<a class="textbtn small new-paper-page" href="${esc(ReaderState.link(p.id,state.accounts?.active))}" target="_blank" rel="noopener" title="在新页面阅读" aria-label="在新页面阅读 ${esc(p.title)}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 4h6v6m0-6L10 14M10 4H5a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5"/></svg><span>新页面阅读</span></a>`}
function readerBack(){return separateReader?'<a class="textbtn backbtn" href="/" target="_blank" rel="noopener">↗ 打开工作台</a>':'<button id="back" class="textbtn backbtn">← 返回论文库</button>'}
function preferenceButtons(p){
 const selected=p.starred?'starred':p.liked?'liked':'none';
 const shapes={liked:'M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z',starred:'m12 3 2.8 5.7 6.3.9-4.5 4.4 1.1 6.2-5.7-3-5.7 3 1.1-6.2-4.5-4.4 6.3-.9Z'};
 return `<span class="paper-preference" role="group" aria-label="论文偏好">${[['liked','喜欢'],['starred','收藏']].map(([key,label])=>`<button type="button" class="preference-button preference-${key}" data-preference="${key}" data-preference-paper="${p.id}" aria-pressed="${selected===key}" aria-label="${selected===key?'取消':''}${label}论文" title="${selected===key?'取消':selected!=='none'?'改为':''}${label}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="${shapes[key]}"/></svg></button>`).join('')}</span>`;
}
function library(){
 const counts=LibraryView.counts(state.papers),papers=LibraryView.rows(state.papers,libraryTab),stats=state.reading_stats||{today:0,week:0};
 return head('YOUR RESEARCH LIBRARY','为好想法留一个位置','上传论文，读懂动机与方法，再判断它与你的研究有什么联系。',`<div class="reading-stats" aria-label="阅读统计"><span>今日已读<strong>${stats.today}<small> 篇</small></strong></span><span title="每周日开始计算">本周已读<strong>${stats.week}<small> 篇</small></strong></span></div>`)+`
 <div class="panel import-panel"><div><label class="dropzone"><input id="upload" type="file" accept="application/pdf"><strong>＋ 上传论文 PDF</strong><small>保留原文 · 提取文字与图表 · 最大 40 MB</small></label></div><div class="link-import"><label for="paper-url">arXiv 链接(ID)</label><div class="fieldrow"><input id="paper-url" placeholder="例如 2603.16666 或完整 arXiv 链接"><button id="import-link" class="secondary" data-task>导入</button></div></div></div>
 <section class="panel favorite-import"><div><h3>从待读清单导入</h3></div><button id="pick-favorite" class="secondary" data-task>选择待读论文 · ${(state.favorites||[]).length} 篇</button></section>
 <div class="library-tabs" role="tablist" aria-label="论文分类">${[['reading','在读论文'],['read','已读论文'],['liked','我的喜欢'],['starred','我的收藏']].map(([key,label])=>`<button id="library-tab-${key}" role="tab" aria-selected="${libraryTab===key}" aria-controls="library-list" class="${libraryTab===key?'active':''}" data-library-tab="${key}">${key==='starred'?'<span class="tab-star" aria-hidden="true">★</span> ':key==='liked'?'<span class="tab-heart" aria-hidden="true">♥</span> ':''}${label}<span class="count">${counts[key]} 篇</span></button>`).join('')}</div>
 <div id="library-list" role="tabpanel" aria-labelledby="library-tab-${libraryTab}">${papers.length?`<div class="paper-grid">${papers.map(p=>libraryTab!=='reading'?compactPaper(p):`<article tabindex="0" class="paper-card" data-paper="${p.id}"><div class="row" style="justify-content:space-between"><span class="tag ${p.is_reference?'reference':''}">${p.is_reference?'风格参考读本':p.report?'已有中文解读':'等待阅读'}</span><div class="row">${preferenceButtons(p)}<button class="textbtn danger small" data-delete="${p.id}" aria-label="移除 ${esc(p.title)}">移除</button></div></div><h3>${esc(LibraryView.title(p))}</h3><p class="muted small">${p.page_count} 页 · ${p.figures.filter(f=>!f.duplicate_of).length} 个图表候选${p.notes?' · 有个人思考':''}${p.feedback?' · 已有偏好反馈':''}</p><div class="card-foot"><span class="reading-status ${LibraryView.done(p)?'is-complete':''}">${esc(p.read_status)}</span>${newPaperPage(p)}</div></article>`).join('')}</div>`:
 `<div class="empty"><div class="empty-icon">${libraryTab==='starred'?'☆':libraryTab==='liked'?'♡':'∿'}</div><h3>${({reading:'这里还没有在读论文',read:'读完一篇，留下一份积累',liked:'留住让你喜欢的论文',starred:'收藏值得反复回看的论文'})[libraryTab]}</h3><p>${({reading:'上传 PDF、输入 arXiv ID，或从待读清单导入。',read:'在解读末尾点击“阅读完毕”，论文就会出现在这里。',liked:'点击爱心，保存欣赏的思想、风格或方法。喜欢与收藏可随时切换。',starred:'点击星星，保留长期核心参考。再次点击可取消标记。'})[libraryTab]}</p></div>`}</div>${historyView()}`
}
function finishReading(p){return `<div class="reading-finish"><span class="reading-status ${LibraryView.done(p)?'is-complete':''}">${esc(p.read_status)}</span><button id="finish-reading" class="primary" ${LibraryView.done(p)?'disabled':''}>${LibraryView.done(p)?'已完成阅读 ✓':'阅读完毕'}</button></div>`}

function reportSectionView(s,p,figure,finish=false){
 const heading=s.key==='abstract'?'':s.key==='paper_info'?'<h2><button type="button" id="refresh-paper-info" class="metadata-action metadata-heading" data-task title="点击更新论文相关信息" aria-label="论文相关：点击更新">论文相关</button></h2>':`<h2>${esc(ReportView.references(s.title))}</h2>`;
 const content=s.key==='paper_info'?ReportView.sectionBody(s,true):ReportView.sectionContent(s,figure,e=>`<div class="equation"><div class="math">${math(e.latex)}</div>${ReportView.equationNotes(e,p.report.mode).map(t=>`<p>${esc(ReportView.references(t))}</p>`).join('')}</div>`);
 return `<section data-view-anchor="report-${esc(s.key)}" class="section report-section ${s.key==='abstract'?'abstract-section':''}" style="--accent:${ReportView.theme(s)[1]};--tint:${ReportView.theme(s)[2]}">${heading}${content}${finish?finishReading(p):''}</section>`;
}

function savedOutline(p){return p.reading_outlines?.[paperType(p)]||(!p.reading_outlines&&paperType(p)==='research'?(p.reading_outline||p.report?.reading_outline):null)||defaultOutline(p)}
function outlineDraft(p){if(!readingOutlines.has(outlineKey(p)))readingOutlines.set(outlineKey(p),[...savedOutline(p)]);return readingOutlines.get(outlineKey(p))}
function outlineEditor(p){
 if(!editingOutlines.has(p.id))return `<div class="outline-editor"><div class="outline-heading"><strong>叙述线</strong><button id="edit-outline" class="textbtn small" type="button" aria-expanded="false">修改</button></div><div class="outline-summary" aria-label="已保存的叙述线">${savedOutline(p).map(esc).join(' <span aria-hidden="true">→</span> ')}</div></div>`;
 const steps=outlineDraft(p),dirty=JSON.stringify(steps)!==JSON.stringify(savedOutline(p));
 return `<div class="outline-editor"><div class="outline-heading"><strong>叙述线</strong><button id="reset-outline" class="textbtn small" type="button">恢复默认</button></div><div class="outline-flow">${steps.map((text,i)=>`<div class="outline-step">${i?'<span class="outline-arrow" aria-hidden="true">→</span>':''}<div class="outline-field"><textarea data-outline-step="${i}" aria-label="叙述步骤 ${i+1}" maxlength="80" rows="1" placeholder="词或一句话">${esc(text)}</textarea><button type="button" class="outline-remove" data-outline-remove="${i}" ${steps.length===1?'disabled':''} aria-label="删除步骤 ${i+1}">×</button></div></div>`).join('')}</div><div class="outline-actions"><button id="add-outline" class="textbtn small" type="button" ${steps.length>=8?'disabled':''}>＋ 添加步骤</button><div class="outline-save-actions"><button id="cancel-outline" class="textbtn small" type="button">取消</button><button id="save-outline" class="primary" type="button">保存</button></div></div><p class="hint outline-status" id="outline-status">${dirty?'有修改 · 生成时一并保存':'用于当前论文 · 最多 8 步，每步 80 字'}</p></div>`;
}
async function saveReadingOutline(){
 const id=selected.id,key=outlineKey(selected),kind=paperType(selected),steps=[...outlineDraft(selected)];
 const updated=await request('/api/paper-update',{id,reading_outline:steps,reading_outline_type:kind});
 const index=state.papers.findIndex(p=>p.id===id);if(index>=0)state.papers[index]=updated;
 if(selected?.id===id)selected=updated;
 if(JSON.stringify(readingOutlines.get(key))===JSON.stringify(steps)){readingOutlines.set(key,[...updated.reading_outlines[kind]]);editingOutlines.delete(id)}
 render();toast('叙述线已保存，下次生成时使用');
}

function paperTypeControl(p){
 const chosen=paperType(p);
 return `<label class="paper-type-control">论文类型<select id="paper-type" class="wideinput" ${busy?'disabled':''}>${[['research','研究论文'],['survey','综述论文']].map(([value,label])=>`<option value="${value}" ${chosen===value?'selected':''}>${label}</option>`).join('')}</select></label>`;
}
function presentationPanel(p){
 const latest=(p.exports||[]).filter(e=>e.format==='pptx').at(-1);
 const customStyle=(state.ppt_samples||[]).some(s=>s.enabled);
 return `<section class="panel teaching-panel"><h3>讲解 PPT</h3><p class="hint">${paperType(p)==='survey'?'先建立领域地图，再展开技术路线与比较。':'直接依据原论文备课，讲清概念、方法与证据。'}有阅读报告时作为辅助，无需先生成精读。</p><div class="style-sample-entry"><span>讲解风格 · ${customStyle?'我的范例':'内置'}</span><button id="manage-ppt-samples" class="textbtn small" type="button">${(state.ppt_samples||[]).length?`管理 · ${state.ppt_samples.filter(s=>s.enabled).length} 份启用`:'添加范例'}</button></div><button id="generate-presentation" class="secondary wideinput" data-task>${latest?'重新生成讲解 PPT':'生成讲解 PPT'}</button><p class="hint">调用当前模型的精读配置，独立编写幻灯片与讲稿。</p>${latest?`<a class="small export-download" href="${scopedFile(latest.url)}">下载讲解 PPT ↗</a>`:''}</section>`;
}

function latestReadingTask(p){return state.analysis_jobs?.[p.id]||(state.jobs||[]).find(j=>j.kind==='analysis'&&j.paper_id===p.id)}
function readingTaskStatus(p){
 const job=latestReadingTask(p);
 if(!job)return '';
 if(job.monitor_error)return `<div class="reading-task-error" role="status"><strong>进度连接中断</strong><p>后台任务可能仍在运行。刷新页面可重新连接进度，请勿重复提交。</p></div>`;
 if(['running','queued'].includes(job.status))return `<div class="reading-task-progress" role="status"><span class="spinner"></span><div><strong>${job.status==='queued'?'等待生成':'正在生成解读'}</strong><p>${esc(job.progress||'准备中')}</p></div></div>`;
 if(job.status==='cancelled')return '<p class="hint" role="status">已停止生成，可修改阅读方式后重新生成。原有报告保留。</p>';
 if(job.status!=='failed')return '';
 return `<div class="reading-task-error" role="status"><strong>上次解读未完成</strong>${job.last_stage?`<p>停止于：${esc(job.last_stage)}</p>`:''}<p>${esc(job.error||'生成中断，请重试')}</p><p class="hint">${p.report?'已保留原报告。':'尚未保存完整报告。'}重试会复用材料与配置未变、已通过检查的步骤。</p></div>`;
}

function paper(){
 if(!selected){view='library';return library()}const p=selected,r=p.report;if(p.metadata_only)return metadataPaper(p);
 const failed=latestReadingTask(p)?.status==='failed';
 if(failed){const job=latestReadingTask(p);if(job.mode&&!readingModes.has(p.id))readingModes.set(p.id,job.mode);if(job.figure_scope&&!readingScopes.has(p.id))readingScopes.set(p.id,job.figure_scope)}
 const figures=r?.figures||[],figuresById=new Map(figures.map(f=>[f.id,f])),sections=r?ReportView.sections(r):[];const figure=id=>{const f=figuresById.get(id);return f?`<figure class="reportfigure"><img src="${scopedFile(ReaderState.figureUrl(p.id,f,true))}" alt="${esc(ReportView.caption(f))}"><figcaption>${esc(ReportView.caption(f))}</figcaption></figure>`:''};
 const used=new Set(r?.sections.flatMap(s=>s.figures)||[]),remainingFigures=figures.filter(f=>!used.has(f.id));
 return readerBack()+head(p.is_reference?'STYLE REFERENCE':'PAPER READING',esc(LibraryView.title(p)),`${p.page_count} 页 · ${p.is_reference?'用户提供的教材式学习稿':'已提取论文文字'} · ${p.pdf_released?'<span class="small muted">原文已释放</span> · <button class="textbtn small" data-storage="'+p.id+'">恢复原文</button>':`<a target="_blank" rel="noopener" href="${scopedFile(`/files/${p.id}/source.pdf`)}">打开原文 PDF ↗</a>`}`, `<div class="row paper-actions">${separateReader?'':newPaperPage(p)}${preferenceButtons(p)}<button id="open-paper-chat" class="primary" aria-expanded="${paperChatOpen}">交流</button>${paperMore(p)}</div>`)+`
 <div class="workspace"><div class="reading-column"${paperChatOpen?' data-scroll-key="paper-reading"':''}><article class="reading">${r?`<div class="row"><span class="tag">${({overview:'中文速览',detailed:'中文精读',deep:'数学精读'})[r.mode]||'中文速览'}${r.paper_type==='survey'?' · 综述':''}</span><span class="small muted">${names[r.provider]||'历史接入'} · ${esc(r.model||'')} · ${date(r.generated_at)}</span></div><p class="lead" style="margin-top:22px">${esc(ReportView.references(r.summary))}</p><div class="meta">${esc(r.scope)}<br>${r.vision?`附图 ${r.image_count} 张，图文理解取决于所用模型`:'未启用图片理解，图表解释依据文字和图注'}${p.is_reference?'<br>风格参考学习稿，非原始论文':''}</div>${r.abstract?.original?`<details class="source-caption"><summary>查看原始摘要</summary><p>${esc(r.abstract.original)}</p></details>`:''}${r.figure_coverage?`<details class="source-caption"><summary>图表阅读清单 · 分析 ${r.figure_coverage.length} 项 / 收录 ${r.figures.length} 项</summary>${r.figure_coverage.map(f=>`<p>${esc(ReportView.references(f.label))} · ${f.included?'已收录':'未收录'}：${esc(f.reason)}</p>`).join('')}</details>`:''}${sections.filter(s=>s.key!=='relevance').map(s=>reportSectionView(s,p,figure)).join('')}${remainingFigures.length?`<section class="section"><h2>其他所选原文图表</h2><p class="muted small">模型未将这些图分配到章节，供对照原文。</p>${remainingFigures.map(f=>figure(f.id)).join('')}</section>`:''}${r.sections.some(s=>s.key==='relevance')?sections.filter(s=>s.key==='relevance').map(s=>reportSectionView(s,p,figure,true)).join(''):`<section class="section"><h2>助手判断</h2>${finishReading(p)}</section>`}`:
 ` ${p.abstract_record?.original||p.abstract?`<section class="section abstract-section"><p>${esc(p.abstract_record?.translation||p.abstract_record?.original||p.abstract)}</p>${p.abstract_record?.translation?`<details class="source-caption"><summary>查看原始摘要</summary><p>${esc(p.abstract_record.original)}</p></details>`:''}</section>`:''}<div class="empty-icon">∿</div><h2>先看懂这篇论文在解决什么</h2><p class="muted">右侧生成中文解读或讲解 PPT，也可以围绕具体问题直接提问。</p><div class="section"><h3>按自己的思路读论文</h3><p class="muted">在右侧编辑叙述线，用词或句子说明希望如何展开，再生成解读。</p></div>`}</article>
 <section class="panel personal-notes" data-view-anchor="personal-notes"><div class="row" style="justify-content:space-between"><h2>我的思考 / 评价</h2><span class="small muted" id="notes-status">${notesDrafts.has(p.id)?'尚未保存':p.notes_updated_at?'已保存 · '+date(p.notes_updated_at):'仅保存你的文字'}</span></div><p class="hint">可以记下亮点、疑问、复现思路，或为什么觉得这篇论文不值得继续读。不会混入模型解读或自动导出。</p><textarea id="personal-notes" rows="7" maxlength="20000" placeholder="我认为这篇论文最有价值 / 最薄弱的地方是…">${esc(notesDrafts.get(p.id)??p.notes??'')}</textarea><button id="save-notes" class="primary">保存我的思考</button></section></div>
 <aside class="toolcol">${identityFields(p)}<section class="panel">${paperTypeControl(p)}<h3>阅读方式</h3><select id="read-mode" class="wideinput"><option value="overview" ${(readingModes.get(p.id)||r?.mode||'overview')==='overview'?'selected':''}>中文速览 · 默认</option><option value="detailed" ${(readingModes.get(p.id)||r?.mode)==='detailed'?'selected':''}>中文精读 · 细致展开</option><option value="deep" ${(readingModes.get(p.id)||r?.mode)==='deep'?'selected':''}>数学精读 · 教材式</option></select><div class="style-sample-entry"><span>数学精读 · 参考例文</span><button id="manage-style-samples" class="textbtn small" type="button">${(state.style_samples||[]).length?`管理 · ${state.style_samples.filter(s=>s.enabled).length} 份启用`:'提供例文'}</button></div>${outlineEditor(p)}<label>图表阅读范围<select id="figure-scope"><option value="all" ${(readingScopes.get(p.id)||'all')==='all'?'selected':''}>全部图表 · 默认</option><option value="selected" ${readingScopes.get(p.id)==='selected'?'selected':''}>仅手动勾选的图表</option></select></label><p class="hint">研究论文讲清研究故事，综述论文梳理领域地图。速览与精读按叙述线展开，数学精读结合参考例文讲解。摘要、论文相关与助手判断独立保留。</p><div id="reading-task-status">${readingTaskStatus(p)}</div><button id="analyze" class="primary wideinput" ${analysisActive(p.id)?'disabled':''}>${analysisActive(p.id)?'生成中…':p.pdf_released?'恢复原文后生成解读':failed?'重试生成解读':r?'重新生成解读':'生成解读'}</button><button id="stop-analysis" class="textbtn wideinput" type="button" ${analysisActive(p.id)?'':'hidden'}>停止生成</button>${r?`<div class="report-tools"><button data-export="pdf" class="secondary" data-task>导出 PDF</button></div><p class="hint">PDF 保存当前解读，不额外调用模型。</p>${(p.exports||[]).filter(e=>e.format==='pdf').slice(-1).map(e=>`<a class="small export-download" href="${scopedFile(e.url)}">下载 PDF ↗</a>`).join('')}`:''}</section>
 ${presentationPanel(p)}
 ${p.pdf_released?`<section class="panel"><h3>原文图表</h3><p class="hint">报告中的图表已保留。恢复原文后可查看全部图表、调整裁剪。</p><button class="secondary" data-storage="${p.id}">恢复原文</button></section>`:` <section class="panel"><h3>原文图表 <span class="small muted">${readingScopes.get(p.id)==='selected'?`手动选择 ${p.figures.filter(f=>f.selected&&!f.duplicate_of).length} 张`:`全部 ${p.figures.filter(f=>!f.duplicate_of).length} 张待评估`}</span></h3><p class="hint">当前阅读范围为“${readingScopes.get(p.id)==='selected'?'仅手动勾选':'全部图表'}”。默认全部评估，由模型决定哪些值得放入速览；切换为“仅手动勾选”后可调整勾选。自动裁剪可手动修正。</p><div class="figlist" data-scroll-key="paper-figures">${p.figures.filter(f=>!f.duplicate_of).map(f=>`<div class="figitem" data-view-anchor="figure-${esc(f.id)}"><img loading="lazy" src="${scopedFile(ReaderState.figureUrl(p.id,f))}" alt="${esc(ReportView.caption(f))}"><label><input type="checkbox" data-figure="${f.id}" ${readingScopes.get(p.id)==='selected'?(f.selected?'checked':''):'checked disabled'}><p>第 ${f.page} 页 · ${esc(ReportView.caption(f))}</p></label><details class="source-caption"><summary>查看原文图注</summary>${esc(f.caption)}</details><button data-crop="${f.id}" class="textbtn small">调整裁剪 / 中文图注</button></div>`).join('')||'<p class="small muted">未检测到图注，可以手动添加。</p>'}</div><button id="add-figure" class="textbtn small">＋ 从原文页面添加图表</button>${readingScopes.get(p.id)==='selected'?'<button id="translate-captions" class="textbtn small" data-task>改写手动勾选图注</button>':''}<p class="hint">新解读会同时生成中文图注；切换为手动选择后，可单独改写勾选图注。手动裁剪和图注修改立即同步，下载文件需重新导出。</p></section>`}

 <section class="panel"><h3>阅读状态与推荐偏好</h3><div class="row"><span class="reading-status ${LibraryView.done(p)?'is-complete':''}">${esc(p.read_status)}</span>${LibraryView.done(p)?'<button id="start-reading" class="textbtn small">开始阅读</button>':''}</div><textarea id="feedback" class="wideinput" rows="3" placeholder="供后续推荐参考：喜欢或不喜欢什么，为什么？">${esc(p.feedback)}</textarea><button id="save-feedback" class="textbtn">保存反馈</button></section></aside>${paperChatOpen?'<div class="reader-divider" role="separator" tabindex="0" aria-orientation="vertical" aria-label="调整报告与交流宽度" title="拖动调整宽度 · 双击恢复默认"></div>'+paperChat(p):''}</div>`;
}
function historyView(){const entries=state.reading_history||[];return entries.length?`<details class="panel history-panel"><summary>仅保留的阅读记录 · ${entries.length} 篇</summary><p class="hint">没有保留 PDF、解读、对话或个人思考；偏好反馈仍可帮助后续推荐。</p>${entries.map(p=>`<div class="history-row"><div><strong>${esc(p.title)}</strong><p class="small muted">${esc(p.read_status)} · ${esc(p.feedback||'未留下偏好反馈')}</p></div><button class="textbtn danger small" data-forget="${p.id}">忘记记录</button></div>`).join('')}</details>`:''}
function openDelete(p){deleting=p;$('#delete-title').textContent=p.title;$('#delete-dialog input[value="keep"]').checked=true;$('#delete-dialog').showModal()}
let reasoningDraft=null,hotspotNewsDraft=null;
function readReasoningPolicy(){return {custom_enabled:$('#reasoning-custom-enabled').checked,overrides:Object.fromEntries([...document.querySelectorAll('[data-reasoning-group]')].filter(el=>el.value!=='recommended').map(el=>[el.dataset.reasoningGroup,el.value]))}}
function webSupplementSettings(c){
 const u=state.capabilities?.web_supplement_usage||{};
 return `<section class="advanced-section"><h3>联网补充</h3><label class="advanced-toggle-row"><span><span class="setting-label">DeepSeek Search / Fetch</span><small>仅补充标题搜索与失败的文章读取</small></span><input id="web-supplement-enabled" class="setting-switch" type="checkbox" role="switch" ${c.web_supplement_enabled?'checked':''}></label><p class="hint">使用当前用户的 DeepSeek Key；切换模型仍按此开关生效。成功请求约 ¥0.005 / 次，每日最多 60 次；缓存不重复计费。</p><small class="muted">今日 ${u.successful||0} 次成功 · 接口估算 ¥${Number(u.estimated_cny||0).toFixed(3)}${u.unknown?' · '+u.unknown+' 次费用待确认':''}（不含模型 token）</small></section>`;
}
function reasoningSettings(c){
 const groups=[['overview','论文速览','medium','快速理解研究故事'],['study','论文精读','high','精读报告与讲解 PPT'],['knowledge','知识图谱','medium','领域／主线图谱']];
 const policy=reasoningDraft||c.reasoning_policy||{custom_enabled:false,overrides:{}},labels={low:'轻量',medium:'标准',high:'深入'},provider=draftProvider||c.provider;
 const params=provider==='codex'?['low','medium','high']:['关闭','low','high'];
 const mapping=Object.values(labels).map((label,i)=>`<span>${label}<code>${params[i]}</code></span>`).join('');
 return `<details class="panel advanced-settings" id="reasoning-advanced"><summary>高级设置</summary><div class="advanced-body">${ModelSetupView.models(provider,c)}<section class="advanced-section"><div class="advanced-section-head"><h3>思考档位</h3><button id="reasoning-recommended" type="button" class="textbtn small" title="全部使用推荐配置">恢复推荐</button></div><label class="advanced-toggle-row"><span><span class="setting-label">自定义档位</span><small>关闭时使用推荐配置</small></span><input id="reasoning-custom-enabled" class="setting-switch" type="checkbox" role="switch" ${policy.custom_enabled?'checked':''}></label><div class="reasoning-settings">${groups.map(([id,label,level,description])=>`<label class="reasoning-row"><span><span class="setting-label">${label}</span><small>${description}</small></span><select aria-label="${label}档位" data-reasoning-group="${id}" data-recommended="${level}" ${!policy.custom_enabled?'disabled':''}><option value="recommended" ${!policy.overrides?.[id]?'selected':''}>推荐 · ${labels[level]}</option>${Object.entries(labels).map(([v,t])=>`<option value="${v}" ${policy.overrides?.[id]===v?'selected':''}>${t}</option>`).join('')}</select></label>`).join('')}</div><div class="reasoning-mapping">${mapping}</div></section><section class="advanced-section"><div class="advanced-section-head"><h3>论文材料</h3><button id="materials-recommended" type="button" class="textbtn small">恢复推荐</button></div><label class="advanced-toggle-row"><span><span class="setting-label">图表图片理解</span><small>推荐开启，结合原文图表理解论文</small></span><input id="vision" class="setting-switch" type="checkbox" role="switch" ${c.vision?'checked':''}></label><label class="reasoning-row"><span><span class="setting-label">文字上下文上限</span><small>推荐 100,000 字符</small></span><input id="context-chars" aria-label="文字上下文上限" type="number" min="10000" max="240000" step="1000" value="${c.context_chars}"></label></section><section class="advanced-section reasoning-managed"><h3>可选功能</h3><label class="advanced-toggle-row"><span><span class="setting-label">后台持续记忆</span><small>持续了解你的科研进展</small></span><input id="settings-memory-enabled" class="setting-switch" type="checkbox" role="switch" ${state.memory_status?.enabled?'checked':''}></label><label class="advanced-toggle-row"><span><span class="setting-label">领域动态</span><small>AI 初筛推文；关闭后仍可浏览 DailyPapers</small></span><input id="hotspot-news-enabled" class="setting-switch" type="checkbox" role="switch" ${(hotspotNewsDraft??c.hotspot_news_enabled)!==false?'checked':''}></label></section>${provider==='deepseek'?`${webSupplementSettings(c)}<section class="advanced-section" id="output-advanced"><h3>输出额度</h3><label class="advanced-toggle-row"><span><span class="setting-label">自动设置</span><small>按思考模式分配每次输出额度</small></span><input id="output-auto" class="setting-switch" type="checkbox" role="switch" ${c.output_tokens_auto?'checked':''}></label><label class="output-manual reasoning-row" id="output-manual" ${c.output_tokens_auto?'hidden':''}><span><span class="setting-label">每次输出上限</span><small>包含思考与最终答案，单位 token</small></span><input id="output-tokens" ${c.output_tokens_auto?'disabled':''} type="number" min="2000" max="131072" value="${c.output_tokens}"></label></section>`:''}</div></details>`;
}
function settings(){const c=state.settings,p=draftProvider||c.provider;
 return head('PREFERENCES','设置','')+`
 <div class="settings-grid"><section class="panel"><h2>模型接入</h2><div class="provider-options">${Object.keys(names).map(k=>`<button class="provider-option ${p===k?'selected':''}" data-provider="${k}">${k==='codex'?'Codex':'DeepSeek'}<small>${k==='codex'?'ChatGPT 订阅':'DeepSeek API'}</small></button>`).join('')}</div>
 ${ModelSetupView.card(p,state)}${ModelSetupView.manual(p,state)}
 ${reasoningSettings(c)}
 <div class="row"><button id="save-settings" class="primary">保存设置</button><button id="test-provider" class="secondary" data-task>保存并测试连接</button></div></section>
 <aside class="settings-aside">${workspaceSettings()}<section class="panel explain"><h3>接入与用量</h3><p><strong>Codex</strong><br>使用 ChatGPT 订阅额度，与 Codex 任务共享。</p><p><strong>DeepSeek</strong><br>使用 API Key，按 DeepSeek API 用量计费。</p><hr class="form-divider"><p>接入完成后可独立使用 PaperPilot，无需打开助手对话。</p></section></aside></div>`;
}
const profileGroups=[
 ['基本信息','你的学校、研究环境与当前阶段。',[['school','学校','例如：示例大学',200,1],['department','院系','例如：示例学院',120,1],['laboratory','实验室','例如：示例实验室',120,1],['stage','当前阶段 / 身份','例如：硕士一年级、博士生、工程师',120,1]]],
 ['教育背景与能力','帮助助手把解释放在适合你的知识起点。',[['education','教育经历','按时间填写学校、学位、专业、年份；也可以只写专业背景',3000,4],['skills','知识基础与技能','已掌握的理论、编程工具、熟悉的方法，以及还需要补的知识',3000,4]]],
 ['研究与工作','你关心什么，正在推进什么。',[['research_directions','研究方向','关注的领域、问题与边界',4000,4],['current_projects','当前课题与进展','正在做的项目、已完成的工作、遇到的瓶颈',4000,4],['goals','近期目标与现实约束','阶段目标、时间、算力、数据、阅读预算等',3000,4]]],
 ['论文品味与阅读习惯','用具体例子说明什么对你有价值。',[['paper_taste','论文品味','喜欢 / 不喜欢的论文及原因；哪些方向虽不喜欢但仍需追踪',4000,4],['reading_preferences','解读偏好','语言、长短、数学深度、图表、代码联系、速览或精读习惯',3000,4]]],
 ['个人陈述','写给助手读的一段自我介绍。你的动机、顾虑、工作方式、职业想法，都可以写在这里。',[['personal_statement','想让助手了解的我','不必写成正式文书，用自己的话说明即可',8000,7]]],
 ['研究主线','告诉助手当前最想解决的问题、工作的重点与下一步计划。它决定主线图谱的外围联系，也帮助推荐和解读把握重点。',[['mainline','主线标题','用一句短语概括当前主线',100,1],['mainline_detail','主线补充','当前重点、辅助方向或下一步',320,3]]],
];
function sourceLabel(id){const s=id==='embodied_daily'?{name:'具身日报'}:state.sources?.[id];return `${s?.icon?`<img class="source-icon" src="${esc(s.icon)}" alt="" aria-hidden="true">`:''}<span>${esc(s?.name||id)}</span>`}
function sourceOptions(chosen,cls){return Object.entries(state.sources||{}).filter(([id])=>['arxiv','huggingface','papers_cool'].includes(id)).map(([id])=>`<label class="source-choice"><input type="checkbox" class="${cls}" value="${id}" ${chosen.includes(id)?'checked':''}>${sourceLabel(id)}</label>`).join('')}
function sourceStates(run){return (run.source_status||[]).map(s=>`<div class="source-status ${s.ok?'':'error'}">${sourceLabel(s.source)} · ${Number.isInteger(s.articles)?s.articles+' 篇推文 / '+s.count+' 篇论文':s.ok?s.count+' 条候选':'未能读取'} · ${esc(s.message)}</div>`).join('')}
const profileListFields={research_directions:'research_direction_items',current_projects:'current_project_items'};
function profileListForm(key,label,placeholder,d){
 const itemKey=profileListFields[key],items=d[itemKey];
 return `<div class="profile-list-field"><div class="profile-list-head"><span>${label}</span><button type="button" class="textbtn small" data-add-profile-item="${key}" ${items.length>=5?'disabled':''} aria-label="添加${label}">＋ 添加</button></div><div class="profile-list-box" data-scroll-key="profile-${key}" role="group" aria-label="${label}">${items.map((text,i)=>`<div class="profile-list-row"><textarea rows="1" data-profile-list="${key}" data-profile-item="${i}" maxlength="4000" aria-label="${label} ${i+1}" placeholder="${esc(placeholder)}">${esc(text)}</textarea><button type="button" class="textbtn small" data-remove-profile-list="${key}" data-profile-item="${i}" aria-label="移除${label} ${i+1}">×</button></div>`).join('')}</div></div>`;
}
function syncProfileList(key){const values=profileDraft[profileListFields[key]];profileDraft[key]=values.map(v=>v.trim()).filter(Boolean).join('\n');profileDirty=true;$('#profile-save-status').textContent='有修改尚未保存';}
function mainlineForm(d){
 return `<div class="mainline-list">${d.mainlines.map((line,i)=>`<div class="mainline-entry"><div class="mainline-entry-head"><strong>主线 ${i+1}</strong>${d.mainlines.length>1?`<button class="textbtn danger small" data-remove-mainline="${i}" aria-label="移除主线 ${i+1}">移除</button>`:''}</div><label>主线标题<input data-mainline-index="${i}" data-mainline-field="title" maxlength="100" value="${esc(line.title)}" placeholder="用一句短语概括这条主线"></label><label>主线补充 <span class="muted small">最多 320 字</span><textarea data-mainline-index="${i}" data-mainline-field="detail" maxlength="320" rows="3" placeholder="当前重点、辅助方向或下一步">${esc(line.detail)}</textarea></label></div>`).join('')}</div>${d.mainlines.length<3?'<button id="add-mainline" class="secondary small">＋ 添加研究主线</button>':''}`;
}
function syncMainlineDraft(){profileDraft.mainline=profileDraft.mainlines[0]?.title||'';profileDraft.mainline_detail=profileDraft.mainlines[0]?.detail||'';profileDirty=true;}
function profile(){
 if(!profileDraft)profileDraft=JSON.parse(JSON.stringify(state.profile));if(!profileDraft.mainlines?.length)profileDraft.mainlines=[{title:profileDraft.mainline||'',detail:profileDraft.mainline_detail||''}];if(!displayDraft)displayDraft={display_name:state.profile.display_name,gender:state.profile.gender};for(const [key,itemKey] of Object.entries(profileListFields)){if(!profileDraft[itemKey]?.length)profileDraft[itemKey]=[profileDraft[key]||''];}const d=profileDraft,m=state.memory_status||{},institution=[d.school,d.department,d.laboratory].filter(Boolean).join('-');
 return head('RESEARCH PROFILE','我的科研简历','让助手了解你的知识起点、研究方向与当前目标，为论文推荐、解读、问答和知识图谱提供个人背景。',`<button id="save-profile" class="primary">保存研究档案</button>`)+`
 <div class="profile-layout"><div class="resume"><div class="resume-header"><span class="resume-monogram">${esc((state.profile.display_name||'我').slice(0,1))}</span><div><h2>${esc(state.profile.display_name||'你的科研简历')}</h2>${[d.stage,institution].filter(Boolean).length?`<p class="muted">${esc([d.stage,institution].filter(Boolean).join(' · '))}</p>`:''}<span id="profile-save-status" class="small muted">${profileDirty?'有修改尚未保存':''}</span></div></div>
 ${profileGroups.map(([title,description,fields],i)=>`<section class="resume-section"><div class="resume-section-head"><span>${String(i+1).padStart(2,'0')}</span><div><h2>${title}</h2><p class="hint">${description}</p></div></div>${title==='研究主线'?mainlineForm(d):`<div class="resume-fields">${fields.map(([key,label,placeholder,limit,rows])=>profileListFields[key]?profileListForm(key,label,placeholder,d):`<label class="${key==='personal_statement'?'full-width':''}">${label}${rows===1?`<input data-profile-field="${key}" value="${esc(d[key]||'')}" maxlength="${limit}" placeholder="${esc(placeholder)}">`:`<textarea data-profile-field="${key}" rows="${rows}" maxlength="${limit}" placeholder="${esc(placeholder)}">${esc(d[key]||'')}</textarea>`}</label>`).join('')}</div>`}</section>`).join('')}
 <button id="save-profile-bottom" class="primary">保存研究档案</button></div>
 <aside class="profile-aside"><section class="panel"><h3>让助手跟上你的研究</h3><p class="hint">科研简历说明你从哪里出发，研究主线说明你现在要解决什么。随着课题和目标变化，及时更新并保存这些资料，助手才能把论文的价值、解读的重点和知识之间的联系放到你的研究中理解。</p><p class="hint">不必一次填完。先写清当前方向、正在做的事和遇到的问题，再随研究进展逐步补充。</p></section><section class="panel display-preferences"><div class="display-preferences-head"><h3>其他信息</h3><button id="save-display" class="secondary" type="button">保存</button></div><div class="display-preferences-fields"><label>称呼<input id="display-name" maxlength="80" value="${esc(displayDraft.display_name||'')}" placeholder="例如：小林"></label><label>性别<select id="display-gender" aria-label="性别">${[['','不知道'],['男','男'],['女','女'],['秘密','秘密']].map(([value,label])=>`<option value="${value}" ${displayDraft.gender===value?'selected':''}>${label}</option>`).join('')}</select></label></div><p class="hint">仅用于对话界面，不提供给模型。</p></section><section class="panel"><h3>后台持续记忆</h3><p class="hint">开启后，助手会从论文提问、评价、个人思考和学习目标中逐步了解你的偏好与工作进展，让后续交流少一些重复说明，多一些对当前问题的理解。</p><label class="toggle-label"><input id="memory-enabled" type="checkbox" ${m.enabled?'checked':''}>持续记忆我的使用进展</label><p class="hint">${m.enabled?'已开启':'未开启'} · ${m.running?'正在后台整理':m.updated_at?'最近整理：'+date(m.updated_at):'尚未整理'}<br>关闭后停止新增和使用后台记忆，手填资料仍会使用。</p><p class="hint">记忆按用户保存在本地，切换模型仍可延续；它不会改写你的科研简历，研究方向的变化仍请主动更新。记忆正文仅供助手参考，你可以随时关闭或清空。</p><details class="hint"><summary>记忆如何更新</summary><p>首次开启会参考已有的用户提问与评价；至少积累 3 条新活动后，最多每 30 分钟额外调用一次当前模型整理。未整理的新活动也可供助手参考。</p></details>${m.error?`<p class="hint error">${esc(m.error)}</p>`:''}<button id="clear-memory" class="textbtn danger">清空后台记忆</button></section>
</aside></div>`;
}
function abstractState(source){
 const original=(source.match(/[\u4e00-\u9fff]/g)||[]).length/source.length>.1?'zh':'en';
 const language=abstractLanguages.get(source)||original;
 const saved=(state.abstract_translations||[]).find(t=>t.source_text===source&&t.language===language);
 const isOriginal=language===original,loading=abstractPending.get(source)===language;
 return {language,loading,text:isOriginal?source:saved?.text,
  label:isOriginal?'原文':saved?'AI 译文 · 已缓存':'按需翻译，使用当前模型',
  message:loading?'正在翻译，可先切回原文阅读…':abstractErrors.get(source)||'点击语言按钮生成译文。'};
}
function abstractView(p,ref,origin,runId){
 const a=abstractState(p.abstract),key=origin+':'+runId+':'+p.id;
 return `<details class="abstract" data-abstract-ref="${ref}" data-abstract-key="${esc(key)}" ${abstractOpen.has(key)?'open':''}><summary>查看论文摘要</summary><div class="abstract-toolbar"><div class="row">${[['zh','中文'],['en','English']].map(([lang,label])=>`<button type="button" class="${a.language===lang?'primary':'secondary'}" data-abstract-language="${lang}" data-abstract-card="${ref}" aria-pressed="${a.language===lang}">${label}</button>`).join('')}</div><span class="small muted" data-abstract-label>${a.label}</span></div><p data-abstract-body class="${a.text?'abstract-text':'hint'}" aria-live="polite" aria-busy="${a.loading}">${esc(a.text||a.message)}</p></details>`;
}
function updateAbstractViews(source){
 // Keep the details, buttons and surrounding lists mounted. A translation must
 // not rebuild #app, collapse another disclosure, or steal keyboard focus.
 const nodes=[...document.querySelectorAll('[data-abstract-ref]')].filter(el=>cardRefs[Number(el.dataset.abstractRef)]?.paper.abstract===source);
 const anchor=nodes.map(el=>el.querySelector('.abstract-toolbar')).find(el=>{const r=el.getBoundingClientRect();return r.top>=0&&r.bottom<=window.innerHeight});
 const top=anchor?.getBoundingClientRect().top;
 const a=abstractState(source);
 for(const el of nodes){
  const body=el.querySelector('[data-abstract-body]');
  // Retain the occupied space until the user collapses this abstract, so a
  // short loading message/translation cannot pull the rest of the list up.
  if(el.open)body.style.minHeight=body.getBoundingClientRect().height+'px';
  body.textContent=a.text||a.message;body.className=a.text?'abstract-text':'hint';
  body.setAttribute('aria-busy',String(a.loading));
  el.querySelector('[data-abstract-label]').textContent=a.label;
  el.querySelectorAll('[data-abstract-language]').forEach(b=>{const active=b.dataset.abstractLanguage===a.language;b.className=active?'primary':'secondary';b.setAttribute('aria-pressed',String(active))});
 }
 if(anchor){const delta=anchor.getBoundingClientRect().top-top;if(Math.abs(delta)>1)window.scrollBy(0,delta)}
}
async function chooseAbstract(ref,language){
 const r=cardRefs[ref];if(!r?.paper.abstract)return;const source=r.paper.abstract;
 abstractLanguages.set(source,language);abstractOpen.add(r.origin+':'+r.runId+':'+r.paper.id);
 const original=(source.match(/[\u4e00-\u9fff]/g)||[]).length/source.length>.1?'zh':'en';
 if(original===language||(state.abstract_translations||[]).some(t=>t.source_text===source&&t.language===language)){updateAbstractViews(source);return}
 if(abstractPending.has(source)){updateAbstractViews(source);return}
 abstractPending.set(source,language);abstractErrors.delete(source);updateAbstractViews(source);
 try{
  let job=await request('/api/abstract-translate',{origin:r.origin,run_id:r.runId,paper_id:r.paper.id,language});
  while(['queued','running'].includes(job.status)){await new Promise(resolve=>setTimeout(resolve,1200));job=await request('/api/job/'+job.id)}
  if(job.status!=='completed')throw Error(job.error||'摘要翻译失败');
  state.abstract_translations=(state.abstract_translations||[]).filter(t=>t.id!==job.result.id).concat(job.result);
 }catch(e){abstractErrors.set(source,e.message);toast(e.message,true)}finally{abstractPending.delete(source);updateAbstractViews(source)}
}
function paperCard(p, origin, runId='', favorite=null){
 const ref=cardRefs.push({paper:p,origin,runId,favorite})-1;
 const saved=(state.favorites||[]).find(f=>(f.paper.paper_url||f.paper.source_url)===(p.paper_url||p.source_url));
 const url=p.paper_url||p.source_url;
 const reports=(p.reports||[]).map(r=>`<div class="report-source"><span class="tag">${esc(state.sources?.[r.source]?.name||r.source_name||r.source)}</span> <a href="${esc(r.source_url)}" target="_blank" rel="noopener">${esc(r.title)} ↗</a><small> · ${date(r.published)}${r.date_inferred?'（日期推定）':''}${r.cached?' · 上次缓存':''}</small></div>`).join('');
 return `<article class="rec-card" data-view-anchor="card-${esc(origin)}-${esc(p.id)}"><div class="small muted">${origin==='daily'?'中文公众号 · 论文线索':sourceLabel(p.source||'arxiv')}${p.listing_date?' · DailyPapers 收录 '+esc(p.listing_date)+(p.listing_cached?'（上次缓存）':''):''}${p.published?' · 论文发布 '+esc(p.published.slice(0,10)):''}</div><h3><a href="${esc(url)}" target="_blank" rel="noopener">${esc(p.title)} ↗</a></h3>${p.metadata_status==='unavailable'?`<p class="small muted">${esc((p.paper_url||p.source_url||p.id).replace('https://arxiv.org/abs/','arXiv: ').replace('https://doi.org/','DOI: '))}</p>`:''}${p.match_type?`<span class="tag">${({direct:'原词匹配',alias:'简称对应',related:'相关候选'})[p.match_type]||'标题匹配'}</span>`:''}${reports}<div class="small muted">${esc((p.authors||[]).slice(0,3).join(', '))}${p.venue?' · '+esc(p.venue):''}</div>${p.reason?`<div class="rationale">${esc(p.reason)}</div>${p.taste?`<div class="dimension"><strong>品味匹配：</strong>${esc(p.taste)}</div>`:''}${p.tracking?`<div class="dimension"><strong>追踪价值：</strong>${esc(p.tracking)}</div>`:''}`:''}${p.abstract?abstractView(p,ref,origin,runId):''}<div class="row card-actions">${favorite?`<button class="textbtn danger" data-favorite-action="delete" data-favorite-id="${esc(favorite.id)}">移出待读清单</button>`:`<button class="secondary" data-save-card="${ref}" ${saved?'disabled':''}>${saved?'已加入待读清单':'加入待读清单'}</button>`}${/^https:\/\/arxiv\.org\/abs\//.test(url)?`<button data-import="${esc(url)}" ${(favorite||saved)?`data-import-favorite="${esc((favorite||saved).id)}"`:""} class="secondary" data-task>导入论文阅读</button>`:`<a class="secondary" href="${esc(url)}" target="_blank" rel="noopener">查看原文 ↗</a>`}${p.pdf_url?`<a class="textbtn" href="${esc(p.pdf_url)}" target="_blank" rel="noopener">开放 PDF ↗</a>`:''}${['daily','hf-listing'].includes(origin)?hotspotSkipButton(p,origin,runId):''}</div>${['daily','hf-listing','hotspot-skipped','hotspot-recovered'].includes(origin)||p.source==='chinese'?'':`<p class="hint">${esc(p.evidence_scope||'仅依据摘要')}</p>`}</article>`
}
function titleSearchStatus(result){
 const model=result.model_status, unresolved=(result.candidates||[]).filter(c=>!c.verified);
 return `${model?`<p class="${model.ok?'hint':'error'}">${esc(model.ok?(names[model.provider]||model.provider)+' · '+model.model+' · 已辨认候选论文':model.message)}</p>`:''}${!result.complete?'<p class="hint">部分来源、候选核实或模型辨认未完成，当前结果可能不完整。</p>':''}<details class="coverage"><summary>搜索来源与候选核实</summary>${sourceStates(result)}${result.web_supplement?`<p class="hint">联网补充 · ${result.web_supplement.requests} 次请求 · 缓存 ${result.web_supplement.cache_hits} 次 · 接口估算 ¥${Number(result.web_supplement.estimated_cny).toFixed(3)}${result.web_supplement.unknown?' · 有请求费用待确认':''}</p>${(result.web_supplement.errors||[]).map(e=>`<p class="hint">${esc(e)}</p>`).join('')}`:''}${result.web_leads?.length?`<p class="hint">其他网页线索（未核实为论文）</p><ul>${result.web_leads.map(p=>`<li><a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.title)} ↗</a></li>`).join('')}</ul>`:''}${unresolved.length?`<p class="hint">以下候选尚未查证，不计入论文结果：</p><ul>${unresolved.map(c=>`<li>${esc(c.title)}</li>`).join('')}</ul>`:''}</details>`
}
async function followTitleJob(job){
 titleLoading=true;
 try{
  while(['queued','running'].includes(job.status)){
   titleProgress=job.progress||'正在搜索';if(view==='discover')render();
   await new Promise(resolve=>setTimeout(resolve,1200));job=await request('/api/job/'+job.id);
  }
  if(job.status!=='completed')throw Error(job.error||'论文搜索失败');
  titleResult=job.result;titleQuery=job.result.query;
 }finally{titleLoading=false;if(view==='discover')render()}
}
async function searchTitle(){
 if(titleLoading)return;
 const query=titleQuery.trim();
 if(query.length<2){toast('请输入论文标题、简称或前几个词',true);return}
 titleLoading=true;titleProgress='准备联网检索';titleError='';titleResult=null;render();
 try{await followTitleJob(await request('/api/title-search',{query,async:true}))}catch(e){titleError=e.message}finally{titleLoading=false;if(view==='discover')render()}
}
async function loadHfList(){
 if(hfLoading)return;
 const days=Number(hfDays),force=hfResult?.days===days;
 hfLoading=true;hfError='';render();
 try{hfResult=await request('/api/hf-list',{days,force});setFoldExpanded('hf-results',true)}catch(e){hfError='读取 DailyPapers 列表失败；'+e.message}finally{hfLoading=false;if(view==='hotspots')render()}
}
function hotspotNewsEnabled(){return state?.settings?.hotspot_news_enabled!==false}
async function refreshDaily(force){
 if(!hotspotNewsEnabled()||dailyLoading)return;
 const day=hotspotDay, sourceRevision=newsSourceRevision;dailyLoading=true;dailyError='';if(view==='hotspots')render();
 try{const result=await request('/api/daily-refresh',{force,day});if(hotspotNewsEnabled()&&sourceRevision===newsSourceRevision){dailyByDay[day]=result;state.daily=result}}catch(e){if(e.message==='领域动态已关闭，可在模型设置中重新开启'){state.settings.hotspot_news_enabled=false;dailyByDay={};state.daily={items:[],articles:[],source_status:[]};dailyError=''}else if(hotspotNewsEnabled()&&sourceRevision===newsSourceRevision)dailyError='更新失败，已保留本地缓存；'+e.message}finally{dailyLoading=false;if(view==='hotspots')render();if(sourceRevision!==newsSourceRevision)refreshDaily(false)}
}
let citationPaperId=null;
function openCitations(role){
 citationPaperId=selected.id;
 const authors=(selected.report?.paper_info?.authors||[]).filter((a,i)=>role==='first'?i===0:a.corresponding);
 $('#citation-fields').innerHTML=authors.length?authors.map(a=>`<label class="citation-field"><span>${esc(a.name)}${a.scholar?.verified?`<small class="muted">${esc(a.scholar.source)} · ${esc(a.scholar.count)} 次引用</small>`:''}${a.corresponding_source==='last_author_default'?'<small class="muted"> · 原文未注明通讯，按尾作显示</small>':''}</span><input type="number" min="0" max="999999999" step="1" data-citation-name="${esc(a.name)}" value="${esc(a.manual_citation?.count??'')}" placeholder="选填"></label>`).join(''):'<p class="muted">尚未提取作者，请先更新论文相关。</p>';
 $('#citations-error').hidden=true;$('#citations-form button[type="submit"]').disabled=!authors.length;$('#citations-dialog').showModal();
}
$('#close-citations').onclick=()=>$('#citations-dialog').close();
$('#citations-form').onsubmit=async e=>{
 e.preventDefault();const button=$('#citations-form button[type="submit"]');button.disabled=true;$('#citations-error').hidden=true;
 try{
  const citations=Object.fromEntries([...document.querySelectorAll('[data-citation-name]')].map(el=>[el.dataset.citationName,el.value.trim()===''?null:Number(el.value)]));
  const saved=await request('/api/author-citations',{id:citationPaperId,citations});
  if(selected?.id===saved.id)selected=saved;
  const index=state.papers.findIndex(p=>p.id===saved.id);if(index>=0)state.papers[index]=saved;
  const position=ViewContinuity.capture($('#app'));$('#citations-dialog').close();render(position);toast('引用量已保存');
 }catch(error){$('#citations-error').textContent=error.message;$('#citations-error').hidden=false}finally{button.disabled=false}
};
async function guard(fn){try{await fn()}catch(e){toast(e.message,true)}}
function renderReaderUpdate(){
 const drafts=view==='paper'?['paper-short-title','publication-month','feedback'].flatMap(id=>{const el=document.getElementById(id);return el&&el.value!==el.defaultValue?[[id,el.value]]:[]}):[];
 render();for(const [id,value] of drafts){const el=document.getElementById(id);if(el)el.value=value}
}
function analysisActive(id){return analysisSubmitting.has(id)||['queued','running'].includes(state.analysis_jobs?.[id]?.status)}
function updateAnalysisUI(id){
 if(view!=='paper'||selected?.id!==id)return;
 const stop=$('#stop-analysis');if(stop)stop.hidden=!analysisActive(id);
 const status=$('#reading-task-status');if(status)status.innerHTML=readingTaskStatus(selected);
 const button=$('#analyze');if(button){button.disabled=analysisActive(id);button.textContent=button.disabled?'生成中…':selected.pdf_released?'恢复原文后生成解读':latestReadingTask(selected)?.status==='failed'?'重试生成解读':selected.report?'重新生成解读':'生成解读'}
}
async function stopAnalysis(){
 const id=selected?.id,job=state.analysis_jobs?.[id];
 if(!job||!['queued','running'].includes(job.status))return;
 const button=$('#stop-analysis');if(button){button.disabled=true;button.textContent='正在停止…'}
 try{
  const stopped=await request('/api/analysis-cancel',{job_id:job.id});
  if(state.analysis_jobs?.[id]?.id===job.id)state.analysis_jobs[id]=stopped;
  updateAnalysisUI(id);
 }finally{if(button){button.disabled=false;button.textContent='停止生成'}}
}
async function followAnalysis(job){
 if(analysisObservers.has(job.id))return;
 analysisObservers.set(job.id,true);const id=job.paper_id;
 try{
  while(true){
   if(state.analysis_jobs?.[id]?.id&&state.analysis_jobs[id].id!==job.id)return;
   state.analysis_jobs??={};state.analysis_jobs[id]=job;updateAnalysisUI(id);
   if(!['queued','running'].includes(job.status))break;
   await new Promise(r=>setTimeout(r,1500));
   for(let attempt=0;;attempt++){
    try{job=await request('/api/job/'+job.id);break}catch(e){if(attempt>=2||/用户|会话/.test(e.message))throw e;await new Promise(r=>setTimeout(r,1500))}
   }
  }
  await reload(false);renderReaderUpdate();
  if(view==='paper'&&selected?.id===id)toast(job.status==='completed'?'解读已生成':job.status==='cancelled'?'已停止生成，可重新选择阅读方式':job.error||'生成未完成，可查看原因后重试',job.status==='failed');
 }catch(e){
  if(state.analysis_jobs?.[id]?.id&&state.analysis_jobs[id].id!==job.id)return;
  state.analysis_jobs??={};state.analysis_jobs[id]={...job,monitor_error:true};updateAnalysisUI(id);
  if(view==='paper'&&selected?.id===id)toast(e.message,true);
 }finally{analysisObservers.delete(job.id)}
}
function watchAnalyses(){for(const job of ReaderState.pendingAnalyses(state,separateReader?selected?.id:null))void followAnalysis(job)}
async function startAnalysis(body){
 if(analysisActive(body.id))return;
 analysisSubmitting.add(body.id);updateAnalysisUI(body.id);
 try{const job=await request('/api/analyze',body);state.analysis_jobs??={};state.analysis_jobs[body.id]=job;void followAnalysis(job)}
 catch(e){await reload(false);render();watchAnalyses();throw e}
 finally{analysisSubmitting.delete(body.id);updateAnalysisUI(body.id)}
}
async function runJob(j,origin=navigationContext()){
 if(busy){toast('当前任务还在进行，请等它完成');return}
 busy=true;
 try{
  if(j.kind==='knowledge'&&stillAt(origin)){
   knowledgeScope=j.graph_scope||'all';knowledgeMainline=j.mainline_key||'';
   origin=navigationContext();
   if((state.knowledge?.mainline_key||'')!==knowledgeMainline){
    const graph=await request('/api/knowledge?'+new URLSearchParams({mainline:knowledgeMainline}));
    if(stillAt(origin))state.knowledge=graph;
   }
  }
  render();$('#jobbar').hidden=false;
  while(true){
   if(j.kind==='analysis'&&j.paper_id){state.analysis_jobs??={};state.analysis_jobs[j.paper_id]=j;}
   $('#jobtext').textContent=j.progress||'正在处理';
   if(j.status==='completed'){
    if(j.kind==='hf-classify'){hfResult=j.result;hfOnlyRelevant=true;setFoldExpanded('hf-results',true)}
    if(j.kind==='discovery')searchResult=j.result;
    if(j.kind==='route'&&j.result?.id)setFoldExpanded('route-'+j.result.id,true);
    await reload(false);
    // A finished background job must not take over a different page or paper.
    if(stillAt(origin)){
     const historical=['historical-pdf-metadata','historical-pdf-date'].includes(j.kind);
     const paper=j.result?.paper_id&&state.papers.find(p=>p.id===j.result.paper_id);
     if(paper&&!historical){selected=paper;view='paper'}
     if(j.kind==='hf-classify')view='hotspots';
     if(j.kind==='route'&&j.result?.id)view='discover';
     if(j.kind==='discovery'){view='discover';discoveryMode='filter'}
     if(j.kind==='knowledge'){view='knowledge';knowledgeScope=j.graph_scope||'all'}
     if(historical&&paper){historicalPdfId=paper.id;historicalPdfTitle=paper.historical_metadata?.title||paper.title;historicalPdfMonth=paper.historical_metadata?.publication_month||paper.publication_month||'';historicalMode='pdf';historicalOpen=true;view='knowledge'}
    }
    if(j.kind==='connection')toast('连接成功：'+(j.result?.value||'已收到模型响应'));
    else if(j.kind==='export'){const a=document.createElement('a');a.href=scopedFile(j.result.url);a.download='';a.click();toast('文件已导出，可再次点击下载')}
    else toast('任务已完成');
    break;
   }
   if(j.status==='failed'){
    if(j.kind==='hf-classify'){hfResult=await request('/api/hf-classification',{id:j.listing_id});hfError=j.error||'筛选未完成，可继续筛选'}
    if(j.kind==='knowledge'){
     await reload(false);
     if(stillAt(origin)&&state.knowledge?.starred_graph?.generated_at&&!state.knowledge.starred_graph.stale)knowledgeScope='starred';
    }
    throw Error(j.error||'任务失败');
   }
   await new Promise(r=>setTimeout(r,1500));
   for(let attempt=0;;attempt++){
    try{j=await request('/api/job/'+j.id);break}
    catch(error){
     if(attempt>=2||/用户|会话/.test(error.message))throw error;
     $('#jobtext').textContent='正在重新连接任务进度…';
     await new Promise(r=>setTimeout(r,1500));
    }
   }
  }
 }catch(error){
  if(j.kind==='analysis'&&j.paper_id&&['running','queued'].includes(j.status)){
   state.analysis_jobs??={};state.analysis_jobs[j.paper_id]={...j,monitor_error:true};
  }
  throw error;
 }finally{busy=false;$('#jobbar').hidden=true;render()}
}
async function startJob(path,body){
 if(busy)return toast('当前任务还在进行');
 const origin=navigationContext();
 await runJob(await request(path,body),origin);
}
async function saveSettings(){const p=draftProvider||state.settings.provider;const body={provider:p,vision:$('#vision').checked,context_chars:Number($('#context-chars').value),hotspot_news_enabled:$('#hotspot-news-enabled').checked,reasoning_policy:readReasoningPolicy()};if(p==='codex'){body.model=$('#model').value}else{body.web_supplement_enabled=$('#web-supplement-enabled').checked;body.output_tokens=Number($('#output-tokens').value);body.output_tokens_auto=$('#output-auto').checked;body[p]={base_url:$('#base-url').value,model:$('#api-model').value,detail_model:$('#detail-model').value}}const r=await request('/api/settings',body);state.settings=r.settings;if(!hotspotNewsEnabled()){dailyByDay={};dailyError='';state.daily={items:[],articles:[],source_status:[]}}state.capabilities=r.capabilities;draftProvider=null;reasoningDraft=null;hotspotNewsDraft=null;$('#provider-badge').textContent=names[state.settings.provider]}

function bind(){
 bindWorkspace();
 const customToggle=$('#reasoning-custom-enabled');
 if(customToggle)customToggle.onchange=()=>{document.querySelectorAll('[data-reasoning-group]').forEach(el=>el.disabled=!customToggle.checked);reasoningDraft=readReasoningPolicy()};
 document.querySelectorAll('[data-reasoning-group]').forEach(el=>el.onchange=()=>{reasoningDraft=readReasoningPolicy()});
 const useRecommended=$('#reasoning-recommended');
 if(useRecommended)useRecommended.onclick=()=>{customToggle.checked=false;document.querySelectorAll('[data-reasoning-group]').forEach(el=>{el.value='recommended';el.disabled=true});reasoningDraft=readReasoningPolicy();toast('已选择推荐配置，保存设置后生效')};
 const newsToggle=$('#hotspot-news-enabled');if(newsToggle)newsToggle.onchange=()=>{hotspotNewsDraft=newsToggle.checked};
 const settingsMemory=$('#settings-memory-enabled');
 if(settingsMemory)settingsMemory.onchange=()=>guard(async()=>{const desired=settingsMemory.checked;settingsMemory.disabled=true;try{state.memory_status=await request('/api/memory',{enabled:desired});state.settings.memory.enabled=desired;toast(desired?'持续记忆已开启':'已停止记录和使用后台记忆')}catch(e){settingsMemory.checked=!desired;throw e}finally{settingsMemory.disabled=false}});

 bindKnowledge();
 const on=(s,fn)=>{const el=$(s);if(el)el.onclick=()=>guard(fn)};
 document.querySelectorAll('[data-storage]').forEach(b=>b.onclick=()=>guard(()=>openPaperStorage(b.dataset.storage,b.dataset.manualRestore==='1')));
 on('#show-skipped-hotspots',()=>{hotspotSkippedOpen=!hotspotSkippedOpen;render()});
 on('#close-skipped-hotspots',()=>{hotspotSkippedOpen=false;hotspotRestored.clear();render()});
 document.querySelectorAll('[data-skip-hotspot]').forEach(b=>b.onclick=()=>guard(()=>skipHotspot(b)));
 document.querySelectorAll('[data-restore-hotspot]').forEach(b=>b.onclick=()=>guard(()=>restoreHotspot(b)));
 on('#model-setup-open',async()=>{const provider=draftProvider||state.settings.provider,setup=await request('/api/model-setup');$('#model-setup-title').textContent=provider==='codex'?'通过 Codex 接入':'通过 dsh 接入';$('#model-setup-instruction').value=ModelSetupView.instruction(provider,setup);$('#model-setup-dialog').showModal()});
 on('#model-setup-check',async()=>{const button=$('#model-setup-check'),status=$('#model-setup-status'),provider=draftProvider||state.settings.provider;button.disabled=true;status.hidden=false;status.textContent='正在检查…';try{const setup=await request('/api/model-setup');const result=provider==='codex'?await request('/api/codex-status'):{message:setup.deepseek_configured?'密钥已配置；可点击“保存并测试连接”确认模型可用。':'尚未配置 API Key。'};if(status.isConnected){status.textContent=result.message;state.capabilities=setup.capabilities;const badge=$('.connection-badge'),ready=provider==='codex'?result.ready:setup.deepseek_configured;badge.textContent=provider==='codex'?(ready?'本地已登录':setup.codex_available?'待登录':'待安装 CLI'):(ready?'密钥已配置':'待接入');badge.classList.toggle('configured',!!ready);if(provider==='deepseek'&&ready){const field=$('#api-key');field.value=setup.capabilities.key_storage.deepseek.masked;field.readOnly=true;field.type='text';$('#reset-api-key').disabled=false;$('#confirm-api-key').disabled=true;}}}finally{if(button.isConnected)button.disabled=false}});
 on('#materials-recommended',()=>{$('#vision').checked=true;$('#context-chars').value='100000';toast('已恢复论文材料推荐配置，保存后生效')});
 on('#copy-codex-command',async()=>{await navigator.clipboard.writeText(state.codex_setup.command);toast('配置命令已复制，请在 PaperPilot 项目目录的终端中执行');});
 bindDiscovery();
 on('#back',()=>setView('library'));
 document.querySelectorAll('[data-library-tab]').forEach(b=>{b.onclick=()=>{libraryTab=b.dataset.libraryTab;render();$(`#library-tab-${libraryTab}`).focus({preventScroll:true})};b.onkeydown=e=>{const keys=['reading','read','liked','starred'];if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();libraryTab=e.key==='Home'?keys[0]:e.key==='End'?keys[keys.length-1]:keys[(keys.indexOf(libraryTab)+(e.key==='ArrowRight'?1:keys.length-1))%keys.length];render();$(`#library-tab-${libraryTab}`).focus({preventScroll:true})}}});
 document.querySelectorAll('[data-preference]').forEach(b=>{b.onclick=e=>{e.stopPropagation();guard(async()=>{
  const p=state.papers.find(p=>p.id===b.dataset.preferencePaper),current=p.starred?'starred':p.liked?'liked':'none';
  const buttons=[...document.querySelectorAll('[data-preference-paper]')].filter(el=>el.dataset.preferencePaper===p.id);
  buttons.forEach(el=>el.disabled=true);
  try{await request('/api/paper-reading',{id:p.id,action:'preference',preference:current===b.dataset.preference?'none':b.dataset.preference});await reload()}
  finally{buttons.forEach(el=>{if(el.isConnected)el.disabled=false})}
 })};b.onkeydown=e=>e.stopPropagation()});
 on('#finish-reading',async()=>{const p=selected,button=$('#finish-reading');button.disabled=true;try{await request('/api/paper-reading',{id:p.id,action:'finish',report_at:p.report.generated_at});await reload();toast(p.starred?'已记录阅读，论文仍保留在我的收藏':p.liked?'已记录阅读，论文仍保留在我的喜欢':'已记录阅读，论文已移至已读论文')}finally{if(button.isConnected)button.disabled=LibraryView.done(selected)}});
 on('#start-reading',async()=>{await request('/api/paper-reading',{id:selected.id,action:'start'});await reload();toast('已开始新一轮阅读')});
 on('#pick-favorite',openFavorites);
 on('#refresh-paper-info',()=>startJob('/api/paper-info',{id:selected.id}));
 document.querySelectorAll('[data-citation-role]').forEach(button=>button.onclick=()=>openCitations(button.dataset.citationRole));
 on('#save-publication-month',async()=>{acceptPaperUpdate(await request('/api/paper-update',{id:selected.id,publication_month:$('#publication-month').value,short_title:$('#paper-short-title').value}));render();toast('论文标识已保存')});
 document.querySelectorAll('[data-delete]').forEach(el=>{el.onclick=e=>{e.stopPropagation();openDelete(state.papers.find(p=>p.id===el.dataset.delete)||selected)};el.onkeydown=e=>e.stopPropagation()});
 document.querySelectorAll('[data-forget]').forEach(el=>el.onclick=()=>guard(async()=>{if(!confirm('删除这条阅读记录及偏好反馈？'))return;await request('/api/history-delete',{id:el.dataset.forget});await reload();toast('阅读记录已删除')}));
 const notes=$('#personal-notes');if(notes)notes.oninput=()=>{notesDrafts.set(selected.id,notes.value);$('#notes-status').textContent='尚未保存'};
 on('#save-notes',async()=>{const id=selected.id,text=$('#personal-notes').value;const saved=await request('/api/paper-update',{id,notes:text});const p=state.papers.find(p=>p.id===id);if(p)Object.assign(p,{notes:saved.notes,notes_updated_at:saved.notes_updated_at});if(selected?.id===id){selected.notes=saved.notes;selected.notes_updated_at=saved.notes_updated_at}if(notesDrafts.get(id)===text)notesDrafts.delete(id);if(selected?.id===id&&$('#notes-status'))$('#notes-status').textContent=notesDrafts.has(id)?'尚未保存':'已保存 · '+date(saved.notes_updated_at);toast('个人思考已保存')});
 on('#translate-captions',()=>startJob('/api/captions',{id:selected.id}));
 document.querySelectorAll('[data-paper]').forEach(el=>{el.onclick=e=>{if(e?.target.closest('a,button,input,select,textarea'))return;selected=state.papers.find(p=>p.id===el.dataset.paper);if(selected)setView('paper');else toast('论文已移除',true)};el.onkeydown=e=>{if(e.target!==el)return;if(e.key==='Enter'||e.key===' '){e.preventDefault();el.onclick()}}});
 const upload=$('#upload');if(upload)upload.onchange=()=>guard(async()=>{const f=upload.files[0];if(!f)return;if(f.size>40*1024*1024)throw Error('最大支持 40 MB');const origin=navigationContext();toast('正在提取文字和图表…');const paper=await request('/api/upload',f,true,{'X-Filename':encodeURIComponent(f.name)});await reload(false);if(stillAt(origin)){selected=state.papers.find(p=>p.id===paper.id)||paper;setView('paper')}else{render();toast('论文已导入论文库')}});
 on('#import-link',()=>startJob('/api/import',{url:$('#paper-url').value.trim()}));
 on('#manage-ppt-samples',()=>{renderPptSamples();$('#ppt-samples-dialog').showModal();pollPptStyle()});
 on('#manage-style-samples',()=>{renderStyleSamples();$('#style-samples-dialog').showModal();pollStyleCache()});
 if($('#figure-scope'))$('#figure-scope').onchange=()=>{const mode=$('#read-mode').value;readingScopes.set(selected.id,$('#figure-scope').value);render();$('#read-mode').value=mode};
 if($('#read-mode'))$('#read-mode').onchange=e=>readingModes.set(selected.id,e.target.value);
 document.querySelectorAll('[data-outline-step]').forEach(el=>{const resize=()=>{el.closest('.outline-step').classList.toggle('is-long',el.value.length>12);el.style.height='auto';el.style.height=el.scrollHeight+'px'};resize();el.oninput=()=>{outlineDraft(selected)[Number(el.dataset.outlineStep)]=el.value;resize();$('#outline-status').textContent='有修改 · 生成时一并保存'}});
 document.querySelectorAll('[data-outline-remove]').forEach(el=>el.onclick=()=>{const steps=outlineDraft(selected);if(steps.length>1){steps.splice(Number(el.dataset.outlineRemove),1);render()}});
 on('#add-outline',()=>{const steps=outlineDraft(selected);if(steps.length<8){steps.push('');render();$(`[data-outline-step="${steps.length-1}"]`)?.focus()}});
 on('#reset-outline',()=>{readingOutlines.set(outlineKey(selected),[...defaultOutline(selected)]);render()});
 on('#edit-outline',()=>{readingOutlines.set(outlineKey(selected),[...savedOutline(selected)]);editingOutlines.add(selected.id);render();$('[data-outline-step]')?.focus({preventScroll:true})});
 on('#cancel-outline',()=>{readingOutlines.set(outlineKey(selected),[...savedOutline(selected)]);editingOutlines.delete(selected.id);render()});
 on('#save-outline',saveReadingOutline);
 if($('#paper-type'))$('#paper-type').onchange=e=>guard(async()=>{const choice=e.target.value,id=selected.id;if(editingOutlines.has(id))await saveReadingOutline();const updated=await request('/api/paper-update',{id,paper_type:choice});const i=state.papers.findIndex(p=>p.id===id);if(i>=0)state.papers[i]=updated;if(selected?.id===id)selected=updated;render();toast('论文类型已保存，报告与 PPT 共用此设置')});
 on('#generate-presentation',async()=>{if(selected.pdf_released)return openPaperStorage(selected.id);if(busy)return;const id=selected.id,origin=navigationContext();if(editingOutlines.has(id))await saveReadingOutline();if(stillAt(origin))await startJob('/api/presentation',{id})});
 on('#analyze',async()=>{if(selected.pdf_released)return openPaperStorage(selected.id);if(analysisActive(selected.id))return;const id=selected.id,origin=navigationContext(),mode=$('#read-mode').value,scope=$('#figure-scope').value;if(editingOutlines.has(id))await saveReadingOutline();if(stillAt(origin))await startAnalysis({id,mode,figure_scope:scope})});
 on('#open-paper-chat',()=>togglePaperChat(!paperChatOpen));
 on('#close-paper-chat',()=>togglePaperChat(false));
 on('#stop-paper-answer',stopPaperMessage);
 on('#stop-analysis',stopAnalysis);
 if($('#question')){
  $('#question').oninput=e=>chatDrafts.set(selected.id,e.target.value);
  $('#question').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();guard(sendPaperMessage)}};
  $('#paper-chat-form').onsubmit=e=>{e.preventDefault();guard(sendPaperMessage)};
 }

 document.querySelectorAll('[data-export]').forEach(b=>b.onclick=()=>guard(()=>startJob('/api/export',{id:selected.id,format:b.dataset.export})));
 document.querySelectorAll('[data-figure]').forEach(el=>el.onchange=()=>guard(async()=>{const updated=selected.figures.map(f=>({...f,selected:f.id===el.dataset.figure?el.checked:f.selected}));acceptPaperUpdate(await request('/api/paper-update',{id:selected.id,figures:updated}));render()}));
 document.querySelectorAll('[data-crop]').forEach(b=>b.onclick=()=>guard(()=>openCrop(selected.figures.find(f=>f.id===b.dataset.crop))));
 on('#add-figure',()=>openCrop(null));
 on('#save-feedback',async()=>{acceptPaperUpdate(await request('/api/paper-update',{id:selected.id,feedback:$('#feedback').value}));toast('反馈已保存，会用于后续解读和推荐')});
 document.querySelectorAll('[data-provider]').forEach(b=>b.onclick=()=>{draftProvider=b.dataset.provider;render()});
 on('#reset-api-key',async()=>{const r=await request('/api/deepseek-key',{action:'reset'});state.capabilities=r.capabilities;render();$('.model-manual').open=true;$('#api-key').focus({preventScroll:true});toast('已清除 PaperPilot 使用的密钥，请输入新密钥后确认')});
 on('#confirm-api-key',async()=>{const field=$('#api-key');const value=field.value.trim();if(!value)throw Error('请输入 API Key');const r=await request('/api/deepseek-key',{action:'confirm',key:value});field.value='';state.capabilities=r.capabilities;render();toast('密钥已保存')});
 on('#output-auto',()=>{const automatic=$('#output-auto').checked;$('#output-tokens').disabled=automatic;$('#output-manual').hidden=automatic});
 on('#save-settings',async()=>{await saveSettings();render();toast('模型设置已保存')});
 on('#test-provider',async()=>{await saveSettings();await startJob('/api/test-provider',{})});
 const saveProfile=async()=>{const snapshot=JSON.parse(JSON.stringify(profileDraft));const result=await request('/api/profile',{profile:snapshot});state.profile=result.profile;if(JSON.stringify(profileDraft)===JSON.stringify(snapshot)){profileDraft=JSON.parse(JSON.stringify(result.profile));profileDirty=false}render();toast('研究档案已保存，将用于后续模型调用')};
 if($('#display-name'))$('#display-name').oninput=e=>displayDraft.display_name=e.target.value;
 if($('#display-gender'))$('#display-gender').onchange=e=>displayDraft.gender=e.target.value;
 on('#save-display',async()=>{const result=await request('/api/profile-display',displayDraft);state.profile=result.profile;profileDraft.display_name=result.profile.display_name;profileDraft.gender=result.profile.gender;displayDraft={display_name:result.profile.display_name,gender:result.profile.gender};render();toast('其他信息已更新')});
 on('#save-profile',saveProfile);on('#save-profile-bottom',saveProfile);
 on('#add-mainline',()=>{if(profileDraft.mainlines.length>=3)return;profileDraft.mainlines.push({title:'',detail:''});syncMainlineDraft();render()});
 document.querySelectorAll('[data-remove-mainline]').forEach(el=>el.onclick=()=>{profileDraft.mainlines.splice(Number(el.dataset.removeMainline),1);syncMainlineDraft();render()});
 document.querySelectorAll('[data-mainline-field]').forEach(el=>el.oninput=()=>{profileDraft.mainlines[Number(el.dataset.mainlineIndex)][el.dataset.mainlineField]=el.value;syncMainlineDraft();$('#profile-save-status').textContent='有修改尚未保存'});
 document.querySelectorAll('[data-add-profile-item]').forEach(el=>el.onclick=()=>{const key=el.dataset.addProfileItem,items=profileDraft[profileListFields[key]];if(items.length>=5)return;items.push('');syncProfileList(key);render();const box=$(`[data-profile-list="${key}"][data-profile-item="${items.length-1}"]`);box?.focus();box?.scrollIntoView({block:'nearest'})});
 document.querySelectorAll('[data-remove-profile-list]').forEach(el=>el.onclick=()=>{const key=el.dataset.removeProfileList;profileDraft[profileListFields[key]].splice(Number(el.dataset.profileItem),1);syncProfileList(key);render()});
 document.querySelectorAll('[data-profile-list]').forEach(el=>el.oninput=()=>{const key=el.dataset.profileList;profileDraft[profileListFields[key]][Number(el.dataset.profileItem)]=el.value;syncProfileList(key)});
 document.querySelectorAll('[data-profile-field]').forEach(el=>el.oninput=()=>{profileDraft[el.dataset.profileField]=el.value;profileDirty=true;$('#profile-save-status').textContent='有修改尚未保存'});
 const toggle=$('#memory-enabled');if(toggle)toggle.onchange=()=>guard(async()=>{const desired=toggle.checked;toggle.disabled=true;try{state.memory_status=await request('/api/memory',{enabled:desired});render();toast(desired?'持续记忆已开启':'已停止记录和使用后台记忆')}catch(e){toggle.checked=!desired;throw e}finally{toggle.disabled=false}});
 on('#clear-memory',async()=>{if(!confirm('清空后台记忆？手填简历、个人陈述与论文笔记会保留。'))return;state.memory_status=await request('/api/memory-clear',{});render();toast('后台记忆已清空')});
 document.querySelectorAll('[data-search-mode]').forEach(b=>b.onclick=()=>{discoveryMode=b.dataset.searchMode;render()});
 if($('#title-query'))$('#title-query').oninput=e=>titleQuery=e.target.value;
 if($('#title-search-form'))$('#title-search-form').onsubmit=e=>{e.preventDefault();guard(searchTitle)};
 on('#title-google',()=>{const query=titleQuery.trim();if(!query)throw Error('请先输入论文标题');window.open('https://scholar.google.com/scholar?'+new URLSearchParams({q:query,hl:'zh-CN'}),'_blank','noopener,noreferrer')});
 on('#clear-title-search',()=>{titleResult=null;titleError='';render()});
 if($('#search-query'))$('#search-query').oninput=e=>discoveryDraft.query=e.target.value;
 if($('#search-count'))$('#search-count').oninput=e=>discoveryDraft.count=e.target.value;
 if($('#route-goal'))$('#route-goal').oninput=e=>discoveryDraft.routeGoal=e.target.value;
 if($('#search-days'))$('#search-days').onchange=e=>discoveryDraft.days=e.target.value;
 document.querySelectorAll('.discover-source').forEach(el=>el.onchange=()=>{discoveryDraft.sources=[...document.querySelectorAll('.discover-source:checked')].map(e=>e.value)});
 const chosenSources=async()=>{const sources=discoveryDraft.sources;if(!sources.length)throw Error('请至少选择一个信息源');const result=await request('/api/settings',{discovery_sources:sources});state.settings=result.settings;return sources};
 on('#recommend',async()=>{if(!Number.isInteger(Number(discoveryDraft.count))||Number(discoveryDraft.count)<1||Number(discoveryDraft.count)>20)throw Error('推荐条目数须为 1–20 的整数');const sources=await chosenSources();await startJob('/api/recommend',{query:discoveryDraft.query,days:Number(discoveryDraft.days),count:Number(discoveryDraft.count),sources})});
 document.querySelectorAll('[data-abstract-key]').forEach(el=>el.ontoggle=()=>{if(el.isConnected){if(el.open)abstractOpen.add(el.dataset.abstractKey);else{abstractOpen.delete(el.dataset.abstractKey);const body=el.querySelector('[data-abstract-body]');if(body)body.style.minHeight=''}}});
 document.querySelectorAll('[data-abstract-language]').forEach(b=>b.onclick=()=>guard(()=>chooseAbstract(Number(b.dataset.abstractCard),b.dataset.abstractLanguage)));
 on('#refresh-daily',()=>refreshDaily(true));
 on('#hf-list',()=>loadHfList());
 on('#hf-classify',()=>{hfError='';return startJob('/api/hf-classify',{id:hfResult.id})});
 on('#hf-all',()=>{hfOnlyRelevant=false;render()});
 on('#hf-mine',()=>{hfOnlyRelevant=true;render()});
 if($('#hf-days'))$('#hf-days').onchange=e=>{hfDays=e.target.value;hfResult=null;hfError='';hfOnlyRelevant=false;render()};
 on('#clear-hf-list',()=>{hfResult=null;hfError='';hfOnlyRelevant=false;render()});
 on('#clear-search',async()=>{await request('/api/discovery-delete',{id:searchResult.id});searchResult=null;render()});
 document.querySelectorAll('[data-save-card]').forEach(b=>b.onclick=()=>guard(async()=>{const r=cardRefs[Number(b.dataset.saveCard)];b.disabled=true;try{await request('/api/favorite',{origin:r.origin,run_id:r.runId,paper_id:r.paper.id});await reload();toast('已加入待读清单')}finally{b.disabled=false}}));
 document.querySelectorAll('[data-favorite-action]').forEach(b=>b.onclick=()=>guard(async()=>{await request('/api/favorite-update',{id:b.dataset.favoriteId,action:b.dataset.favoriteAction});await reload();toast('已移出待读清单')}));
 document.querySelectorAll('[data-import]').forEach(b=>b.onclick=()=>guard(()=>startJob('/api/import',{url:b.dataset.import,favorite_id:b.dataset.importFavorite||undefined})));
 on('#route',async()=>{const question=$('#route-goal').value;const sources=await chosenSources();await startJob('/api/route',{question,sources})});
 if($('#chatmessages'))$('#chatmessages').scrollTop=$('#chatmessages').scrollHeight;
}
function openFavorites(){
 const rows=state.favorites||[];
 $('#favorites-picker').innerHTML=rows.length?rows.map(f=>`<article class="favorite-picker-row"><div class="favorite-picker-heading"><h3>${esc(f.paper.title)}</h3><button type="button" class="textbtn small" data-pick-remove="${esc(f.id)}">移出清单</button></div>${/^https:\/\/arxiv\.org\/abs\//.test(f.paper.paper_url||f.paper.source_url)?`<button class="secondary" data-pick-import="${esc(f.id)}">导入并移出待读清单</button>`:`<a href="${esc(f.paper.paper_url||f.paper.source_url)}" target="_blank" rel="noopener">打开原文 ↗</a><label class="hint">选择对应的论文 PDF<input type="file" accept="application/pdf" data-favorite-pdf="${esc(f.id)}"></label>`}</article>`).join(''):'<p class="muted">待读清单为空。先在“热点发现”或“论文检索”添加想读的论文。</p>';
 document.querySelectorAll('[data-pick-remove]').forEach(b=>b.onclick=()=>guard(async()=>{
  const row=b.closest('.favorite-picker-row');
  if(row.querySelector('input:disabled,button:disabled'))return;
  const controls=[...row.querySelectorAll('button,input')];controls.forEach(el=>el.disabled=true);
  try{
   await request('/api/favorite-update',{id:b.dataset.pickRemove,action:'delete'});
   state.favorites=(state.favorites||[]).filter(f=>f.id!==b.dataset.pickRemove);
   document.querySelectorAll('[data-pick-remove]').forEach(el=>{if(el.dataset.pickRemove===b.dataset.pickRemove)el.closest('.favorite-picker-row').remove()});
   if(!state.favorites.length)$('#favorites-picker').innerHTML='<p class="muted">待读清单为空。先在“热点发现”或“论文检索”添加想读的论文。</p>';
   const opener=$('#pick-favorite');if(opener)opener.textContent=`选择待读论文 · ${state.favorites.length} 篇`;
   toast('已移出待读清单');
  }finally{controls.forEach(el=>el.disabled=false)}
 }));
 document.querySelectorAll('[data-pick-import]').forEach(b=>b.onclick=()=>guard(async()=>{$('#favorites-dialog').close();await startJob('/api/import',{favorite_id:b.dataset.pickImport})}));
 document.querySelectorAll('[data-favorite-pdf]').forEach(el=>el.onchange=()=>guard(async()=>{const file=el.files[0];if(!file)return;const origin=navigationContext();el.disabled=true;try{const paper=await request('/api/upload',await file.arrayBuffer(),true,{'X-Filename':encodeURIComponent(file.name),'X-Favorite-Id':el.dataset.favoritePdf});$('#favorites-dialog').close();await reload(false);if(stillAt(origin)){selected=state.papers.find(p=>p.id===paper.id)||paper;setView('paper')}else render();toast('已导入论文库，并从待读清单移除')}finally{el.disabled=false}}));
 $('#favorites-dialog').showModal();
}
$('#close-favorites').onclick=()=>$('#favorites-dialog').close();
async function openCrop(figure){crop={paperId:selected.id,figure:figure?JSON.parse(JSON.stringify(figure)):null,page:figure?.page||1,bbox:figure?.bbox||[.05,.05,.95,.8]};$('#crop-page').value=crop.page;$('#crop-page').max=selected.page_count;$('#crop-page-total').textContent='/ '+selected.page_count;$('#crop-caption').value=figure?.caption_zh||(/[\u4e00-\u9fff]/.test(figure?.caption||'')?figure.caption:'');$('#crop-source-caption').value='';$('#crop-caption-status').textContent='';$('#crop-text-layer').innerHTML='';$('#translate-crop-caption').disabled=false;setCropMode(false);$('#crop-dialog').showModal();await loadCropPage()}
function setCropMode(text){$('#crop-text-layer').hidden=!text;$('#crop-source-tools').hidden=!text;$('#crop-mode-box').setAttribute('aria-pressed',String(!text));$('#crop-mode-text').setAttribute('aria-pressed',String(text))}
async function loadCropText(editing,page){
 const ticket=editing.pageRequest;const data=await request('/api/crop-page-text',{id:editing.paperId,page});if(crop!==editing||editing.page!==page||editing.pageRequest!==ticket)return;
 editing.textPage=page;const layer=$('#crop-text-layer');layer.innerHTML=data.lines.map(l=>`<span style="left:${l.bbox[0]*100}%;top:${l.bbox[1]*100}%;width:${(l.bbox[2]-l.bbox[0])*100}%;height:${(l.bbox[3]-l.bbox[1])*100}%;font-size:${(l.bbox[3]-l.bbox[1])*$('#crop-canvas').height/$('#crop-canvas').width*100}cqw">${esc(l.text)}
</span>`).join('');
 $('#crop-caption-status').textContent=data.lines.length?'在页面上选取图注，再点击翻译；保存前可修改中文。':'本页没有可选择的文字，请手动填写中文图注。';
}
$('#crop-mode-box').onclick=()=>setCropMode(false);
$('#crop-mode-text').onclick=()=>guard(async()=>{if(!crop)return;setCropMode(true);if(crop.textPage!==crop.page)await loadCropText(crop,crop.page)});
$('#crop-text-layer').onmouseup=()=>{const selection=window.getSelection(),layer=$('#crop-text-layer');if(selection&&layer.contains(selection.anchorNode)&&layer.contains(selection.focusNode))$('#crop-source-caption').value=selection.toString().trim()};
$('#translate-crop-caption').onclick=()=>guard(async()=>{
 if(!crop)return;const editing=crop,page=editing.page,text=$('#crop-source-caption').value.trim(),before=$('#crop-caption').value,button=$('#translate-crop-caption');if(button.disabled)return;
 button.disabled=true;$('#crop-caption-status').textContent='正在翻译…';
 try{const result=await request('/api/crop-caption-translate',{id:editing.paperId,page,text});
  if(crop!==editing||editing.page!==page||$('#crop-source-caption').value.trim()!==text)return;
  if($('#crop-caption').value!==before){$('#crop-caption-status').textContent='已保留你刚刚手动修改的中文图注。';return}
  editing.sourceCaption=result.original;$('#crop-caption').value=result.translation;$('#crop-caption-status').textContent='已填入中文图注，可继续修改；点击保存后生效。';
 }catch(e){if(crop===editing)$('#crop-caption-status').textContent=e.message}
 finally{if(crop===editing)button.disabled=false}
});
function cropPageControls(page,total){
 $('#crop-prev-page').disabled=page<=1;$('#crop-next-page').disabled=page>=total;
}
async function loadCropPage(){
 if(!crop)return;
 const editing=crop,p=Number($('#crop-page').value),paper=state.papers.find(row=>row.id===editing.paperId),status=$('#crop-page-status');
 if(!paper||!Number.isInteger(p)||p<1||p>paper.page_count){status.hidden=false;status.textContent=`请输入 1–${paper?.page_count||1} 之间的整数页码`;return}
 const ticket=(editing.pageRequest||0)+1;editing.pageRequest=ticket;editing.targetPage=p;
 cropPageControls(p,paper.page_count);$('#save-crop').disabled=true;$('#crop-page-surface').setAttribute('aria-busy','true');
 status.hidden=false;status.textContent='正在加载第 '+p+' 页…';
 try{
  const img=new Image();
  await new Promise((resolve,reject)=>{img.onload=resolve;img.onerror=()=>reject(Error('页面加载失败，请重试'));img.src=scopedFile(`/files/${editing.paperId}/page-${p}.png`)});
  if(crop!==editing||editing.pageRequest!==ticket)return;
  const changed=editing.page!==p;editing.page=p;editing.image=img;editing.textPage=null;
  $('#crop-text-layer').innerHTML='';
  if(changed){$('#crop-source-caption').value='';$('#crop-caption-status').textContent='';editing.sourceCaption=null}
  const canvas=$('#crop-canvas');canvas.width=Math.min(740,img.width);canvas.height=img.height*canvas.width/img.width;$('#crop-page-surface').style.width=canvas.width+'px';drawCrop();
  if(changed)$('#crop-dialog .canvaswrap').scrollTop=0;
  status.hidden=true;
  if(!$('#crop-text-layer').hidden)await loadCropText(editing,p);
 }catch(e){
  if(crop!==editing||editing.pageRequest!==ticket)return;
  status.hidden=false;status.textContent=e.message;
  $('#crop-page').value=editing.page;editing.targetPage=editing.page;cropPageControls(editing.page,paper.page_count);
 }finally{
  if(crop===editing&&editing.pageRequest===ticket){$('#save-crop').disabled=!editing.image;$('#crop-page-surface').setAttribute('aria-busy','false')}
 }
}
function stepCropPage(delta){
 if(!crop)return;const max=Number($('#crop-page').max),page=Math.max(1,Math.min(max,(crop.targetPage||crop.page)+delta));
 $('#crop-page').value=page;return loadCropPage();
}
$('#crop-prev-page').onclick=()=>guard(()=>stepCropPage(-1));
$('#crop-next-page').onclick=()=>guard(()=>stepCropPage(1));
$('#crop-page').onkeydown=e=>{if(['ArrowUp','ArrowDown','Enter'].includes(e.key)){e.preventDefault();guard(()=>e.key==='Enter'?loadCropPage():stepCropPage(e.key==='ArrowUp'?-1:1))}};
function drawCrop(){const canvas=$('#crop-canvas'),ctx=canvas.getContext('2d');ctx.drawImage(crop.image,0,0,canvas.width,canvas.height);const b=crop.bbox;ctx.strokeStyle='#44765a';ctx.fillStyle='#739f6728';ctx.lineWidth=2;ctx.fillRect(b[0]*canvas.width,b[1]*canvas.height,(b[2]-b[0])*canvas.width,(b[3]-b[1])*canvas.height);ctx.strokeRect(b[0]*canvas.width,b[1]*canvas.height,(b[2]-b[0])*canvas.width,(b[3]-b[1])*canvas.height)}
const point=e=>{const r=$('#crop-canvas').getBoundingClientRect();return [Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))]};
$('#crop-canvas').onpointerdown=e=>{if(!crop?.image||$('#crop-page-surface').getAttribute('aria-busy')==='true')return;crop.start=point(e);$('#crop-canvas').setPointerCapture(e.pointerId)};
$('#crop-canvas').onpointermove=e=>{if(!crop?.start)return;const b=point(e),a=crop.start;crop.bbox=[Math.min(a[0],b[0]),Math.min(a[1],b[1]),Math.max(a[0],b[0]),Math.max(a[1],b[1])];drawCrop()};
$('#crop-canvas').onpointerup=()=>{if(crop)crop.start=null};
function cancelCrop(){if(crop?.saving)return;crop=null;$('#crop-dialog').close()}
$('#close-crop').onclick=cancelCrop;$('#cancel-crop').onclick=cancelCrop;
$('#crop-dialog').oncancel=e=>{if(crop?.saving)e.preventDefault();else crop=null};
$('#load-page').onclick=()=>guard(loadCropPage);
async function saveCrop(){
 const button=$('#save-crop');if(button.disabled||!crop)return;
 const editing=crop,paper=state.papers.find(p=>p.id===editing.paperId);
 if(!paper)throw Error('论文已移除，请重新打开阅读');
 let figs=paper.figures.map(f=>({...f}));
 const f={...(editing.figure||{}),page:editing.page,bbox:[...editing.bbox],caption:editing.sourceCaption||editing.figure?.caption||'用户选择的原文图表',caption_zh:$('#crop-caption').value.trim(),auto_crop:false,selected:editing.figure?.selected??true};
 if(editing.figure)figs=figs.map(v=>v.id===f.id?f:v);else figs.push(f);
 editing.saving=true;button.disabled=true;button.textContent='正在保存…';$('#cancel-crop').disabled=true;$('#close-crop').disabled=true;
 try{
  acceptPaperUpdate(await request('/api/paper-update',{id:paper.id,figures:figs}));
  const position=view==='paper'&&selected?.id===paper.id?ViewContinuity.capture($('#app')):null;
  if(crop===editing){$('#crop-dialog').close();crop=null}
  if(position)render(position);
  toast('裁剪与中文图注已更新；下载文件需重新导出');
 }finally{editing.saving=false;button.disabled=false;button.textContent='保存裁剪与图注';$('#cancel-crop').disabled=false;$('#close-crop').disabled=false}
}
$('#save-crop').onclick=()=>guard(saveCrop);
$('#sidebar-toggle').onclick=()=>{sidebarCollapsed=!sidebarCollapsed;try{localStorage.setItem('paperpilot-sidebar-collapsed',String(sidebarCollapsed))}catch{}applySidebar()};
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>setView(b.dataset.view));
$('#mainline-more').onclick=()=>setView('profile');
guard(async()=>{
 const legacyProfile=['#mainline','#research-chat'].includes(location.hash);
 await reload(false);
 restoreModelTask();
 const route=ReaderState.route(location.search,state.accounts?.active,state.papers||[]);
 if(route){view='paper';selected=state.papers?.find(p=>p.id===route.paperId)||null}
 else if(legacyProfile){view='profile';history.replaceState(null,'',location.pathname)}
 else{try{const saved=ReaderState.restore(sessionStorage,state.accounts?.active,state.papers||[]);if(saved){view=saved.view;selected=state.papers?.find(p=>p.id===saved.paperId)||null}}catch{}}
 render();
 if(route?.error)return;
 void openDailyHandoff();
 if(view==='hotspots')enterHotspots();
 for(const job of state.jobs.filter(j=>(!separateReader||j.paper_id===selected?.id)&&j.kind==='chat'&&['running','queued'].includes(j.status)&&j.question)){
  const pending={question:job.question,stopping:false,ready:Promise.resolve(job)};chatPending.set(job.paper_id,pending);void followPaperMessage(job.paper_id,pending);
 }
 if(chatPending.size)render();
 watchAnalyses();
 const pending=state.jobs.find(j=>(!separateReader||j.paper_id===selected?.id)&&!['analysis','chat','style-cache','ppt-style','knowledge-auto'].includes(j.kind)&&['running','queued'].includes(j.status));
 if(pending){
  if(pending.kind.startsWith('recommendation-'))await followModelJob(pending);
  else if(pending.kind==='title-search')await followTitleJob(pending);
  else await runJob(pending,{...navigationContext(),revision:-1});
 }
});

$('#close-delete').onclick=()=>$('#delete-dialog').close();
$('#confirm-delete').onclick=()=>guard(async()=>{const p=deleting;if(!p)return;$('#confirm-delete').disabled=true;try{await request('/api/paper-delete',{id:p.id,keep_history:$('#delete-dialog input:checked').value==='keep'});notesDrafts.delete(p.id);if(selected?.id===p.id){selected=null;view='library'}$('#delete-dialog').close();await reload();toast('已从论文库移除')}finally{$('#confirm-delete').disabled=false}});
window.addEventListener('beforeunload',event=>{if(notesDrafts.size||profileDirty||[...chatDrafts.values()].some(v=>v.trim())){event.preventDefault();event.returnValue=''}});

let deletingUser=null;
function openUsers(){deletingUser=null;$('#delete-user-area').hidden=true;$('#users-list').innerHTML=(state.accounts?.users||[]).map(u=>`<div class="user-row"><strong>${esc(u.name)}</strong>${u.id===state.accounts.active?'<span class="tag">当前用户</span>':`<button class="secondary" data-switch-user="${u.id}">切换</button>`}<button class="textbtn danger" data-delete-user="${u.id}">删除</button></div>`).join('');$('#users-list').querySelectorAll('[data-switch-user]').forEach(b=>b.onclick=()=>guard(async()=>{await request('/api/accounts/switch',{id:b.dataset.switchUser});accountReload();}));$('#users-list').querySelectorAll('[data-delete-user]').forEach(b=>b.onclick=()=>{deletingUser=state.accounts.users.find(u=>u.id===b.dataset.deleteUser);$('#delete-user-area').hidden=false;$('#delete-username').value='';$('#delete-username').placeholder=deletingUser.name;$('#delete-username').focus();});$('#users-dialog').showModal();}
$('#manage-users').onclick=openUsers;$('#close-users').onclick=()=>$('#users-dialog').close();
$('#create-user-form').onsubmit=e=>{e.preventDefault();guard(async()=>{await request('/api/accounts/create',{name:$('#new-username').value.trim()});accountReload();});};
$('#delete-user-confirm').onclick=()=>guard(async()=>{if(!deletingUser)return;await request('/api/accounts/delete',{id:deletingUser.id,name:$('#delete-username').value});accountReload();});
async function checkAccount(){if(!state?.accounts?.enabled)return;try{const a=await (await fetch('/api/session')).json();if(a.active!==state.accounts.active||a.revision!==state.accounts.revision)accountReload();}catch{}}
setInterval(checkAccount,5000);window.addEventListener('focus',checkAccount);document.addEventListener('visibilitychange',()=>{if(!document.hidden)checkAccount();});

let syncingReader=false;
async function syncReaderOnFocus(){
 if(!state||syncingReader||document.hidden||view!=='paper')return;
 syncingReader=true;
 try{const before=JSON.stringify(selected),context=navigationContext();await reload(false);watchAnalyses();if(stillAt(context)){if(JSON.stringify(selected)!==before)renderReaderUpdate();else if(selected)updateAnalysisUI(selected.id)}}catch{}finally{syncingReader=false}
}
window.addEventListener('focus',syncReaderOnFocus);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)void syncReaderOnFocus()});

function renderStyleSamples(){
 const mode=state.settings.math_style_mode||'cached';
 $('#style-mode-options').innerHTML=[['cached','提炼风格','复用规范与短片段，输入更精简'],['direct','现场阅读例文','直接参考原始摘录，保留更多细节']].map(([value,title,description])=>`<button type="button" class="style-mode-option ${mode===value?'selected':''}" data-style-mode="${value}" aria-pressed="${mode===value}"><strong>${title}</strong><small>${description}</small></button>`).join('');
 document.querySelectorAll('[data-style-mode]').forEach(el=>el.onclick=()=>updateStyleSamples(()=>request('/api/style-mode',{mode:el.dataset.styleMode})));
 const items=state.style_samples||[];
 $('#style-sample-list').innerHTML=items.length?items.map(item=>`<div class="style-sample-row"><label class="style-sample-label"><input type="checkbox" data-style-enable="${esc(item.id)}" ${item.enabled?'checked':''}><span><strong>${esc(item.name)}</strong><small>${item.pages?item.pages+' 页 · ':''}${item.full_text?'全部可提取文字': '全文分段选取'} · ${item.characters} 字符${!item.full_text&&item.source_characters?' / 原文 '+item.source_characters+' 字符':''}${item.pages?' · 参考 '+(item.selected_pages||[]).length+' 页':''}${item.extraction_error?' · '+esc(item.extraction_error):''}</small></span></label><button type="button" class="textbtn danger small" data-style-delete="${esc(item.id)}">移除</button></div>`).join(''):'<div class="style-sample-empty">尚未提供例文，将按通用教材式风格讲解。</div>';
 $('#style-sample-upload').disabled=items.length>=3;
 $('#style-sample-error').hidden=true;
 renderStyleCacheStatus();
 document.querySelectorAll('[data-style-enable]').forEach(el=>el.onchange=()=>updateStyleSamples(()=>request('/api/style-samples',{id:el.dataset.styleEnable,action:'enable',enabled:el.checked})));
 document.querySelectorAll('[data-style-delete]').forEach(el=>el.onclick=()=>updateStyleSamples(()=>request('/api/style-samples',{id:el.dataset.styleDelete,action:'delete'})));
}
async function updateStyleSamples(action){
 $('#style-sample-error').hidden=true;
 $('#style-samples-dialog').querySelectorAll('input,button:not(#close-style-samples)').forEach(el=>el.disabled=true);
 try{const result=await action();state.style_samples=result.items;if(result.mode)state.settings.math_style_mode=result.mode;state.style_cache=result.style_cache;renderStyleSamples();render();pollStyleCache()}
 catch(e){renderStyleSamples();$('#style-sample-error').textContent=e.message;$('#style-sample-error').hidden=false}
}
$('#close-style-samples').onclick=()=>$('#style-samples-dialog').close();
$('#style-samples-dialog').addEventListener('close',()=>clearTimeout(styleCacheTimer));
$('#style-sample-upload').onchange=()=>{
 const file=$('#style-sample-upload').files[0];if(!file)return;
 updateStyleSamples(async()=>{if(file.size>20*1024*1024)throw Error('参考例文最大支持 20 MB');return request('/api/style-samples/upload',file,true,{'X-Filename':encodeURIComponent(file.name)})});
 $('#style-sample-upload').value='';
};

let styleCacheTimer;
function renderStyleCacheStatus(){
 if(state.settings.math_style_mode==='direct'){$('#style-cache-state').textContent='数学精读直接使用例文摘录，不额外提炼风格';$('#retry-style-cache').hidden=true;return}
 const value=state.style_cache||{state:'stale'};
 const labels={empty:'未启用例文，使用通用教材式风格',ready:'风格规范已保存 · 切换模型也可复用',pending:'正在提炼风格规范…',stale:'尚未提炼风格规范',failed:'风格整理未完成，可重试'};
 $('#style-cache-state').textContent=labels[value.state]||labels.stale;
 const retry=$('#retry-style-cache');retry.hidden=!['stale','failed'].includes(value.state);retry.disabled=false;retry.textContent=value.state==='stale'?'提炼风格':'重试整理';
}
async function pollStyleCache(){
 clearTimeout(styleCacheTimer);
 if(state.settings.math_style_mode==='direct'){renderStyleCacheStatus();return}
 try{state.style_cache=await request('/api/style-cache');renderStyleCacheStatus()}
 catch(e){$('#style-cache-state').textContent=e.message;return}
 if($('#style-samples-dialog').open&&state.style_cache.state==='pending')styleCacheTimer=setTimeout(pollStyleCache,1800);
}
$('#retry-style-cache').onclick=()=>guard(async()=>{state.style_cache=await request('/api/style-cache',{});renderStyleCacheStatus();pollStyleCache()});

let pptStyleTimer,pptSourceId;
function renderPptSamples(){
 const mode=state.settings.ppt_style_mode||'cached';
 $('#ppt-mode-options').innerHTML=[['cached','提炼风格','复用叙述与版式规范'],['direct','现场阅读范例','每次参考原始文字与结构']].map(([value,title,description])=>`<button type="button" class="style-mode-option ${mode===value?'selected':''}" data-ppt-mode="${value}" aria-pressed="${mode===value}"><strong>${title}</strong><small>${description}</small></button>`).join('');
 const items=state.ppt_samples||[];
 $('#ppt-sample-list').innerHTML=items.length?items.map(item=>`<div class="style-sample-row"><label class="style-sample-label"><input type="checkbox" data-ppt-enable="${esc(item.id)}" ${item.enabled?'checked':''}><span><strong>${esc(item.name)}</strong><small>${item.slides} 页 · ${item.full_text?'全部可提取文字与结构':'全文分段参考'}</small></span></label><button type="button" class="textbtn danger small" data-ppt-delete="${esc(item.id)}">移除</button></div><div class="ppt-source-row"><span>${item.source_name?'对应原文：'+esc(item.source_name):'对应原文（选填）'}</span><button class="textbtn small" data-ppt-source="${esc(item.id)}">${item.source_name?'更换':'添加 PDF'}</button>${item.source_name?`<button class="textbtn small" data-ppt-source-delete="${esc(item.id)}">移除原文</button>`:''}</div>`).join(''):'<div class="style-sample-empty">已内置课堂讲解风格，可直接生成；添加范例后优先参考你的风格。</div>';
 $('#ppt-sample-upload').disabled=items.length>=3;$('#ppt-sample-error').hidden=true;renderPptStyleStatus();
 document.querySelectorAll('[data-ppt-mode]').forEach(b=>b.onclick=()=>updatePptSamples(()=>request('/api/ppt-mode',{mode:b.dataset.pptMode})));
 document.querySelectorAll('[data-ppt-enable]').forEach(b=>b.onchange=()=>updatePptSamples(()=>request('/api/ppt-samples',{id:b.dataset.pptEnable,action:'enable',enabled:b.checked})));
 document.querySelectorAll('[data-ppt-delete]').forEach(b=>b.onclick=()=>updatePptSamples(()=>request('/api/ppt-samples',{id:b.dataset.pptDelete,action:'delete'})));
 document.querySelectorAll('[data-ppt-source]').forEach(b=>b.onclick=()=>{pptSourceId=b.dataset.pptSource;$('#ppt-source-upload').click()});
 document.querySelectorAll('[data-ppt-source-delete]').forEach(b=>b.onclick=()=>updatePptSamples(()=>request('/api/ppt-samples',{id:b.dataset.pptSourceDelete,action:'source-delete'})));
}
async function updatePptSamples(action){
 $('#ppt-samples-dialog').querySelectorAll('input,button:not(#close-ppt-samples)').forEach(el=>el.disabled=true);
 try{const result=await action();state.ppt_samples=result.items;state.ppt_style=result.style_cache;if(result.mode)state.settings.ppt_style_mode=result.mode;renderPptSamples();render();pollPptStyle()}
 catch(e){renderPptSamples();$('#ppt-sample-error').hidden=false;$('#ppt-sample-error').textContent=e.message}
 finally{$('#ppt-source-upload').disabled=false}
}
function renderPptStyleStatus(){
 const direct=state.settings.ppt_style_mode==='direct',value=state.ppt_style?.state||'empty';
 $('#ppt-style-state').textContent=value==='empty'?'使用内置讲解风格':direct?'生成时直接参考范例文字与版式结构':({ready:'PPT 风格已保存 · 切换模型也可复用',pending:'正在提炼 PPT 风格…',stale:'尚未提炼 PPT 风格',failed:'整理未完成，可重试'}[value]);
 $('#retry-ppt-style').hidden=direct||!['failed','stale'].includes(value);$('#retry-ppt-style').disabled=false;
}
async function pollPptStyle(){
 clearTimeout(pptStyleTimer);if(state.settings.ppt_style_mode==='direct')return;
 try{state.ppt_style=await request('/api/ppt-style');renderPptStyleStatus();if($('#ppt-samples-dialog').open&&state.ppt_style.state==='pending')pptStyleTimer=setTimeout(pollPptStyle,1800)}catch(e){$('#ppt-style-state').textContent=e.message}
}
$('#close-ppt-samples').onclick=()=>$('#ppt-samples-dialog').close();$('#ppt-samples-dialog').addEventListener('close',()=>clearTimeout(pptStyleTimer));
$('#retry-ppt-style').onclick=()=>updatePptSamples(()=>request('/api/ppt-style',{}));
$('#ppt-sample-upload').onchange=()=>{const file=$('#ppt-sample-upload').files[0];if(file)updatePptSamples(()=>request('/api/ppt-samples/upload',file,true,{'X-Filename':encodeURIComponent(file.name)}));$('#ppt-sample-upload').value=''};
$('#ppt-source-upload').onchange=()=>{const file=$('#ppt-source-upload').files[0];if(file)updatePptSamples(()=>request('/api/ppt-samples/source',file,true,{'X-Filename':encodeURIComponent(file.name),'X-Sample-Id':pptSourceId}));$('#ppt-source-upload').value=''};

$('#model-setup-close').onclick=$('#model-setup-done').onclick=()=>$('#model-setup-dialog').close();
$('#model-setup-copy').onclick=()=>guard(async()=>{await navigator.clipboard.writeText($('#model-setup-instruction').value);toast('已复制，可粘贴给 Codex 或 dsh')});
