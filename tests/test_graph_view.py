import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class GraphView(unittest.TestCase):
    def test_personal_salience_and_real_neighbors_without_invented_direction(self):
        subprocess.run(['node', '-e', r'''
const assert=require('node:assert/strict'),{decorate}=require('./web/graph-metrics.js');
const nodes=['a','b','c','d'].map(id=>({id,starred:false}));
const edges=[{source:'a',target:'b'},{source:'a',target:'c'},{source:'a',target:'b'},{source:'b',target:'a'},{source:'c',target:'c'},{source:'a',target:'missing'}];
const before=JSON.stringify([nodes,edges]);
const result=decorate(nodes,edges,[]),byId=new Map(result.map(n=>[n.id,n]));
assert.equal(byId.get('a').degree,2);assert.equal(byId.get('b').degree,1);assert.equal(byId.get('d').degree,0);
assert(byId.get('a').graphSize>byId.get('b').graphSize);assert(byId.get('b').graphSize>byId.get('d').graphSize);
assert.notEqual(byId.get('a').graphColor,byId.get('d').graphColor);
assert.equal(JSON.stringify([nodes,edges]),before);
const base=decorate([{id:'x'}],[],[])[0];
const read=decorate([{id:'x'}],[],[{id:'x',read_status:'已速览'}])[0];
const deep=decorate([{id:'x'}],[],[{id:'x',read_status:'已精读'}])[0];
const starred=decorate([{id:'x',starred:true}],[],[{id:'x',read_status:'已精读'}])[0];
assert(base.importance<read.importance&&read.importance<deep.importance&&deep.importance<starred.importance);
assert(Number.isFinite(base.graphRadius)&&base.graphRadius>0);
assert.equal(starred.readStatus,'已精读');assert(!('inDegree' in starred));
const favoriteScope=decorate([{id:'x',starred:true}],[],[{id:'x',read_status:'已精读'}],'starred')[0];
assert.equal(favoriteScope.importance,starred.importance); // Preferences distinguish core tiers in either scope.
const liked=decorate([{id:'x',liked:true}],[],[{id:'x',read_status:'已精读'}],'starred')[0];
assert(deep.importance<liked.importance&&liked.importance<favoriteScope.importance);
assert.equal(favoriteScope.degree,starred.degree);
const relevant=decorate([{id:'x',relevance:3}],[],[])[0];
assert(relevant.importance>starred.importance); // Current research takes priority over star/read signals.
assert(relevant.graphColor!==base.graphColor);
'''], cwd=Path(__file__).resolve().parent.parent, check=True, capture_output=True)
