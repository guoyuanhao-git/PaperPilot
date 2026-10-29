/* Browser-tab navigation state contains IDs only, isolated by local user. */
(function(root){
 const key=user=>'paperpilot-view:'+encodeURIComponent(user||'local');
 const views=new Set(['library','paper','knowledge','hotspots','discover','profile','settings','conferences']);
 function save(storage,user,view,paperId){
  try{if(views.has(view))storage.setItem(key(user),JSON.stringify({view,paperId:view==='paper'?paperId:null}))}catch{}
 }
 function restore(storage,user,papers){
  try{
   const saved=JSON.parse(storage.getItem(key(user))||'null');
   if(!saved||!views.has(saved.view))return null;
   if(saved.view==='paper'&&!papers.some(p=>p.id===saved.paperId))return {view:'library',paperId:null};
   return saved;
  }catch{return null}
 }
 function figureUrl(paperId,figure,report=false){
  const query=new URLSearchParams({crop:JSON.stringify([figure.page,figure.bbox])});
  if(report)query.set('report','1');
  return `/files/${paperId}/${figure.id}.png?${query}`;
 }
 function link(paperId,user){return '/?'+new URLSearchParams({paper:paperId,account:user||'local'})}
 function route(search,user,papers){
  const q=new URLSearchParams(search);if(!q.has('paper'))return null;
  if(q.get('account')!==(user||'local'))return {error:'当前用户与此阅读页不一致，请回到对应用户的论文库打开。'};
  const paper=papers.find(p=>p.id===q.get('paper'));
  return paper?{paperId:paper.id}:{error:'这篇论文已移除或不存在，请从论文库重新打开。'};
 }
 function pendingAnalyses(state,paperId){return Object.values(state.analysis_jobs||{}).filter(j=>(!paperId||j.paper_id===paperId)&&['queued','running'].includes(j.status))}
 const api={save,restore,figureUrl,link,route,pendingAnalyses};
 if(typeof module!=='undefined')module.exports=api;else root.ReaderState=api;
})(globalThis);
