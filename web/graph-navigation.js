/* View-only backbone. Never invent, delete, or rewrite saved relationships. */
(function(root){
 const key=e=>[e.source,e.target].sort().join('|');
 function clean(nodes,edges){
  const ids=new Set(nodes.map(n=>n.id)),seen=new Set();
  return edges.filter(e=>{const k=key(e);if(e.source===e.target||!ids.has(e.source)||!ids.has(e.target)||seen.has(k))return false;seen.add(k);return true});
 }
 function rank(edges,nodes,primary){
  const byId=new Map(nodes.map(n=>[n.id,n]));
  const value=e=>(primary?.has(key(e))?100:0)+(e.priority||1)*20+Math.min(byId.get(e.source)?.relevance||0,byId.get(e.target)?.relevance||0);
  return [...edges].sort((a,b)=>value(b)-value(a)||key(a).localeCompare(key(b)));
 }
 function forest(nodes,edges){
  const parent=new Map(nodes.map(n=>[n.id,n.id]));
  const find=id=>{let v=id;while(parent.get(v)!==v)v=parent.get(v);while(id!==v){const next=parent.get(id);parent.set(id,v);id=next;}return v};
  return edges.filter(e=>{const a=find(e.source),b=find(e.target);if(a===b)return false;parent.set(a,b);return true});
 }
 function backbone(nodes,edges,pairs){
  const primary=Array.isArray(pairs)?new Set(pairs):null;
  const eligible=edges.filter(e=>primary?primary.has(key(e)):(e.priority||1)>=2);
  // Legacy graphs have no model comparisons. A maximum-weight forest is a
  // conservative display fallback, not a claim that alternative paths mean the same thing.
  return primary?rank(eligible,nodes,primary):forest(nodes,rank(eligible,nodes));
 }
 function sparse(nodes,edges,seed=[]){
  const ordered=rank(edges,nodes),kept=new Set(seed.map(key));
  const result=[...seed];
  // A display budget, never a degree cap: preserve the overview and add the
  // strongest independent routes; all omitted evidence remains in focus.
  for(const e of forest(nodes,[...seed,...ordered]))if(!kept.has(key(e))){result.push(e);kept.add(key(e))}
  const budget=Math.max(seed.length,Math.ceil(nodes.length*1.5));
  for(const e of ordered){if(result.length>=budget)break;if(e.priority===3&&!kept.has(key(e))){result.push(e);kept.add(key(e))}}
  return result;
 }
 function plan(nodes,raw,options={}){
  const edges=clean(nodes,raw),primary=Array.isArray(options.pairs)?new Set(options.pairs):null;
  const core=backbone(nodes,edges,options.pairs),byId=new Map(nodes.map(n=>[n.id,n]));
  if(options.focus&&byId.has(options.focus)){
   const adjacent=rank(edges.filter(e=>e.source===options.focus||e.target===options.focus),nodes,primary);
   const shown=adjacent.slice(0,options.limit||6),ids=new Set([options.focus,...shown.flatMap(e=>[e.source,e.target])]);
   return {nodes:nodes.filter(n=>ids.has(n.id)),edges:shown,totalRelations:adjacent.length,hidden:nodes.length-ids.size,mode:'focus'};
  }
  const query=(options.query||'').trim().toLocaleLowerCase();
  if(query){
   const matches=nodes.filter(n=>(n.label+' '+n.title+' '+(n.tags||[]).join(' ')).toLocaleLowerCase().includes(query)),ids=new Set(matches.map(n=>n.id));
   const allowed=core.filter(e=>{
    if(!ids.has(e.source)||!ids.has(e.target))return false;
    const a=byId.get(e.source),b=byId.get(e.target);
    return options.scope==='starred'?a.starred||b.starred:a.starred||a.liked||b.starred||b.liked;
   });
   return {nodes:matches,edges:sparse(matches,allowed),hidden:nodes.length-matches.length,mode:'search'};
  }
  const isCore=n=>!!(n.starred||n.liked),isRelevant=n=>!Number.isInteger(n.relevance)||n.relevance>=2;
  const domain=options.scope==='starred';
  let overview=domain?nodes.filter(n=>n.starred):nodes.filter(n=>isCore(n)&&isRelevant(n));
  // With no favorites, keep the long-term map useful using representative likes.
  if(domain&&!overview.length)overview=[...nodes].filter(n=>n.liked).sort((a,b)=>(b.relevance||0)-(a.relevance||0)||a.id.localeCompare(b.id)).slice(0,12);
  const selected=options.all?(domain?nodes:nodes.filter(isRelevant)):overview;
  const ids=new Set(selected.map(n=>n.id)),baseIds=new Set(overview.map(n=>n.id));
  // Preserve the overview skeleton when expanding. Lower-tier links remain in
  // raw data for focus/search; never manufacture a link to connect an island.
  const base=sparse(overview,core.filter(e=>baseIds.has(e.source)&&baseIds.has(e.target)));
  const additions=options.all?core.filter(e=>{
   if(!ids.has(e.source)||!ids.has(e.target)||baseIds.has(e.source)&&baseIds.has(e.target))return false;
   const a=byId.get(e.source),b=byId.get(e.target);
   return domain?!!(a.starred||b.starred):isCore(a)||isCore(b);
  }):[];
  return {nodes:selected,edges:options.all?sparse(selected,additions,base):base,hidden:nodes.length-selected.length,mode:options.all?'all':'overview'};
 }
 const api={key,clean,backbone,plan};if(typeof module!=='undefined')module.exports=api;else root.GraphNavigation=api;
})(globalThis);
