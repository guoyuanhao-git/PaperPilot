"""Crop URL invalidation and refresh navigation, without touching user papers."""
import shutil
import subprocess
import unittest
from paperpilot import store


@unittest.skipUnless(shutil.which('node'), 'Node required')
class ReaderStateUI(unittest.TestCase):
    def test_crop_urls_and_account_isolated_page_restore(self):
        subprocess.run(['node', '-e', r'''
const assert=require('node:assert/strict'),reader=require('./web/reader-state.js');
const f={id:'fig-1',page:1,bbox:[.1,.1,.8,.8]};
const before=reader.figureUrl('a',f,true);
assert.equal(reader.figureUrl('a',{...f},true),before);
for(const changed of [{...f,page:2},{...f,bbox:[.1,.1,.5,.5]}]){
 assert.notEqual(reader.figureUrl('a',changed,true),before);
 assert.notEqual(reader.figureUrl('a',changed),reader.figureUrl('a',f));
}
assert.equal(new URL(before,'http://localhost').searchParams.get('report'),'1');
const cache=new Map(),storage={getItem:k=>cache.get(k),setItem:(k,v)=>cache.set(k,v)};
reader.save(storage,'user-a','paper','p');
assert.deepEqual(reader.restore(storage,'user-a',[{id:'p'}]),{view:'paper',paperId:'p'});
assert.equal(reader.restore(storage,'user-b',[{id:'p'}]),null);
assert.equal(reader.restore(storage,'user-a',[]).view,'library');
reader.save(storage,'user-a','library','p');
assert.deepEqual(reader.restore(storage,'user-a',[{id:'p'}]),{view:'library',paperId:null});
assert.equal(reader.restore({getItem:()=>'{broken'},'user-a',[]),null);
reader.save({setItem:()=>{throw Error('blocked')}},'user-a','paper','p');
'''], cwd=store.ROOT, check=True, timeout=15)

    def test_crop_save_waits_and_does_not_replace_another_paper(self):
        subprocess.run(['node', '-e', r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('web/app.js','utf8');
const save=source.slice(source.indexOf('async function saveCrop(){'),source.indexOf("$('#save-crop').onclick="));
const accept=source.slice(source.indexOf('function acceptPaperUpdate('),source.indexOf('async function reload('));
const context=vm.createContext({assert,console});
vm.runInContext(`
let state={papers:[{id:'a',figures:[{id:'fig-1',page:1,bbox:[0,0,1,1]}]},{id:'b'}]},selected=state.papers[0],view='paper';
let crop={paperId:'a',figure:state.papers[0].figures[0],page:1,bbox:[.1,.2,.8,.9]},resolve,reject,requests=0,renders=0,closed=false;
const button={disabled:false},caption={value:'新图注'},dialog={close(){closed=true}};
const $=key=>({'#save-crop':button,'#crop-caption':caption,'#crop-dialog':dialog,'#cancel-crop':{},'#close-crop':{}}[key]);
const ViewContinuity={capture:()=>({position:'saved'})};function render(position){assert.ok(position);renders++}function toast(){}
function request(path,body){requests++;assert.equal(body.id,'a');assert.deepEqual(body.figures[0].bbox,[.1,.2,.8,.9]);return new Promise((yes,no)=>{resolve=yes;reject=no})}
`+accept+save+`
async function test(){
 const task=saveCrop();assert.equal(button.disabled,true);assert.equal(closed,false);
 await saveCrop();assert.equal(requests,1);
 selected=state.papers[1];resolve({id:'a',figures:[{id:'fig-1',bbox:[.1,.2,.8,.9]}]});await task;
 assert.equal(selected.id,'b');assert.equal(renders,0);assert.equal(closed,true);assert.equal(button.disabled,false);
 selected=state.papers[0];closed=false;crop={paperId:'a',figure:selected.figures[0],page:1,bbox:[.1,.2,.8,.9]};
 const failure=saveCrop();reject(Error('Save failed'));await assert.rejects(failure,/Save failed/);
 assert.equal(closed,false);assert.ok(crop);assert.equal(button.disabled,false);
 const success=saveCrop();resolve({id:'a',figures:[{id:'fig-1',bbox:[.1,.2,.8,.9]}]});await success;
 assert.equal(renders,1);assert.equal(crop,null);assert.equal(closed,true);
}
`,context);
vm.runInContext('test()',context).catch(e=>{console.error(e);process.exitCode=1});
'''], cwd=store.ROOT, check=True, timeout=15)

    def test_crop_page_navigation_races_and_validation(self):
        subprocess.run(['node', '-e', r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('web/app.js','utf8');
const code=source.slice(source.indexOf('function cropPageControls('),source.indexOf('function drawCrop()'));
const elements=new Map(),images=[];
const $=id=>{if(!elements.has(id))elements.set(id,{value:1,max:18,disabled:false,hidden:true,setAttribute(k,v){this[k]=v}});return elements.get(id)};
const crop={paperId:'p',page:1,image:{old:true}},context={crop,state:{papers:[{id:'p',page_count:18}]},$,Image:class{constructor(){images.push(this)}},scopedFile:x=>x,drawCrop(){},loadCropText:async()=>{},guard:f=>f()};
vm.createContext(context);vm.runInContext(code,context);
(async()=>{
 $('#crop-page').value=2;const a=context.loadCropPage();
 const b=context.stepCropPage(1);assert.equal($('#crop-page').value,3);assert.equal($('#save-crop').disabled,true);
 Object.assign(images[1],{width:600,height:900});images[1].onload();await b;
 assert.equal(crop.page,3);assert.equal($('#save-crop').disabled,false);
 images[0].onload();await a;assert.equal(crop.page,3);assert.equal(crop.image,images[1]);
 $('#crop-page').value=2.5;await context.loadCropPage();assert.equal(images.length,2);assert.equal(crop.page,3);
 $('#crop-page').value=18;const c=context.loadCropPage();images[2].onerror();await c;assert.equal(crop.page,3);assert.equal($('#crop-page').value,3);
 console.log('Navigation: immediate steps, last request wins, invalid page and failure recovery passed');
})().catch(e=>{console.error(e);process.exitCode=1});

'''], cwd=store.ROOT, check=True, timeout=15)
