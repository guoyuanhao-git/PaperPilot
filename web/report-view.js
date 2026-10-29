/* Shared, escaped rendering for the reader and PDF exporter. No model HTML. */
(function(root){
 const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const themes={motivation:['研究动机','#925313','#fff2df'],method:['核心方法','#225f8b','#eaf3fb'],experiments:['实验证据','#28715b','#e9f4ed'],conclusion:['研究结论','#71508e','#f3ecf8'],relevance:['研究联系','#71508e','#f3ecf8']};
 function theme(section){return section.key==='conclusion'?themes.conclusion:section.textbook?['教材式精读','#225f8b','#eaf3fb']:themes[section.focus||section.key]||['阅读重点','#225f8b','#eaf3fb']}
 function chunks(text,max=180){
  const result=[];let current='';
  for(const sentence of String(text).match(/[^。！？\n]+[。！？]?|\n/g)||[]){
   if(current.length+sentence.length>max&&current){result.push(current.trim());current=''}
   current+=sentence;
  }
  if(current.trim())result.push(current.trim());return result;
 }
 function highlights(s){return (s.highlights||[]).filter(h=>typeof h==='string'&&s.paragraphs.some(p=>p.includes(h))).slice(0,3)}
 function marked(text,terms){
  let at=0,out='';while(at<text.length){
   let found=null;
   for(const term of terms){const pos=text.indexOf(term,at);if(pos>=0&&(!found||pos<found.pos||pos===found.pos&&term.length>found.term.length))found={pos,term}}
   if(!found){out+=escape(text.slice(at));break}
   out+=escape(text.slice(at,found.pos))+'<mark>'+escape(found.term)+'</mark>';at=found.pos+found.term.length;
  }return out;
 }
 function references(value){return String(value??'').replace(/左(?:侧)?(?:子)?图/g,'Left').replace(/右(?:侧)?(?:子)?图/g,'Right').replace(/（左）|\(左\)/g,'(Left)').replace(/（右）|\(右\)/g,'(Right)').replace(/(图|表)\s*([A-Z]?\d+(?:[.\-]\d+)*[a-z]?|[A-Z]\.\d+)/g,(_,kind,n)=>(kind==='图'?'Figure ':'Table ')+n)}
 function paperSection(info){
  const paragraphs=[];
  if(!info)paragraphs.push('尚未整理作者、单位和项目链接，可点击“论文相关”标题更新。');
  else{
   const name=a=>{const extras=[];if(a.chinese_name?.verified===true&&a.chinese_name?.name)extras.push(a.chinese_name.name);const citation=a.manual_citation?.source==='manual'?a.manual_citation:(a.scholar?.verified===true&&['Google Scholar','Semantic Scholar'].includes(a.scholar?.source)?a.scholar:null);if(Number.isInteger(citation?.count)&&citation.count>=0)extras.push(citation.count);return a.name+(extras.length?'（'+extras.join(' ')+'）':'')};
   const authors=info.authors||[],corresponding=authors.filter(a=>a.corresponding===true);
   if(authors.length)paragraphs.push('作者：'+name(authors[0])+(corresponding.length?'　通讯：'+corresponding.map(name).join('、'):''));
   const organizations=info.organizations||[...new Set(authors.flatMap(a=>a.affiliations||[]))];
   if(organizations.length)paragraphs.push('组织：'+organizations.map((v,i)=>(organizations.length>1?(i+1)+'. ':'')+v).join('　'));
   if(info.venue?.verified===true&&info.venue?.name)paragraphs.push('期刊/会议：'+info.venue.name);
   if(info.project_url)paragraphs.push('项目链接：'+info.project_url);
   if(info.code_url)paragraphs.push('代码链接：'+info.code_url);
  }
  return {key:'paper_info',title:'论文相关',paragraphs,highlights:[],pages:[],figures:[],equations:[]};
 }
 function equationNotes(e,mode){return (mode==='deep'?[e.meaning,e.implementation]:[e.meaning||e.implementation]).filter(t=>typeof t==='string'&&t.trim())}
 function sections(report){return [paperSection(report.paper_info),...report.sections.filter(s=>s.key!=='paper_info'&&!/论文身份|论文相关/.test(s.title))]}
 function sectionBody(s,interactive=false){
  if(s.key==='paper_info')return s.paragraphs.map(p=>{
   let html=escape(p).replace(/https?:\/\/[^\s]+/g,url=>'<a href="'+url+'" target="_blank" rel="noopener">'+url+'</a>');
   if(interactive&&p.startsWith('作者：'))html=html.replace(/^作者：/,'<button type="button" class="metadata-action" data-citation-role="first" title="填写第一作者引用量" aria-label="作者：填写第一作者引用量">作者</button>：').replace('　通讯：','　<button type="button" class="metadata-action" data-citation-role="corresponding" title="填写通讯作者引用量" aria-label="通讯：填写通讯作者引用量">通讯</button>：');
   return '<p>'+html+'</p>';
  }).join('');
  if(s.key==='abstract')return `<div class="abstract-box">${s.paragraphs.map(p=>`<p>${escape(references(p))}</p>`).join('')}</div>`;
  const terms=highlights(s).map(references);
  return s.paragraphs.flatMap(p=>chunks(references(p))).map(p=>`<p>${marked(p,terms)}</p>`).join('');
 }
 function label(f){
  const match=String(f.caption||'').match(/^\s*(Figure|Fig\.?|Table|图|表)\s*([A-Z]\.\d+|[A-Z]?\d+(?:[.\-]\d+)*|[IVX]+)(?=\s|[:：.．|｜]|$)/i);
  if(match)return (/^(table|表)$/i.test(match[1])?'Table ':'Figure ')+match[2];
  return f.kind==='table'?'Table':'Figure'; // Never invent a source number from an internal ID.
 }
 function caption(f){
  let text=f.caption_zh?.trim()||(/[\u4e00-\u9fff]/.test(f.caption||'')?f.caption:'');
  text=text.replace(/^PDF\s*第\s*[\d、,\s]+\s*页\s*[·:：]?\s*/i,'').replace(/^\s*(?:Figure|Fig\.?|Table|图|表)\s*(?:[A-Z]\.\d+|[A-Z]?\d+(?:[.\-]\d+)*|[IVX]+)\s*[:：.．|｜]?\s*/i,'');
  return label(f)+(text?': '+references(text):'');
 }
 function sectionContent(s,figure,equation){
  if(s.key==='abstract')return sectionBody(s);
  const blocks=s.blocks||[s];
  return blocks.map(b=>(b.figure_first||s.blocks?(b.figures||[]).map(figure).join(''):'')+sectionBody(b)+(b.equations||[]).map(equation).join('')+(!b.figure_first&&!s.blocks?(b.figures||[]).map(figure).join(''):'')).join('');
 }
 const api={equationNotes,sections,paperSection,references,label,sectionContent,escape,theme,chunks,highlights,marked,sectionBody,caption};
 if(typeof module!=='undefined')module.exports=api;else root.ReportView=api;
})(globalThis);
