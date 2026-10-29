(function(root){
 const done=p=>['已速览','已精读'].includes(p.read_status);
 const group=p=>p.starred?'starred':p.liked?'liked':done(p)?'read':'reading';
 const timestamp=v=>Number.isFinite(Date.parse(v))?Date.parse(v):0;
 function rows(papers,tab){const result=papers.filter(p=>group(p)===tab);
  if(tab==='reading')return result;
  return result.sort((a,b)=>(b.publication_month||'').localeCompare(a.publication_month||'')||timestamp(b.added_at)-timestamp(a.added_at)||a.id.localeCompare(b.id));
 }
 function counts(papers){const result={reading:0,read:0,liked:0,starred:0};papers.forEach(p=>result[group(p)]++);return result}
 function title(p){if(p.report?.title)return p.report.title;const month=p.publication_month||'';return (/^\d{4}-\d{2}$/.test(month)?month.slice(2,4)+month.slice(5,7)+' · ':'')+(p.original_title||p.title||'论文标题暂未获取')}
 const api={done,group,rows,counts,title};if(typeof module!=='undefined')module.exports=api;else root.LibraryView=api;
})(globalThis);
