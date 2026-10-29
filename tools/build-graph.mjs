import {build} from 'esbuild';
import fs from 'node:fs';
import path from 'node:path';
const result=await build({entryPoints:['tools/graph3d-entry.js'],bundle:true,minify:true,format:'iife',target:'es2020',outfile:'web/graph3d.bundle.js',metafile:true,legalComments:'inline'});
const packages=new Set();
for(const input of Object.keys(result.metafile.inputs)){
 if(!input.includes('node_modules/'))continue;
 let folder=path.dirname(path.resolve(input));
 while(folder!==path.dirname(folder)&&!fs.existsSync(path.join(folder,'package.json')))folder=path.dirname(folder);
 if(fs.existsSync(path.join(folder,'package.json')))packages.add(folder);
}
const notices=[];
for(const folder of [...packages].sort()){
 const info=JSON.parse(fs.readFileSync(path.join(folder,'package.json'),'utf8'));
 const licenses=fs.readdirSync(folder).filter(name=>/^(license|copying)([.\-]|$)/i.test(name));
 notices.push(`${info.name} ${info.version} (${info.license||'See license'})\n`+licenses.map(name=>fs.readFileSync(path.join(folder,name),'utf8')).join('\n'));
}
fs.writeFileSync('web/graph3d-licenses.txt',notices.join('\n\n'+'='.repeat(70)+'\n\n'));
