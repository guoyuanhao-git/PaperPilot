import shutil
import subprocess
import unittest
from paperpilot import store

@unittest.skipUnless(shutil.which('node'), 'Node required')
class AnalysisCancelUI(unittest.TestCase):
    def test_stop_and_new_mode_ignore_old_poll(self):
        subprocess.run(['node', '-e', r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const source=fs.readFileSync('web/app.js','utf8');
const methods=source.slice(source.indexOf('function analysisActive('),source.indexOf('function watchAnalyses('));
const c=vm.createContext({assert,setTimeout:(f)=>setTimeout(f,1)});
vm.runInContext(`
let state={analysis_jobs:{p:{id:'old',paper_id:'p',status:'running'}}},selected={id:'p'},view='paper';
const analysisSubmitting=new Set(),analysisObservers=new Map();
const elements={'#stop-analysis':{},'#analyze':{},'#reading-task-status':{}};
const $=key=>elements[key];function readingTaskStatus(){return ''}function latestReadingTask(){return state.analysis_jobs.p}
function toast(){}async function reload(){}function renderReaderUpdate(){}
let handler;async function request(...args){return handler(...args)}
`+methods+`
async function test(){
 let poll;
 handler=(path)=>path==='/api/job/old'?new Promise(r=>poll=r):Promise.resolve({id:'old',paper_id:'p',status:'cancelled'});
 const observer=followAnalysis(state.analysis_jobs.p);
 while(!poll)await new Promise(r=>setTimeout(r,1));
 await stopAnalysis();assert.equal(analysisActive('p'),false);assert.equal(elements['#stop-analysis'].hidden,true);
 state.analysis_jobs.p={id:'new',paper_id:'p',status:'running',mode:'deep'};
 poll({id:'old',paper_id:'p',status:'cancelled'});await observer;
 assert.equal(state.analysis_jobs.p.id,'new');assert.equal(analysisActive('p'),true);
}
`,c);
vm.runInContext('test()',c).catch(e=>{console.error(e);process.exitCode=1});
'''], cwd=store.ROOT, check=True, timeout=15)
