// Portable renderer: model JSON becomes editable PowerPoint objects, never model HTML/code.
import fs from 'node:fs/promises';
import {readFileSync} from 'node:fs';
import path from 'node:path';
import PptxGenJS from 'pptxgenjs';
import katex from 'katex';
import {chromium} from 'playwright';
const payload=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
const {theme:t,slides,output,build}=payload;
const pptx=new PptxGenJS();pptx.defineLayout({name:'REFERENCE',width:t.width,height:t.height});pptx.layout='REFERENCE';
pptx.author='PaperPilot';pptx.subject='论文讲解';pptx.title=payload.paper_title;pptx.lang='zh-CN';
pptx.theme={headFontFace:t.font,bodyFontFace:t.font,lang:'zh-CN'};
const W=t.width,H=t.height,sx=W/13.333,sy=H/7.5;
const x=v=>v*sx,y=v=>v*sy;
const opts=(a,b,w,h,extra={})=>({x:x(a),y:y(b),w:x(w),h:y(h),fontFace:t.font,fontSize:t.body_size,color:t.text,margin:0,breakLine:false,paraSpaceAfterPt:6,valign:'top',...extra});
const tone=t.primary,accent=t.accent;
const rgb=c=>[0,2,4].map(i=>parseInt(c.slice(i,i+2),16));
const inkOn=c=>rgb(c).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0)<140?'FFFFFF':'202B35';
function shape(s,type,a,b,w,h,extra={}){s.addShape(type,{x:x(a),y:y(b),w:x(w),h:y(h),line:{color:'DCE3EB',transparency:100},...extra});}
function text(s,content,a,b,w,h,extra={}){s.addText(content,opts(a,b,w,h,{fit:'shrink',...extra}));}
function rich(block){const word=block.emphasis;return word&&block.text.includes(word)?block.text.split(word).flatMap((part,i)=>[...(i?[{text:word,options:{bold:true,color:t.emphasis||accent}}]:[]),{text:part}]):block.text;}
function blocks(s,items,a,b,w,h){
 if(!items.length)return;const unit=h/items.length;
 items.forEach((block,i)=>{const top=b+i*unit;
  if(block.heading)text(s,block.heading,a,top,w,.32,{fontSize:19,bold:true,color:t.primary});
  text(s,rich(block),a,top+(block.heading?.42:0),w,unit-(block.heading?.53:.12),{fontSize:t.body_size,breakLine:false});
 });
}
let browser;
async function equationImage(latex,index){
 if(!browser){const system='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';const available=await fs.access(system).then(()=>true).catch(()=>false);browser=await chromium.launch({headless:true,...(process.env.PAPERPILOT_CHROME?{executablePath:process.env.PAPERPILOT_CHROME}:available?{executablePath:system}:{})});}
 const page=await browser.newPage({viewport:{width:1400,height:500},deviceScaleFactor:2});
 try{
 const html=katex.renderToString(latex,{throwOnError:true,displayMode:true,trust:false});
 const folder=path.resolve('node_modules/katex/dist');
 const css=(await fs.readFile(path.join(folder,'katex.min.css'),'utf8')).replace(/url\(([^)]+)\)/g,(_,url)=>{
   const font=path.join(folder,url.replace(/["']/g,''));return `url(data:font/woff2;base64,${readFileSync(font).toString('base64')})`;
 });
 await page.setContent('<style>'+css+'</style><div id="equation" style="padding:25px;display:inline-block;background:white;font-size:30px">'+html+'</div>');
 await page.evaluate(()=>document.fonts.ready);
 const filename=path.join(build,`equation-${index}.png`);await page.locator('#equation').screenshot({path:filename});return filename;
 }finally{await page.close()}
}
try{
for(const [i,d] of slides.entries()){
 const s=pptx.addSlide();s.background={color:t.background};
 if(d.layout==='cover'){
  s.background={color:t.primary};shape(s,'rect',.65,1.15,.08,3.7,{fill:{color:accent}});
  text(s,payload.paper_title,1,1.1,11.3,2.2,{fontSize:34,bold:true,color:inkOn(t.primary)});
  text(s,d.takeaway,1,3.65,11.1,1.0,{fontSize:23,color:inkOn(t.primary)});
  text(s,d.blocks.map(b=>b.heading+' '+b.text).join('\n'),1,5.15,11.1,1.3,{fontSize:16,color:inkOn(t.primary)});
 }else{
  if(t.header){shape(s,'rect',0,0,13.333,1.02,{fill:{color:t.primary}});shape(s,'rect',0,1.02,13.333,.04,{fill:{color:accent}});}
  text(s,d.title,.5,.18,12.25,.68,{fontSize:t.title_size,bold:true,color:t.header?inkOn(t.primary):t.primary});
  const top=1.36,bodyH=d.takeaway?4.55:5.45;
  if(d.layout==='columns'){
   const split=Math.ceil(d.blocks.length/2);blocks(s,d.blocks.slice(0,split),.6,top,5.85,bodyH);blocks(s,d.blocks.slice(split),6.95,top,5.75,bodyH);
   shape(s,'line',6.65,top,0,bodyH,{line:{color:'DCE3EB',width:1}});
  }else if(d.layout==='figure'){
   blocks(s,d.blocks,.6,top,5.15,bodyH);
   s.addImage({path:d.image_path,...pptxgenContain(d.image_path,x(6.05),y(top),x(6.6),y(bodyH-.55))});
   text(s,d.caption,6.05,top+bodyH-.48,6.6,.5,{fontSize:13,color:'5D6872'});
  }else if(d.layout==='table'){
   const rows=[d.table.headers.map(text=>({text,options:{bold:true,color:inkOn(t.primary),fill:t.primary}})),...d.table.rows];
   const commentH=d.blocks.length?1.35:0,tableH=bodyH-commentH-(commentH?.2:0);
   s.addTable(rows,{x:x(.6),y:y(top),w:x(12.1),h:y(tableH),fontFace:t.font,fontSize:17,color:t.text,
    border:{color:'FFFFFF',pt:1},fill:'EDF2F8',margin:6,autoPage:false,verbose:false,rowH:y(Math.min(.62,tableH/rows.length))});
   // Keep explanatory blocks beside each other, not stacked into a sub-inch strip.
   const gap=.28,cw=(12.1-gap*(d.blocks.length-1))/Math.max(1,d.blocks.length);
   d.blocks.forEach((block,k)=>blocks(s,[block],.6+k*(cw+gap),top+tableH+.2,cw,commentH));
  }else if(d.layout==='process'){
   const gap=.28,cw=(12.1-(d.steps.length-1)*gap)/d.steps.length;
   d.steps.forEach((step,k)=>{shape(s,'roundRect',.6+k*(cw+gap),top+.25,cw,1.2,{fill:{color:k%2?accent:t.primary},radius:.12});text(s,step,.75+k*(cw+gap),top+.44,cw-.3,.8,{fontSize:19,bold:true,color:inkOn(k%2?accent:t.primary)});
    if(k<d.steps.length-1)shape(s,'line',.6+(k+1)*cw+k*gap,top+.85,gap,0,{line:{color:accent,width:2,beginArrowType:'none',endArrowType:'triangle'}});
   });blocks(s,d.blocks,.6,top+1.9,12.1,bodyH-1.9);
  }else if(d.layout==='equation'){
   const image=await equationImage(d.equation,i);s.addImage({path:image,...pptxgenContain(image,x(.8),y(top),x(11.7),y(1.5))});
   text(s,d.equation_meaning,.8,top+1.65,11.7,.65,{fontSize:20,bold:true,color:t.primary});blocks(s,d.blocks,.8,top+2.5,11.7,bodyH-2.5);
  }else blocks(s,d.blocks,.7,top,11.9,bodyH);
  if(d.takeaway){shape(s,'roundRect',.6,6.02,12.1,.62,{fill:{color:'EDF2F8'},line:{color:t.primary,width:.6},radius:.08});text(s,d.takeaway,.8,6.12,11.7,.42,{fontSize:17,color:t.primary,bold:true});}
 }
 text(s,'PaperPilot · 论文讲解',.6,7.05,7,.2,{fontSize:10,color:d.layout==='cover'?inkOn(t.primary):'7D8892'});
 text(s,`${i+1} / ${slides.length}`,11.5,7.05,1.15,.2,{fontSize:10,color:d.layout==='cover'?inkOn(t.primary):'7D8892',align:'right'});
 s.addNotes(`${d.notes}\n\n原文依据：PDF 第 ${d.pages.join('、')} 页\n${d.evidence_quote}\n${payload.source_url||''}\n\n阅读覆盖：${payload.coverage}\n${d.equation?'公式 LaTeX：'+d.equation:''}`);
}
await pptx.writeFile({fileName:output});
}finally{if(browser)await browser.close()}
function pptxgenContain(file,x,y,w,h){
 const bytes=readFileSync(file);if(bytes.toString('hex',0,8)!=='89504e470d0a1a0a')throw Error('Expected local PNG asset');
 const iw=bytes.readUInt32BE(16),ih=bytes.readUInt32BE(20),scale=Math.min(w/iw,h/ih);
 return {x:x+(w-iw*scale)/2,y:y+(h-ih*scale)/2,w:iw*scale,h:ih*scale};
}
