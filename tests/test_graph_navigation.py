import json
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch
from paperpilot import store, knowledge, knowledge_backbone, user_profile
import test_core


class Backbone(unittest.TestCase):
    setUp = test_core.Core.setUp
    tearDown = test_core.Core.tearDown

    def fixture(self):
        nodes = [{'id':str(i),'title':f'Paper {i}','insight':'可验证的方法'} for i in range(6)]
        edges = [{'source':str(i),'target':str(j),'priority':3,'relation':'方法差异','reason':'具体机制不同','research_use':'比较机制','quote_a':'Evidence A','quote_b':'Evidence B'} for i in range(6) for j in range(i+1,6)]
        return nodes, edges

    def model(self, c, system, messages, **kwargs):
        rows=json.loads(messages[0]['content'].split('\n',1)[1])
        return {'value':{'choices':[{'id':r['id'],'keep':[e['id'] for e in r['links'] if '0' in e['id'].split('|')],'role':'foundation','reason':'保留基础机制与其独立发展之间的关系。'} for r in rows]}}

    def test_refine_preserves_hub_evidence_cache_and_user_context(self):
        nodes,edges=self.fixture();before=json.dumps(edges)
        c=knowledge.config(knowledge.CORE_KEY)
        with patch('paperpilot.providers.generate',side_effect=self.model) as call:
            result=knowledge_backbone.refine(lambda _:None,nodes,edges,c)
            self.assertEqual(len(result['backbone_pairs']),5)
            self.assertEqual(call.call_count,2) # six neighborhoods batched into two calls
            knowledge_backbone.refine(lambda _:None,nodes,edges,c)
            self.assertEqual(call.call_count,2)
        self.assertEqual(json.dumps(edges),before)
        knowledge.forget('0')
        self.assertFalse(store.all_objects('knowledge_backbone'))

    def test_unknown_edge_ids_cannot_enter_backbone(self):
        nodes,edges=self.fixture()
        def invalid(*args,**kwargs):
            value=self.model(*args,**kwargs)
            for row in value['value']['choices']:row['keep']=['unknown|paper']
            return value
        with patch('paperpilot.providers.generate',side_effect=invalid), self.assertRaisesRegex(ValueError,'本批已有联系'):
            knowledge_backbone.refine(lambda _:None,nodes,edges,knowledge.config(knowledge.CORE_KEY))

    def test_mainline_copies_core_selection_without_rejudging_it(self):
        nodes,edges=self.fixture()
        core={'nodes':nodes,'edges':edges,'backbone_pairs':['0|1'],'node_roles':{'0':'foundation'}}
        with patch('paperpilot.providers.generate') as call:
            result=knowledge_backbone.refine(lambda _:None,nodes,edges,knowledge.config(),core)
        call.assert_not_called();self.assertEqual(result['backbone_pairs'],['0|1'])


@unittest.skipUnless(shutil.which('node'),'Node required')
class Navigation(unittest.TestCase):
    def test_macro_micro_hubs_search_and_no_data_loss(self):
        subprocess.run(['node','-e',r'''
const assert=require('node:assert/strict'),nav=require('./web/graph-navigation.js');
const nodes=Array.from({length:24},(_,i)=>({id:String(i).padStart(2,'0'),label:'Paper '+i,title:'Title '+i,tags:['topic'+i%4],relevance:i===23?0:3,starred:i<4,liked:i>=4&&i<12}));
const edges=nodes.flatMap((n,i)=>nodes.slice(i+1).map(m=>({source:n.id,target:m.id,priority:3,relation:'test'})));
const before=JSON.stringify([nodes,edges]),pairs=edges.map(nav.key);
const domainNodes=nodes.filter(n=>n.starred||n.liked);
const overview=nav.plan(domainNodes,edges,{scope:'starred',pairs});
assert.equal(overview.nodes.length,4);assert.equal(overview.edges.length,6);
const expanded=nav.plan(domainNodes,edges,{scope:'starred',pairs,all:true});
assert.equal(expanded.nodes.length,12);assert(expanded.edges.every(e=>e.source<'04'||e.target<'04'));
for(const e of overview.edges)assert(expanded.edges.includes(e));
const line=nav.plan(nodes,edges,{scope:'all',pairs});assert.equal(line.nodes.length,12);
const likePair=nav.plan(nodes,edges,{scope:'all',pairs:['04|05']});assert(likePair.edges.some(e=>e.source==='04'&&e.target==='05')); // Likes can connect in a mainline.
assert(line.edges.length<=line.nodes.length*1.5);
const all=nav.plan(nodes,edges,{scope:'all',pairs,all:true});assert.equal(all.nodes.length,23);
assert(all.edges.every(e=>e.source<'12'||e.target<'12')); // Read-read hidden globally.
for(const e of line.edges)assert(all.edges.includes(e));
const focused=nav.plan(nodes,edges,{scope:'all',pairs,focus:'22',limit:24});
assert.equal(focused.edges.length,23);assert(focused.nodes.some(n=>n.id==='23')); // Focus includes weak neighbors.
assert(focused.edges.some(e=>e.source==='22'&&e.target==='23'));
assert.equal(nav.plan(nodes,edges,{scope:'all',focus:'22'}).edges.length,6);
assert(nav.plan(nodes,edges,{query:'Paper 23'}).nodes.some(n=>n.id==='23'));
const likes=domainNodes.filter(n=>n.liked);assert.equal(nav.plan(likes,edges,{scope:'starred'}).nodes.length,likes.length);
const island=nav.plan([{id:'x',liked:true,label:'x',title:'x'}],[],{scope:'starred',all:true});assert.equal(island.nodes.length,1);assert.equal(island.edges.length,0);
const star=edges.filter(e=>e.source==='00');assert.equal(nav.backbone(nodes,star).length,23); // No hub degree cap.
assert.equal(nav.plan(nodes,edges,{pairs:[]}).edges.length,0);
assert.equal(JSON.stringify([nodes,edges]),before);
assert.equal(nav.plan([],[],{}).nodes.length,0);
'''],cwd=Path(__file__).resolve().parent.parent,check=True,capture_output=True)
