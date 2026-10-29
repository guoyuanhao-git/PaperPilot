(function(root){
 const palette=[[116,197,244],[128,215,163],[240,218,119],[236,146,187],[168,112,216]];
 function colorAt(value){
  const position=Math.max(0,Math.min(1,value))*(palette.length-1);
  const segment=Math.min(palette.length-2,Math.floor(position)),mix=position-segment;
  return '#'+palette[segment].map((c,i)=>Math.round(c+(palette[segment+1][i]-c)*mix).toString(16).padStart(2,'0')).join('');
 }
 function decorate(nodes,edges,papers,scope='all'){
  const live=new Map(papers.map(p=>[p.id,p])),neighbors=new Map(nodes.map(n=>[n.id,new Set()]));
  for(const e of edges){if(e.source!==e.target&&neighbors.has(e.source)&&neighbors.has(e.target)){neighbors.get(e.source).add(e.target);neighbors.get(e.target).add(e.source)}}
  const weighted=nodes.map(n=>{
   const readStatus=live.get(n.id)?.read_status||'',degree=neighbors.get(n.id).size;
   // Personal display salience, not citations, scientific quality or inferred causality.
   const depth=readStatus==='已精读'?1.5:readStatus==='已速览'?.5:0;
   const connected=Math.min(4,1.2*Math.log2(1+degree));
   const relevance=Number.isInteger(n.relevance)?Math.max(0,Math.min(3,n.relevance))*4:0;
   const importance=relevance+(n.starred?2:n.liked?1:0)+depth+connected;
   return {...n,readStatus,degree,importance};
  });
  const weights=weighted.map(n=>n.importance),minimum=weights.length?Math.min(...weights):0,maximum=weights.length?Math.max(...weights):0;
  return weighted.map(n=>{
   // Use the current graph's range before search/focus; a minimum span avoids
   // exaggerating tiny differences. Equal weights retain the absolute scale.
   const t=maximum>minimum?(n.importance-minimum)/Math.max(4,maximum-minimum):Math.min(1,n.importance/(scope==='starred'?18:22));
   // Color anchors define a continuous ramp, never categorical weight buckets.
   const size=Math.pow(t,1.1);
   // The 3D library treats nodeVal as volume. Cube the desired radius scale so
   // its cube-root rendering does not flatten visible size differences.
   return {...n,graphColor:colorAt(t),graphSize:Math.pow(1+2.2*size,3),graphRadius:10+22*size};
  });
 }
 const api={decorate,colorAt};if(typeof module!=='undefined')module.exports=api;else root.GraphMetrics=api;
})(globalThis);
