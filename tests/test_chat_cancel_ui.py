import shutil
import subprocess
import unittest
from paperpilot import store


@unittest.skipUnless(shutil.which('node'),'Node required')
class ChatCancelUI(unittest.TestCase):
    def test_stop_before_submission_returns_and_late_reply_cannot_overwrite_new_send(self):
        subprocess.run(['node','-e',r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const source=fs.readFileSync('web/app.js','utf8');
const methods=source.slice(source.indexOf('async function refreshPaperMessages'),source.indexOf('\nlet deleting'));
const c=vm.createContext({assert,setTimeout:(f,t)=>setTimeout(f,Math.min(t,2)),URLSearchParams,console});
vm.runInContext(`
let state={papers:[{id:'p',messages:[]}]},selected=state.papers[0],view='paper';
let knowledgeMainline='',knowledgeProvider='';
const chatDrafts=new Map(),chatPending=new Map(),chatErrors=new Map();
const $=()=>({focus(){}});function render(){}function toast(){}
let handler;async function request(...args){return handler(...args)}
const sleep=()=>new Promise(r=>setTimeout(r,2));
`+methods+`
async function test(){
 let create;
 chatDrafts.set('p','original question');
 handler=(path)=>path==='/api/chat'?new Promise(r=>create=r):Promise.resolve({status:'cancelled'});
 const send=sendPaperMessage();const stop=stopPaperMessage();
 assert.equal(chatPending.get('p').stopping,true);
 create({id:'old',status:'running'});await Promise.all([send,stop]);
 assert.equal(chatPending.size,0);assert.equal(chatDrafts.get('p'),'original question');
 // A response already being polled must not clear a newer pending request.
 let oldPoll,newCreate;
 handler=(path)=>path==='/api/chat'?Promise.resolve({id:'old2',status:'running'}):path==='/api/job/old2'?new Promise(r=>oldPoll=r):Promise.resolve({status:'cancelled'});
 const old=sendPaperMessage();while(!oldPoll)await sleep();
 chatDrafts.set('p','unsent draft');await stopPaperMessage();
 assert.equal(chatDrafts.get('p'),'original question\\n\\nunsent draft');
 chatDrafts.set('p','corrected');
 handler=(path)=>path==='/api/chat'?new Promise(r=>newCreate=r):Promise.resolve({status:'cancelled'});
 const fresh=sendPaperMessage();const latest=chatPending.get('p');
 oldPoll({id:'old2',status:'completed'});await old;
 assert.equal(chatPending.get('p'),latest);
 const finish=stopPaperMessage();newCreate({id:'new',status:'running'});await Promise.all([fresh,finish]);
 assert.equal(chatDrafts.get('p'),'corrected');assert.equal(chatPending.size,0);
}
`,c);
vm.runInContext('test()',c).catch(e=>{console.error(e);process.exitCode=1});
'''],cwd=store.ROOT,check=True,timeout=15)
