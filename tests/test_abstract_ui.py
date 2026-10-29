"""Regression for asynchronous abstract language changes without full-page render."""
import shutil
import subprocess
import unittest

from paperpilot import store


@unittest.skipUnless(shutil.which('node'), 'Node required')
class AbstractUI(unittest.TestCase):
    def test_translation_updates_locally_and_preserves_language_choice(self):
        subprocess.run(['node', '-e', r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('web/app.js','utf8');
const functions=source.slice(source.indexOf('function abstractState('),source.indexOf('function paperCard('));
const context=vm.createContext({assert,setTimeout});
vm.runInContext(`
let state={abstract_translations:[]},view='hotspots',requests=0,resolveJob,rejectJob;
const cardRefs=[{paper:{id:'p',abstract:'English source abstract'},origin:'hf-listing',runId:'fixture'}];
const abstractLanguages=new Map(),abstractOpen=new Set(),abstractPending=new Map(),abstractErrors=new Map();
function render(){throw Error('Must not rebuild the page')}
function toast(){}
function request(){requests++;return new Promise((resolve,reject)=>{resolveJob=resolve;rejectJob=reject})}
`+functions+`
const updates=[];
updateAbstractViews=source=>updates.push(abstractState(source));
async function test(){
 const source=cardRefs[0].paper.abstract;
 const task=chooseAbstract(0,'zh');
 assert.equal(requests,1);assert.equal(updates.at(-1).loading,true);
 await chooseAbstract(0,'zh');assert.equal(requests,1);
 await chooseAbstract(0,'en');assert.equal(updates.at(-1).text,source);
 resolveJob({status:'completed',result:{id:'t',source_text:source,language:'zh',text:'中文译文'}});
 await task;
 assert.equal(updates.at(-1).language,'en');
 assert.equal(updates.at(-1).text,source);
 assert.equal(abstractPending.size,0);
 await chooseAbstract(0,'zh');
 assert.equal(updates.at(-1).text,'中文译文');assert.equal(requests,1);
 state.abstract_translations=[];
 const failed=chooseAbstract(0,'zh');rejectJob(Error('Network failed'));await failed;
 assert.equal(updates.at(-1).message,'Network failed');assert.equal(abstractPending.size,0);
 const retry=chooseAbstract(0,'zh');
 assert.equal(updates.at(-1).loading,true);assert.equal(abstractErrors.size,0);
 resolveJob({status:'completed',result:{id:'t',source_text:source,language:'zh',text:'重试译文'}});
 await retry;
 assert.equal(updates.at(-1).text,'重试译文');assert.equal(requests,3);
}
`,context);
vm.runInContext('test()',context).catch(error=>{console.error(error);process.exitCode=1});
'''], cwd=store.ROOT, check=True, timeout=15)
