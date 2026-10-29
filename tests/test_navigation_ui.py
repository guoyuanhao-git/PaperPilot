"""Front-end async navigation regressions, without calling a model or live data."""
import shutil
import subprocess
import unittest

from paperpilot import store


@unittest.skipUnless(shutil.which("node"), "Node required")
class NavigationUI(unittest.TestCase):
    def test_nested_scroll_and_late_images_do_not_reset_the_list(self):
        subprocess.run(['node', '-e', r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const events=new Map(),imageEvents=new Map();let frame;
const win={scrollX:0,scrollY:1600,scrollTo:p=>{win.scrollY=p.top},addEventListener:(k,f)=>events.set(k,f),removeEventListener:k=>events.delete(k)};
let offset=2400;
const scroller={dataset:{scrollKey:'figures'},scrollTop:2375,scrollLeft:0,getBoundingClientRect:()=>({top:200,bottom:660}),querySelectorAll:()=>[anchor]};
const anchor={dataset:{viewAnchor:'figure-12'},closest:()=>scroller,getBoundingClientRect:()=>({top:200+offset-scroller.scrollTop,bottom:420+offset-scroller.scrollTop})};
const img={complete:false,naturalWidth:0,naturalHeight:0,addEventListener:(k,f)=>imageEvents.set(k,f),removeEventListener:k=>imageEvents.delete(k)};
const app={firstElementChild:{},contains:()=>false,querySelectorAll:s=>s==='[data-scroll-key]'?[scroller]:s==='[data-view-anchor]'?[anchor]:s==='img'?[img]:[]};
const context=vm.createContext({window:win,document:{activeElement:null,getElementById:()=>null},setTimeout:()=>1,clearTimeout(){},requestAnimationFrame:f=>{frame=f;return 1},cancelAnimationFrame:()=>{frame=null}});
vm.runInContext(fs.readFileSync('web/view-continuity.js','utf8'),context);
const api=context.ViewContinuity,snapshot=api.capture(app);
scroller.scrollTop=0;api.restorePosition(app,snapshot);
assert.equal(scroller.scrollTop,2375);assert.equal(win.scrollY,1600);
api.settleImages(app,snapshot);
offset+=200;img.complete=true;imageEvents.get('load')();frame();
assert.equal(scroller.scrollTop,2575); // The same figure stays 25 px below the list top.
assert.equal(win.scrollY,1600);
img.complete=false;api.settleImages(app,api.capture(app));
events.get('wheel')();scroller.scrollTop=3000;offset+=200;
assert.equal(imageEvents.size,0);assert.equal(frame,null);assert.equal(scroller.scrollTop,3000);
'''], cwd=store.ROOT, check=True, timeout=15)

    def test_background_results_do_not_take_over_navigation(self):
        subprocess.run(["node", "-e", r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('web/app.js','utf8');
const helpers=source.slice(source.indexOf('let navigationRevision='),source.indexOf('async function reload('));
const jobs=source.slice(source.indexOf('async function runJob('),source.indexOf('async function saveSettings('));
const context=vm.createContext({assert,console,setTimeout,URLSearchParams});
vm.runInContext(`
let state={papers:[{id:'a'},{id:'b'}],accounts:{revision:'u1'},knowledge:{}};
let selected=state.papers[0],view='paper',busy=false,discoveryMode='filter';
let knowledgeMainline='',knowledgeScope='all',knowledgeProvider='';
let hfResult,hfOnlyRelevant,hfError,searchResult,requests=0,renders=0;
const hfTopicSelection=new Set(),names={},elements={};
const $=key=>elements[key]||(elements[key]={});
function render(){renders++}
function toast(){}
function setFoldExpanded(){}
let onReload=()=>{},requestImpl;
async function reload(){await onReload()}
async function request(...args){requests++;return requestImpl(...args)}
`+helpers+jobs+`
function reset(){
 view='paper';selected=state.papers[0];busy=false;navigationRevision++;
 onReload=()=>{};knowledgeMainline='';knowledgeScope='all';knowledgeProvider='';
}
async function test(){
 reset();
 await runJob({kind:'analyze',status:'completed',result:{paper_id:'a'}});
 assert.equal(view,'paper');assert.equal(selected.id,'a');
 // Navigation while fetching fresh data must be checked after the await.
 reset();onReload=()=>{view='library';navigationRevision++};
 await runJob({kind:'analyze',status:'completed',result:{paper_id:'a'}});
 assert.equal(view,'library');
 reset();onReload=()=>{selected=state.papers[1];navigationRevision++};
 await runJob({kind:'analyze',status:'completed',result:{paper_id:'a'}});
 assert.equal(selected.id,'b');assert.equal(view,'paper');
 // A removed/missing result must not assign undefined and trigger library fallback.
 reset();
 await runJob({kind:'analyze',status:'completed',result:{paper_id:'removed'}});
 assert.equal(selected.id,'a');assert.equal(view,'paper');
 // The origin is recorded BEFORE the initial POST response, even if user returns.
 reset();let resolve;
 requestImpl=()=>new Promise(r=>resolve=r);
 const starting=startJob('/api/analyze',{id:'a'});
 navigationRevision+=2;selected=state.papers[1];
 resolve({kind:'analyze',status:'completed',result:{paper_id:'a'}});
 await starting;assert.equal(selected.id,'b');
 reset();onReload=()=>{view='paper';selected=state.papers[1];navigationRevision++};
 await runJob({kind:'discovery',status:'completed',result:{items:[]}});
 assert.equal(view,'paper');assert.equal(selected.id,'b');assert.ok(searchResult);
 reset();view='knowledge';
 onReload=()=>{view='paper';selected=state.papers[1];navigationRevision++};
 await assert.rejects(runJob({kind:'knowledge',status:'failed',error:'failed'}),/failed/);
 assert.equal(view,'paper');assert.equal(busy,false);
 // Slow paper saves update the matching record, never replace a different selection.
 reset();selected=state.papers[1];
 acceptPaperUpdate({id:'a',title:'Updated A'});
 assert.equal(selected.id,'b');assert.equal(state.papers[0].title,'Updated A');
 reset();const origin=navigationContext();navigationRevision+=2;
 assert.equal(stillAt(origin),false);
 reset();view='knowledge';const graphOrigin=navigationContext();knowledgeMainline='another';
 assert.equal(stillAt(graphOrigin),false);
}
`,context);
vm.runInContext('test()',context).catch(e=>{console.error(e);process.exitCode=1});
"""], cwd=store.ROOT, check=True, timeout=15)

    def test_in_place_render_restores_details_focus_and_reading_anchor(self):
        subprocess.run(["node", "-e", r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
let current,focused,scroll;
const window={scrollX:0,scrollY:900,scrollTo:p=>scroll=p};
const document={get activeElement(){return focused},getElementById:()=>current.input};
function page(top,open){
 const detail={id:'source',open,closest:()=>null,querySelector:()=>({textContent:'Source'})};
 const image={naturalWidth:600,naturalHeight:400,style:{},getAttribute:()=>'/image.png'};
 const anchor={closest:()=>null,dataset:{viewAnchor:'report-results'},getBoundingClientRect:()=>({top,bottom:top+800})};
 const input={id:'notes',selectionStart:2,selectionEnd:4,focus:opts=>{assert.equal(opts.preventScroll,true);focused=input},setSelectionRange:(a,b)=>input.selection=[a,b]};
 return {detail,image,input,contains:el=>el===input,querySelectorAll:selector=>selector==='img'?[image]:selector==='[data-view-anchor]'?[anchor]:selector==='[data-scroll-key]'?[]:[detail]};
}
const context=vm.createContext({window,document,Map});
vm.runInContext(fs.readFileSync('web/view-continuity.js','utf8'),context);
current=page(50,true);focused=current.input;
const snapshot=context.ViewContinuity.capture(current);
current=page(250,false);focused=null;
context.ViewContinuity.restoreContent(current,snapshot);
context.ViewContinuity.restorePosition(current,snapshot);
assert.equal(current.detail.open,true);
assert.equal(current.image.style.aspectRatio,'600/400');
assert.deepEqual(current.input.selection,[2,4]);
assert.equal(scroll.top,1100);assert.equal(scroll.behavior,'instant');
// A different page receives no snapshot and must keep its own initial state.
current=page(0,false);scroll=null;
context.ViewContinuity.restoreContent(current,null);
context.ViewContinuity.restorePosition(current,null);
assert.equal(current.detail.open,false);assert.equal(scroll,null);
"""], cwd=store.ROOT, check=True, timeout=15)
