import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL,fileURLToPath} from 'node:url';
import os from 'node:os';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const requireLocal=createRequire(path.join(root,'package.json'));
const katex=requireLocal('katex');
const {chromium}=requireLocal('playwright');
const payload=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
const {paper,format,output,build}=payload;
if(format!=='pdf')throw Error('Only PDF export is supported');
const report=paper.report;
const reader=requireLocal('./web/report-view.js');
const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const katexCSS=path.join(root,'node_modules/katex/dist/katex.min.css');
const equations=e=>katex.renderToString(e.latex,{throwOnError:false,displayMode:true,trust:false});
const image=f=>`<figure><img src="${pathToFileURL(f.path).href}"><figcaption>${escape(reader.caption(f))}</figcaption></figure>`;
const figures=report.figures||[];
const used=new Set(report.sections.flatMap(s=>s.figures));
const css=`@page{size:A4;margin:20mm 19mm}*{box-sizing:border-box}body{font-family:"Songti SC","Noto Serif CJK SC","Microsoft YaHei",serif;font-size:12pt;line-height:1.85;color:#213e4e;margin:0}h1{font-family:"PingFang SC","Microsoft YaHei",sans-serif;font-size:25pt;line-height:1.45;margin:0 0 16px}h2{font-family:"PingFang SC","Microsoft YaHei",sans-serif;color:#153f54;font-size:19pt;margin:28px 0 14px;break-after:avoid;border-bottom:1px solid #7297a0;padding-bottom:10px}p{white-space:pre-wrap;margin:0 0 15px;orphans:3;widows:3;color:#24343c}.eyebrow,.meta,figcaption,.cite{font-family:"PingFang SC",sans-serif;color:#6b7c7f;font-size:9pt;line-height:1.65}.eyebrow{letter-spacing:2px;margin-bottom:16px}.lead{font-size:14pt;padding-left:15px;border-left:3px solid #759b9c;margin:20px 0}.meta{margin:12px 0 24px;overflow-wrap:anywhere}figure{margin:20px 0;break-inside:avoid}figure img{display:block;width:100%;max-height:180mm;object-fit:contain}figcaption{margin-top:8px}.equation{break-inside:avoid;background:#f3f6f4;padding:12px 16px;margin:16px 0}.equation p{font-size:10pt;color:#53666b;margin:12px 0 0}.katex-display{margin:8px 0;overflow-wrap:anywhere}.katex{font-size:1.02em}a{color:#315c69}.cite{margin:14px 0}section h2{color:var(--accent);border-color:var(--accent)}mark{background:var(--tint);color:var(--accent);font-weight:700;padding:1px 3px;box-decoration-break:clone;-webkit-box-decoration-break:clone}.reading-cue{background:var(--tint);color:var(--accent);border-left:3px solid var(--accent);padding:10px 14px;margin:16px 0;break-inside:avoid;font-size:11pt}.reading-cue span{display:block;font-size:8pt;margin-bottom:4px}.lead{background:#eef3e9;padding:12px 16px}.abstract-box{background:#eaf3fb;border-left:3px solid #225f8b;padding:16px 20px;box-decoration-break:clone;-webkit-box-decoration-break:clone}.abstract-box p{color:#225f8b}.abstract-box p:last-child{margin-bottom:0}`;
const html=`<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><link rel="stylesheet" href="${pathToFileURL(katexCSS).href}"><style>${css}</style></head><body><div class="eyebrow">PAPERPILOT · ${({overview:'中文论文速览',detailed:'中文精读',deep:'教材式数学精读'})[report.mode]||'中文论文速览'}</div><h1>${escape(report.title)}</h1><p class="lead">${escape(reader.references(report.summary))}</p><div class="meta">${escape(report.scope)}<br>${report.vision?(report.format_version>=2?'已按批附上全部阅读范围内图像供模型理解':'已附 '+(report.image_count||'部分')+' 张图像供模型理解'):'模型仅依据文字及图注，未启用图像理解'}${paper.is_reference?'<br>用户提供的风格参考学习稿，非原始论文':''}<br>接入：${escape(report.provider)} · ${escape(report.model)}${paper.source_url?'<br>原文：'+escape(paper.source_url):''}</div>${reader.sections(report).map(s=>`<section style="--accent:${reader.theme(s)[1]};--tint:${reader.theme(s)[2]}">${s.key==='abstract'?'':`<h2>${escape(reader.references(s.title))}</h2>`}${reader.sectionContent(s,id=>{const f=figures.find(f=>f.id===id);return f?image(f):''},e=>`<div class="equation">${equations(e)}${reader.equationNotes(e,report.mode).map(t=>`<p>${escape(reader.references(t))}</p>`).join('')}</div>`)}</section>`).join('')}${figures.filter(f=>!used.has(f.id)).length?'<h2>其他所选原文图表</h2>'+figures.filter(f=>!used.has(f.id)).map(image).join(''):''}</body></html>`;
await fs.mkdir(build,{recursive:true});
await fs.writeFile(path.join(build,'report.html'),html);
const chrome=process.env.PAPERPILOT_CHROME || (os.platform()==='darwin'?'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome':undefined);
const browser=await chromium.launch({headless:true,...(chrome?{executablePath:chrome}:{})});
try{
 const page=await browser.newPage({viewport:{width:1100,height:1400},deviceScaleFactor:2});
 await page.goto(pathToFileURL(path.join(build,'report.html')).href);
 await page.evaluate(()=>document.fonts.ready);
  await page.pdf({path:output,format:'A4',printBackground:true,displayHeaderFooter:true,
   headerTemplate:'<span></span>',footerTemplate:'<div style="font-size:9px;width:100%;text-align:center;color:#70817d;font-family:sans-serif">PaperPilot　<span class="pageNumber"></span></div>',margin:{top:'20mm',bottom:'20mm',left:'19mm',right:'19mm'}});
}finally{await browser.close()}
console.log(JSON.stringify({output,format}));
