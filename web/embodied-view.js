/* Public discovery content in, personal reading choices stay in PaperPilot. */
let paperFeed='embodied',embodiedResult=null,embodiedLoading=false,embodiedError='',embodiedDate='',embodiedRequest=0;
function embodiedToday(){return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())}
function embodiedCard(p,runId){
 const ref=cardRefs.push({paper:p,origin:'embodied-daily',runId})-1;
 const saved=(state.favorites||[]).find(f=>f.paper.paper_url===p.paper_url);
 return `<article class="rec-card embodied-paper" data-view-anchor="embodied-${esc(p.id)}"><h3><a href="${esc(p.reading_url)}" target="_blank" rel="noopener noreferrer">${esc(p.title)} ↗</a></h3>${p.summary?`<details class="embodied-summary"><summary>一句话概括${p.reading_ready?'':' · 摘要预览'}</summary><p>${esc(p.summary)}</p></details>`:''}<div class="row card-actions"><button class="secondary" data-save-card="${ref}" ${saved?'disabled':''}>${saved?'已加入待读清单':'加入待读清单'}</button><button class="textbtn" data-import="${esc(p.paper_url)}" ${saved?`data-import-favorite="${esc(saved.id)}"`:''} data-task>导入阅读</button>${hotspotSkipButton(p,'embodied-daily',runId)}</div></article>`;
}
function embodiedPanel(){
 const day=embodiedDate||embodiedToday(),result=embodiedResult?.day===day?embodiedResult:null;
 const items=(result?.items||[]).filter(p=>!hotspotIsSkipped(p));
 return `<section class="panel"><div class="section-head"><h2 class="hotspot-section-title"><a href="${esc(state.embodied_daily?.home||'https://ipplab.github.io/embodied-ai-daily-papers/?lang=zh')}" target="_blank" rel="noopener noreferrer">具身日报 ↗</a></h2><div class="row"><input id="embodied-date" type="date" aria-label="日报日期" value="${esc(day)}" max="${embodiedToday()}"><button id="embodied-refresh" class="textbtn" ${embodiedLoading?'disabled':''}>${embodiedLoading?'读取中…':'刷新'}</button></div></div>${embodiedError||result?.error?`<p class="error" role="status">${esc(embodiedError||result.error)}</p>`:''}<div class="daily-list" data-scroll-key="embodied-${esc(day)}">${items.map(p=>embodiedCard(p,result.id)).join('')||`<p class="muted">${embodiedLoading?'正在读取…':result?'当天暂无待浏览论文。':'尚未读取日报。'}</p>`}</div></section>`;
}
async function refreshEmbodied(){
 const seq=++embodiedRequest,day=embodiedDate||embodiedToday();embodiedLoading=true;embodiedError='';
 if(view==='hotspots')render();
 try{const result=await request('/api/embodied-daily?'+new URLSearchParams({date:day}));if(seq===embodiedRequest)embodiedResult=result}
 catch(e){if(seq===embodiedRequest)embodiedError=e.message}
 finally{if(seq===embodiedRequest){embodiedLoading=false;if(view==='hotspots')render()}}
}
function enterHotspots(){
 if(paperFeed==='embodied')void refreshEmbodied();
}
function bindEmbodied(){
 if($('#paper-feed'))$('#paper-feed').onchange=e=>{paperFeed=e.target.value;render();enterHotspots()};
 if($('#embodied-date'))$('#embodied-date').onchange=e=>{embodiedDate=e.target.value||embodiedToday();void refreshEmbodied()};
 if($('#embodied-refresh'))$('#embodied-refresh').onclick=()=>void refreshEmbodied();
}
async function openDailyHandoff(){
 const params=new URLSearchParams(location.search),id=params.get('daily-paper');
 if(!id)return;
 // Navigation only previews; writing always requires an explicit local click.
 if(state.accounts?.enabled&&!state.accounts.active)return;
 try{
  const result=await request('/api/embodied-paper?'+new URLSearchParams({id}));
  const p=result.items[0];
  const dialog=document.createElement('dialog');dialog.className='daily-handoff';
  dialog.innerHTML=`<div class="section-head"><h2>加入待读清单</h2><button class="textbtn" data-close>取消</button></div><h3>${esc(p.title)}</h3>${p.summary?`<p>${esc(p.summary)}</p>`:''}<p class="small muted">保存到 ${esc(state.accounts.users.find(u=>u.id===state.accounts.active)?.name||'当前用户')}</p><p class="error" role="status"></p><button class="primary" data-confirm>加入待读清单</button>`;
  document.body.append(dialog);dialog.onclose=()=>{dialog.remove();params.delete('daily-paper');history.replaceState(null,'',location.pathname+(params.size?'?'+params:'')+location.hash)};
  dialog.querySelector('[data-close]').onclick=()=>dialog.close();
  dialog.querySelector('[data-confirm]').onclick=async e=>{const b=e.currentTarget;b.disabled=true;try{await request('/api/favorite',{origin:'embodied-daily',run_id:result.id,paper_id:p.id});await reload(false);dialog.close();render();toast('已加入待读清单')}catch(err){dialog.querySelector('[role=status]').textContent=err.message;b.disabled=false}};
  dialog.showModal();
 }catch(e){toast(e.message,true)}
}
