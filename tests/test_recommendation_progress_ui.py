import shutil
import subprocess
import unittest
from paperpilot import store

@unittest.skipUnless(shutil.which('node'), 'Node required')
class RecommendationProgress(unittest.TestCase):
    def test_reconnect_and_persistent_failure_draft(self):
        subprocess.run(['node','-e',r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const source=fs.readFileSync('web/discover-view.js','utf8');
const methods=source.slice(source.indexOf('function restoreModelTask('),source.indexOf('async function sendRecommendationMessage('));
const c=vm.createContext({assert,setTimeout:f=>setTimeout(f,1)});
vm.runInContext(`
let state={recommendation_chat:{revision:1}},modelPending=false,modelError='',modelDraft='',modelQuestion='second message';
let view='discover',discoveryMode='model';
const progress={};const $=()=>progress;function render(){}
let handler;async function request(...args){return handler(...args)}
`+methods+`
async function test(){
 let calls=0;
 handler=()=>{if(++calls===1)throw Error('temporary disconnect');return {status:'completed',result:{revision:2,messages:['reply']}}};
 await followModelJob({status:'running',id:'a',created_at:new Date().toISOString()});
 assert.equal(calls,2);assert.equal(state.recommendation_chat.revision,2);assert.equal(modelError,'');
 handler=()=>({status:'failed',error:'Codex timeout'});
 await assert.rejects(followModelJob({status:'running',id:'b',question:'retry me'}),/Codex timeout/);
 assert.equal(modelDraft,'retry me');assert.equal(modelPending,false);assert.equal(modelError,'Codex timeout');
 modelDraft='';modelError='';state.recommendation_chat.last_task={status:'failed',question:'saved question',error:'saved error'};
 restoreModelTask();assert.equal(modelDraft,'saved question');assert.equal(modelError,'saved error');
 modelDraft='new draft';restoreModelTask();assert.equal(modelDraft,'new draft');
}
`,c);
vm.runInContext('test()',c).catch(e=>{console.error(e);process.exitCode=1});
'''],cwd=store.ROOT,check=True,timeout=15)
