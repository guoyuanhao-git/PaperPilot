import shutil
import subprocess
import unittest
from paperpilot import store


@unittest.skipUnless(shutil.which('node'), 'Node required')
class HotspotTriageUI(unittest.TestCase):
    def test_filtering_and_restoration_share_paper_identity(self):
        subprocess.run(['node', '-e', r'''
const vm=require('vm'),fs=require('fs'),assert=require('assert/strict');
const context=vm.createContext({URL,console,assert,setInterval:()=>0,document:{addEventListener(){}}});
vm.runInContext(`
let state={hotspot_skips:[],profile:{research_directions:''}},cardRefs=[];
let hfOnlyRelevant=false,hfTopicSelection=new Set(),busy=false,hfLoading=false;
const paper={id:'p',title:'Example paper',paper_url:'https://arxiv.org/abs/2501.12345v2',abstract:'Abstract'};
let hfResult={id:'list',items:[paper],research_directions:'',topic_options:{},days:1,dates:['2025-01-01'],complete:true};
const esc=String,date=String,sourceLabel=String;
function foldPanel(id,title,meta,body){return body}function paperCard(p){return '<paper>'+p.title+'</paper>'}function sourceStates(){return ''}
let renders=0,samePage=true;
function navigationContext(){return {}}function stillAt(){return samePage}function render(){renders++}
async function request(path,body){return {id:'saved',identity:'paper:arxiv:2501.12345',kind:'paper',item:paper,day:hotspotBrowsingDay()}}
`+fs.readFileSync('web/discover-view.js','utf8')+`
async function test(){
 assert.equal(hotspotIdentity(paper),'paper:arxiv:2501.12345');
 assert.equal(hotspotIdentity({paper_url:'https://huggingface.co/papers/2501.12345'}),hotspotIdentity(paper));
 assert(hfResults().includes('<paper>Example paper</paper>'));
 cardRefs.push({paper,origin:'hf-listing',runId:'list'});
 await skipHotspot({dataset:{skipHotspot:'0'},disabled:false});
 assert.equal(renders,1);assert(!hfResults().includes('<paper>Example paper</paper>'));
 assert.equal(hfResult.items.length,1);assert.equal(hotspotIsSkipped(paper),true);
 assert.equal(hotspotIsSkipped({source_url:paper.paper_url},'article'),false);
 hotspotSkippedOpen=true;assert(skippedHotspots().includes('Example paper'));
 samePage=false;await restoreHotspot({dataset:{restoreHotspot:'saved'},disabled:false});
 assert.equal(renders,1);assert.equal(state.hotspot_skips.length,0);
 assert(hfResults().includes('<paper>Example paper</paper>'));
 assert(skippedHotspots().includes('已恢复'));
}
`,context);
vm.runInContext('test()',context).catch(e=>{console.error(e);process.exitCode=1});
'''], cwd=store.ROOT, check=True, timeout=10)
