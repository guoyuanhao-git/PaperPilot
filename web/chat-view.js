/* A deliberately small Markdown renderer. Raw HTML is always escaped. */
(function(root){
 const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function tableCells(line){
  // Split only structural pipes. Absolute values, norms, conditional probabilities
  // and code can contain pipes of their own, before inline math is rendered.
  const source=line.trim(),cells=[];
  const tokens=/`[^`\n]+`|\\\([^\n]*?\\\)|(?<![\\$])\$(?!\$)[^$\n]+?\$(?!\$)|\\\||\|/g;
  let cell='',at=0;
  for(const match of source.matchAll(tokens)){
   cell+=source.slice(at,match.index);
   if(match[0]==='|'){cells.push(cell.trim());cell='';}
   else cell+=match[0]==='\\|'?'|':match[0];
   at=match.index+match[0].length;
  }
  cells.push((cell+source.slice(at)).trim());
  if(source.startsWith('|'))cells.shift();
  if(cells.at(-1)===''&&source.endsWith('|'))cells.pop();
  return cells;
 }
 function render(text,formula=(s)=>esc(s)){
  function inline(value){
   const pattern=/(`[^`\n]+`|\*\*(?:(?!\*\*)[^\n])+\*\*|\[[^\]\n]+\]\(https?:\/\/[^\s)]+\)|\$[^$\n]+\$|\\\([^\n]*?\\\))/g;
   let out='',at=0;
   for(const m of value.matchAll(pattern)){
    out+=esc(value.slice(at,m.index));const t=m[0];
    if(t.startsWith('`'))out+='<code>'+esc(t.slice(1,-1))+'</code>';
    // Bold text may contain math or code; render its inline contents, not raw LaTeX.
    else if(t.startsWith('**'))out+='<strong>'+inline(t.slice(2,-2))+'</strong>';
    else if(t.startsWith('[')){const end=t.indexOf('](');out+='<a target="_blank" rel="noopener noreferrer" href="'+esc(t.slice(end+2,-1))+'">'+esc(t.slice(1,end))+'</a>'}
    else out+=formula(t.startsWith('$')?t.slice(1,-1):t.slice(2,-2),false);
    at=m.index+t.length;
   }
   return out+esc(value.slice(at));
  }
  const lines=String(text).replace(/\r\n?/g,'\n').split('\n');let out='',i=0;
  const cells=tableCells;
  const special=s=>/^(#{1,6}\s|```|\$\$|\\\[|[-*+]\s|\d+\.\s|>\s|---+$)/.test(s.trim());
  while(i<lines.length){
   let line=lines[i].trim();if(!line){i++;continue}
   if(line.startsWith('```')){const code=[];i++;while(i<lines.length&&!lines[i].trim().startsWith('```'))code.push(lines[i++]);i++;out+='<pre><code>'+esc(code.join('\n'))+'</code></pre>';continue}
   if(line.startsWith('$$')||line.startsWith('\\[')){
    const closer=line.startsWith('$$')?'$$':'\\]';let latex=line.slice(2);i++;
    while(!latex.endsWith(closer)&&i<lines.length)latex+='\n'+lines[i++];
    if(latex.endsWith(closer))latex=latex.slice(0,-2);
    out+='<div class="chat-math">'+formula(latex,true)+'</div>';continue;
   }
   if(i+1<lines.length&&line.includes('|')&&/^\s*\|?\s*:?-{3,}/.test(lines[i+1])){
    const headers=cells(line);i+=2;out+='<div class="chat-table"><table><thead><tr>'+headers.map(c=>'<th>'+inline(c)+'</th>').join('')+'</tr></thead><tbody>';
    while(i<lines.length&&lines[i].includes('|'))out+='<tr>'+cells(lines[i++]).map(c=>'<td>'+inline(c)+'</td>').join('')+'</tr>';
    out+='</tbody></table></div>';continue;
   }
   const heading=line.match(/^(#{1,6})\s+(.+)/);
   if(heading){out+='<h3>'+inline(heading[2])+'</h3>';i++;continue}
   if(/^---+$/.test(line)){out+='<hr>';i++;continue}
   if(/^([-*+]\s|\d+\.\s)/.test(line)){
    const ordered=/^\d+\./.test(line),tag=ordered?'ol':'ul',pattern=ordered?/^\d+\.\s+/:/^[-*+]\s+/;
    // Explanatory paragraphs can split a list; retain the source's next number.
    const start=ordered?Number(line.match(/^\d+/)[0]):1;
    out+='<'+tag+(ordered&&Number.isSafeInteger(start)&&start!==1?' start="'+start+'"':'')+'>';
    while(i<lines.length&&pattern.test(lines[i].trim())){
     out+='<li>'+inline(lines[i++].trim().replace(pattern,''))+'</li>';
     // Empty lines alone do not restart a Markdown list (including 1. / 1. syntax).
     let next=i;while(next<lines.length&&!lines[next].trim())next++;
     if(next<lines.length&&pattern.test(lines[next].trim()))i=next;
    }
    out+='</'+tag+'>';continue;
   }
   if(line.startsWith('> ')){out+='<blockquote>'+inline(line.slice(2))+'</blockquote>';i++;continue}
   const para=[line];i++;
   while(i<lines.length&&lines[i].trim()&&!special(lines[i])&&!(i+1<lines.length&&lines[i].includes('|')&&/^\s*\|?\s*:?-{3,}/.test(lines[i+1])))para.push(lines[i++]);
   out+='<p>'+para.map(inline).join('<br>')+'</p>';
  }
  return out;
 }
 function authorIcon(role,gender){return role==='assistant'?'saixiaoxi':gender==='男'?'liuxing':gender==='女'?'lanxue':gender==='秘密'?'naiwa':'nailong'}
 const api={render,authorIcon};if(typeof module!=='undefined')module.exports=api;else root.ChatView=api;
})(globalThis);
