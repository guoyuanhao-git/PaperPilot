import shutil
import subprocess
import unittest
from paperpilot import store


@unittest.skipUnless(shutil.which('node'), 'Node required')
class ReadingChatEntryUI(unittest.TestCase):
    def test_visibility_and_reading_anchor_across_layouts(self):
        subprocess.run(['node', '-e', r'''
const vm=require('vm'),fs=require('fs'),assert=require('assert/strict');
let callback,disconnected=0,clicked=0;
const floating={hidden:true},win={scrollY:700,scrollTo({top}){this.scrollY=top}};
const context={window:win,document:{getElementById:()=>floating},
 IntersectionObserver:class{constructor(cb){callback=cb}observe(){}disconnect(){disconnected++}}};
vm.createContext(context);vm.runInContext(fs.readFileSync('web/reading-chat-entry.js','utf8'),context);
const api=context.ReadingChatEntry;
let bottom=80,expanded=false;
const top={isConnected:true,getAttribute:()=>String(expanded),getBoundingClientRect:()=>({bottom})};
api.connect(top,floating,()=>clicked++);assert.equal(floating.hidden,true);
bottom=-2;callback();assert.equal(floating.hidden,false);floating.onclick();assert.equal(clicked,1);
bottom=12;callback();assert.equal(floating.hidden,true);
expanded=true;api.connect(top,floating,()=>{});assert.equal(floating.hidden,true);
assert.equal(disconnected,1);
api.connect(null,floating,()=>{});assert.equal(floating.hidden,true);
// A paragraph halfway clipped before opening remains halfway clipped after reflow.
let rect={top:-26,bottom:74,height:100},columnTop=-400;
const block={closest:()=>null,getBoundingClientRect:()=>rect};
const column={scrollTop:0,querySelectorAll:()=>[block],getBoundingClientRect:()=>({top:columnTop})};
const saved=api.capture(column,false);assert.equal(saved.fraction,.5);
columnTop=180;rect={top:580,bottom:780,height:200};api.restore(column,saved,true);
assert.equal(column.scrollTop,484);assert.equal(win.scrollY,0);
rect={top:96,bottom:296,height:200};const back=api.capture(column,true);
assert.equal(back.fraction,.5);
columnTop=300;rect={top:900,bottom:1000,height:100};api.restore(column,back,false);
assert.equal(win.scrollY,926);
// Starting above the report should keep the report at its beginning in split view.
columnTop=300;rect={top:350,bottom:450,height:100};
const start=api.capture(column,false);api.restore(column,start,true);assert.equal(column.scrollTop,0);
'''], cwd=store.ROOT, check=True)
