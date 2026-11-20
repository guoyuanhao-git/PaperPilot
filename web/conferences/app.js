import * as Rules from './logic.mjs';
export async function mount(root,api){
const html=await fetch('/conferences/page.html').then(r=>r.text());if(!root.host.isConnected)return ()=>{};root.innerHTML='<link rel="stylesheet" href="/conferences/style.css">'+html;
let classifications={directories:{},entries:{}},catalog=null,conferences=[],fetchFailed=false,activeJob=null,config={enabled:false},disposed=false;
const $ = id => root.getElementById(id);
const esc = text => String(text ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let focusId = null, direction = '全部';

function rating(c,key){return classifications.entries[c.id]?.[key]||{grade:null,page:null};}
function ratingText(c,key){const grade=rating(c,key).grade;return `${classifications.directories[key]?.label||key.toUpperCase()} ${grade==='N'?'未收录':grade||'待核实'}`;}
function ratingBadges(c,hero=false){
 return `<span class="rating-badges${hero?' hero-ratings':''}">${['ccf','th'].map(key=>{
  const grade=rating(c,key).grade,text=`${key.toUpperCase()}-${grade||'?'}`;
  const title=`${ratingText(c,key)} · ${classifications.directories[key]?.version||'版本待核实'} · N 表示本版未收录，? 表示待核实 · 查看依据`;
  return `<button class="rating ${['A','B','C'].includes(grade)?'':'unlisted'}" data-detail="${c.id}" title="${esc(title)}">${esc(text)}</button>`;
 }).join('')}</span>`;
}
function ratingSources(c){return `<section class="rating-sources"><h3>分类目录</h3>${Object.entries(classifications.directories).map(([key,d])=>{
 const entry=c?rating(c,key):null,page=entry?.page;
 const detail=entry?(entry.grade==='N'?'本版未收录':entry.grade?`${entry.grade} 类 · 第 ${page} 页`:'尚未核实此会议'):'';
 return `<div class="rating-source"><div><strong>${esc(d.label==='TH'?'TH-CPL':d.label)}</strong><span>${esc(d.version)}</span></div>${detail?`<p>${esc(detail)}</p>`:''}<p>${esc(d.name)}</p><div class="rating-links"><a href="${esc(d.source)}" target="_blank" rel="noopener">${d.source===d.document?'查看目录':'官方来源'} ↗</a>${d.source!==d.document?`<a href="${esc(d.document)}${page?'#page='+page:''}" target="_blank" rel="noopener">${esc(d.documentLabel)} ↗</a>`:''}<span>核对于 ${esc(d.checked)}</span></div></div>`;
 }).join('')}<p class="rating-note">两套分类独立展示；未收录不代表较低等级。采用上述目录版本，不随会议届次变化。</p></section>`;}
function current(){return catalog.series.map(x=>Rules.selected(x));}
function closed(c){return Rules.isClosed(c);}
function heroConference(){return Rules.hero(conferences,focusId);}
function label(c,k) { return c[k+'Label'] || (k==='abstract'?'摘要截止':'全文截止'); }
function timeText(c,k) {
 if(!c[k]) return c[k+'Day'] ? `${c[k+'Day'].replaceAll('-','.')}<small>时区待核</small>` : esc(c[k+'Text'] || (c.checked?'官网未列日期':'待核查'));
 const selected=$('zone').value, zone=selected==='official'?c.zone:selected;
 const parts=new Intl.DateTimeFormat('en-CA',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(c[k]));
 const get=t=>parts.find(p=>p.type===t).value;
 return `${get('year')}.${get('month')}.${get('day')}<small>${get('hour')}:${get('minute')}${selected==='official'?' '+esc(c.zoneLabel):''}</small>`;
}
function status(c){
 const p=Rules.phase(c),node=Rules.nextNode(c);
 if(p==='upcoming')return {cls:'',text:node.precise?`${label(c,node.key)} · ${Rules.daysUntil(node.end)} 天后`:'首次投稿日期已列出 · 时区待核'};
 if(p==='uncertain')return {cls:'partial',text:'已临近官方截止日 · 时刻待核'};
 if(p==='followup')return {cls:'closed',text:c.paperAudience==='invited'?'首轮已截止 · 仅限获邀作者':'摘要已截止 · 仅限已注册作者'};
 if(p==='closed')return {cls:'closed',text:'本届投稿已截止'};
 return {cls:'pending',text:c.announcement==='cfp'?'已有征稿 · 截止待核':'投稿日期未公布 / 未核实'};
}
function renderHero() {
 const c=heroConference(); if(!c){$('spotlight').innerHTML='<div class="hero-title">等待下一次投稿机会</div><p class="hero-subtitle">暂无已核实的未来截止，会议日期请查看下方卡片。</p>';return;}
 $('spotlight').classList.toggle('is-closed',closed(c));
 const selected=c.id===focusId,n=Rules.nextNode(c),s=status(c);
 const count=n&&n.precise?`<strong>${Rules.daysUntil(n.end)}</strong><span>天</span><small>${n.audience==='first'?'距离':n.audience==='invited'?'仅获邀作者 · ':'仅已注册作者 · '}${esc(label(c,n.key))}</small>`:`<strong class="text-state">${closed(c)?'已截止':n?'时刻待核':'日期未列'}</strong><small>${n?'官方日期 '+esc(c[n.key+'Day']||''):closed(c)?'首次投稿入口已截止':'所查官网未列投稿日期'}</small>`;
 $('spotlight').innerHTML=`<div class="spotlight-top"><span>${selected?'★ 重点关注':'◷ 最近截稿'}</span><button class="hero-control" data-focus="${c.id}" aria-pressed="${selected}">${selected?'取消关注':'☆ 关注此会议'}</button></div><div class="hero-content"><div><div class="hero-title">${esc(c.name)}<span class="year">${c.year}</span>${ratingBadges(c,true)}</div><p class="hero-subtitle">${esc(c.topics)}</p></div><div class="countdown">${count}</div></div><div class="hero-bottom"><span>${esc(label(c,'abstract'))}<b>${timeText(c,'abstract')}</b></span><span>${esc(label(c,'paper'))}<b>${timeText(c,'paper')}</b></span><a href="${esc(c.source)}" target="_blank" rel="noopener">查看官网 ↗</a></div>${closed(c)?`<div class="hero-note">${esc(Rules.nextEditionNote(c))}</div>`:c.paperAudience==='invited'?'<div class="hero-note">两阶段投稿：6 页扩展摘要 → 获邀后提交最终全文</div>':''}`;
}
function renderCards() {
 const query=$('search').value.trim().toLowerCase();
 const list=conferences.filter(c=>(direction==='全部'||c.group===direction)&&(!query||`${c.name} ${c.topics} ${c.group} ${ratingText(c,'ccf')} ${ratingText(c,'th')} CCF-${rating(c,'ccf').grade||''}`.toLowerCase().includes(query))&&(!$('hide-past').checked||!closed(c))).sort((a,b)=>Rules.compare(a,b,focusId));
 $('count').textContent=`${list.length} / ${conferences.length}`; $('empty').hidden=!!list.length;
 const cardsHTML=list.map(c=>{const s=status(c),saved=c.id===focusId;return `<article class="card ${closed(c)?'is-closed':''} ${saved?'focused':''}" data-series="${c.id}" data-group="${esc(c.group)}"><div class="card-top"><span class="conference-icon" aria-hidden="true">${c.group==='机器人'?'⌘':c.group==='视觉与多模态'?'◈':'∿'}</span><span class="conference-name">${esc(c.name)}<span class="year">${c.year}</span></span><button class="star ${saved?'saved':''}" data-focus="${c.id}" aria-label="${saved?'取消关注':'关注'} ${esc(c.name)}" aria-pressed="${saved}" title="${saved?'取消关注':'设为唯一关注会议'}">${saved?'★':'☆'}</button></div><p class="card-subtitle">${esc(c.topics)}</p><div class="conference-tags">${ratingBadges(c)}<span class="tag direction-tag">${esc(c.group)}</span></div><div class="dates">${['abstract','paper'].map(k=>`<div class="date-row ${!c[k]&&!c[k+'Day']?'pending':''}"><span>${esc(label(c,k))}</span><b>${timeText(c,k)}</b></div>`).join('')}</div><div class="card-bottom"><span class="status ${s.cls}">● ${s.text}</span><button class="source-link" data-detail="${c.id}">历届与来源 ↗</button></div>${closed(c)?`<div class="special">${esc(Rules.nextEditionNote(c))}</div>`:c.paperAudience==='invited'?'<div class="special">两阶段投稿 · 最终全文仅限获邀作者</div>':''}${['failed','conflict'].includes(c.verification)?'<div class="special">官方信息需复核 · 已保留原日期</div>':''}</article>`}).join('');
 if($('cards').innerHTML!==cardsHTML)$('cards').innerHTML=cardsHTML;
}
function render(){
 if(!catalog)return;
 const anchor=[...root.querySelectorAll('#cards [data-series]')].find(el=>el.getBoundingClientRect().bottom>0),top=anchor?.getBoundingClientRect().top;
 const keep=anchor&&top<window.innerHeight&&window.scrollY>0&&!root.querySelector('dialog[open]');
 $('spotlight').className='spotlight';conferences=current();renderHero();renderCards();updateMeta();
 if(keep){const next=root.querySelector(`#cards [data-series="${anchor.dataset.series}"]`);if(next)window.scrollBy(0,next.getBoundingClientRect().top-top);}
}
let focusBusy=false;
async function setFocus(id){if(focusBusy)return;focusBusy=true;try{const result=await api.request('/api/conferences/focus',{series_id:focusId===id?null:id});focusId=result.focus;render();}catch(e){toast(e.message)}finally{focusBusy=false}}
let toastTimer;
function toast(text){$('toast').textContent=text;$('toast').classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').classList.remove('show'),2400);}
function showDetail(id,year){
 const series=catalog.series.find(c=>c.id===id);const shown=conferences.find(c=>c.id===id);const edition=series.editions.find(e=>e.year===Number(year))||shown;const c={...series,...edition};
 $('detail-title').textContent=`${c.name} ${c.year}`;
 $('detail-body').innerHTML=`<label class="edition-select">保存的届次 <select id="detail-year" aria-label="查看会议届次">${[...series.editions].sort((a,b)=>b.year-a.year).map(e=>`<option value="${e.year}" ${e.year===c.year?'selected':''}>${e.year}${e.year===shown.year?' · 当前展示':''}${e.announcement==='unverified'?' · 待核实':e.announcement==='meeting'?' · 仅公布会期':''}</option>`).join('')}</select></label><p>${esc(c.topics)} · ${esc(c.track||'研究论文')}</p><div class="dates">${['abstract','paper'].map(k=>`<div class="date-row"><span>${esc(label(c,k))}</span><b>${timeText(c,k)}</b></div>`).join('')}</div><p>${esc(c.note||'官方已列出投稿日期，请在投稿前核对最新通知。')}</p><p>${esc(status(c).text)}。${c.paperAudience==='invited'?'全文阶段仅面向获邀作者。':c.paperAudience==='registered'?'摘要注册截止后，全文阶段仅面向已注册作者。':''}</p><p>最近成功核查：${esc(c.checked||'尚未核查')}${c.verification==='failed'?' · 最近访问失败，保留原记录':c.verification==='conflict'?' · 存在冲突，待复核':''}。</p><p><a href="${esc(c.source)}" target="_blank" rel="noopener">打开官方来源 ↗</a></p>${c.sourceProofs?.length?`<details><summary>核查依据</summary>${c.sourceProofs.map(p=>`<p>${esc(p.quote)}<br><a href="${esc(p.url)}" target="_blank" rel="noopener">官方原文 ↗</a></p>`).join('')}</details>`:''}`;
 $('detail-body').insertAdjacentHTML('beforeend',ratingSources(c));
 $('detail-year').addEventListener('change',e=>showDetail(id,e.target.value));if(!$('details').open)$('details').showModal();
}
function localDate(value){return value?new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'尚未执行';}
let lastHistoryHTML='';
function updateMeta(){
 const schedule='每周日 10:00 · 北京时间';
 const sourcesHTML=ratingSources();if($('ranking-sources').innerHTML!==sourcesHTML)$('ranking-sources').innerHTML=sourcesHTML;
 $('auto-check').checked=!!config.enabled;
 const last=catalog.updates.find(x=>x.kind==='check');const failed=last?.checks?.some(x=>['failed','conflict'].includes(x.outcome));
 $('update-status').textContent=activeJob?activeJob.progress:fetchFailed?'本次核查未成功，已保留现有资料':`最近核查：${localDate(catalog.lastRunAt)}${failed?' · 部分来源需复核':''}`;
 $('refresh-catalog').textContent=activeJob?'核查中…':'核查官网';
 $('refresh-catalog').disabled=!!activeJob;
 $('schedule-status').textContent=schedule;
 const historyHTML='<h3>最近核查记录</h3>'+catalog.updates.slice(0,5).map(x=>`<p>${esc(localDate(x.at))}<br>${esc(x.summary)}${x.checks?.length?`<br>已记录 ${x.checks.length} 项核查，失败 / 冲突 ${x.checks.filter(c=>['failed','conflict'].includes(c.outcome)).length} 项`:''}</p>${x.checks?.length?`<details><summary>查看核查详情</summary>${x.checks.map(c=>`<p>${esc(c.id.toUpperCase())} ${c.year} · ${esc(c.summary)}</p>`).join('')}</details>`:''}`).join('');
 if(lastHistoryHTML!==historyHTML){$('update-history').innerHTML=historyHTML;lastHistoryHTML=historyHTML;}
}
let loading=false;
async function loadCatalog(){
 if(loading)return;loading=true;$('refresh-catalog').disabled=true;
 try{const result=await api.request('/api/conferences');if(!root.host.isConnected)return;const changed=!catalog||catalog.revision!==result.catalog?.revision||focusId!==result.focus||JSON.stringify(classifications)!==JSON.stringify(result.classifications);classifications=result.classifications||{directories:{},entries:{}};catalog=result.catalog;fetchFailed=!!result.error;focusId=result.focus;activeJob=result.job;config=result.schedule;
 if(catalog){conferences=current();if(focusId&&!conferences.some(c=>c.id===focusId))focusId=null;if(changed)render();else updateMeta();}
 else{$('spotlight').className='empty-source';$('spotlight').innerHTML='<h2>会议目录暂不可用</h2>'; }
 }catch(e){fetchFailed=true;if(catalog)updateMeta();else $('update-status').textContent=e.message;}
 finally{loading=false;$('refresh-catalog').disabled=!!activeJob;}
}
root.addEventListener('click',async event=>{const focus=event.target.closest('[data-focus]');if(focus){const region=focus.closest('#spotlight')?'spotlight':'cards',id=focus.dataset.focus;await setFocus(id);$(region).querySelector(`[data-focus="${id}"]`)?.focus();}const detail=event.target.closest('[data-detail]');if(detail)showDetail(detail.dataset.detail);});
$('filters').addEventListener('click',event=>{const b=event.target.closest('[data-filter]');if(!b)return;direction=b.dataset.filter;root.querySelectorAll('[data-filter]').forEach(el=>{el.classList.toggle('selected',el===b);el.setAttribute('aria-pressed',el===b?'true':'false');});renderCards();});
$('search').addEventListener('input',renderCards);$('hide-past').addEventListener('change',renderCards);$('zone').addEventListener('change',render);$('about').addEventListener('click',()=>$('about-dialog').showModal());
root.querySelectorAll('dialog').forEach(d=>{d.querySelector('.close').addEventListener('click',()=>d.close());d.addEventListener('click',e=>{if(e.target===d){const r=d.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)d.close();}});});
$('refresh-catalog').onclick=()=>$('check-confirm').showModal();
$('check-cancel').onclick=()=>$('check-confirm').close();
$('check-start').onclick=async()=>{const button=$('check-start');button.disabled=true;try{activeJob=await api.request('/api/conferences/check',{});$('check-confirm').close();await loadCatalog();}catch(e){toast(e.message)}finally{button.disabled=false;}};
$('auto-check').onchange=async e=>{const checked=e.target.checked;e.target.disabled=true;try{await api.request('/api/conferences/schedule',{enabled:checked});config.enabled=checked;}catch(error){e.target.checked=!checked;toast(error.message)}finally{e.target.disabled=false;}};
$('catalog-upload').onchange=async e=>{const file=e.target.files[0];if(!file)return;try{if(file.size>2097152)throw Error('目录文件过大');const value=JSON.parse(await file.text());await api.request('/api/conferences/import',{catalog:value});$('catalog-error').textContent='';await loadCatalog();toast('会议目录已更新');}catch(error){$('catalog-error').textContent=error.message;}finally{e.target.value='';}};
await loadCatalog();const minute=setInterval(render,60000),refresh=setInterval(loadCatalog,300000),poll=setInterval(()=>{if(activeJob&&!disposed)loadCatalog()},4000);
return ()=>{disposed=true;clearInterval(poll);clearInterval(minute);clearInterval(refresh);clearTimeout(toastTimer);};
}
