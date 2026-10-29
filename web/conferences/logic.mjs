const DAY=86400000;
// Date-only cutoffs span all civil time zones; never invent a precise instant.
export function bounds(e,key){
 if(e[key]){const t=Date.parse(e[key]);return {start:t,end:t,sort:t,precise:true};}
 if(e[key+'Day']){const t=Date.parse(e[key+'Day']+'T00:00:00Z');return {start:t-14*3600000,end:t+36*3600000,sort:t,precise:false};}
 return null;
}
export function entry(e){return e.entryKey?bounds(e,e.entryKey):null;}
export function phase(e,now=Date.now()){
 const first=entry(e),last=bounds(e,'paper');
 if(first&&now<first.start)return 'upcoming';
 if(first&&!first.precise&&now<=first.end)return 'uncertain';
 if(first&&now>=(first.precise?first.end:first.end+1))return last&&now<last.end?'followup':'closed';
 if(last&&now>last.end)return 'closed';
 return 'pending';
}
export function isClosed(e,now=Date.now()){return ['closed','followup'].includes(phase(e,now));}
export function closureTime(e){return entry(e)?.sort??bounds(e,'paper')?.sort??0;}
export function chooseEdition(series,now=Date.now()){
 const editions=[...series.editions].sort((a,b)=>a.year-b.year);
 const viable=editions.filter(e=>['upcoming','uncertain'].includes(phase(e,now))&&e.announcement==='cfp');
 if(viable.length)return viable[0];
 const announced=editions.filter(e=>e.announcement==='cfp');
 return announced.at(-1)||editions.at(-1);
}
export function selected(series,now=Date.now()){const edition=chooseEdition(series,now);return {...series,...edition,editions:series.editions};}
export function nextEditionNote(c,now=Date.now()){
 if(!isClosed(c,now))return '';
 const next=c.editions.filter(e=>e.year>c.year).sort((a,b)=>a.year-b.year)[0];
 if(next)return next.announcement==='meeting'?`${next.year} 已公布会期，投稿日期未列出`:`${next.year} 征稿日期尚未核实`;
 return '本届新投稿已截止，下届日期待核实';
}
export function compare(a,b,focusId,now=Date.now()){
 if(a.id===focusId&&b.id!==focusId)return -1;if(b.id===focusId&&a.id!==focusId)return 1;
 const order=e=>['upcoming','uncertain'].includes(phase(e,now))?0:phase(e,now)==='pending'?1:2;
 const diff=order(a)-order(b);if(diff)return diff;
 if(order(a)===0)return (entry(a)?.sort??Infinity)-(entry(b)?.sort??Infinity)||a.name.localeCompare(b.name);
 if(order(a)===2)return closureTime(b)-closureTime(a)||a.name.localeCompare(b.name);
 return a.name.localeCompare(b.name);
}
export function hero(list,focusId,now=Date.now()){
 return list.find(c=>c.id===focusId)||list.filter(e=>['upcoming','uncertain'].includes(phase(e,now))).sort((a,b)=>compare(a,b,null,now))[0]||null;
}
export function nextNode(e,now=Date.now()){
 const p=phase(e,now);if(['upcoming','uncertain'].includes(p))return {key:e.entryKey,...entry(e),audience:'first'};
 const paper=bounds(e,'paper');if(p==='followup'&&paper)return {key:'paper',...paper,audience:e.paperAudience==='invited'?'invited':'registered'};
 return null;
}
export function daysUntil(t,now=Date.now()){return Math.max(0,Math.ceil((t-now)/DAY));}
