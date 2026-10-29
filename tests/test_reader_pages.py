"""Independent reader routes and per-paper generation scheduling."""
import shutil
import subprocess
import threading
import unittest
from unittest.mock import patch
import test_core
from paperpilot import documents, service, store


class IndependentReader(unittest.TestCase):
    setUp = test_core.Core.setUp
    tearDown = test_core.Core.tearDown
    wait_job = test_core.Core.wait_job

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_routes_pin_account_and_select_only_relevant_jobs(self):
        subprocess.run(['node','-e',r'''
const assert=require('node:assert/strict'),r=require('./web/reader-state.js');
const papers=[{id:'a'},{id:'b'}];
assert.equal(r.link('a','user1'),'/?paper=a&account=user1');
assert.deepEqual(r.route('?paper=b&account=user1','user1',papers),{paperId:'b'});
assert.ok(r.route('?paper=b&account=user1','user2',papers).error);
assert.ok(r.route('?paper=deleted&account=user1','user1',papers).error);
assert.equal(r.route('','user1',papers),null);
const s={analysis_jobs:{a:{id:'1',paper_id:'a',status:'running'},b:{id:'2',paper_id:'b',status:'queued'},c:{id:'3',paper_id:'c',status:'failed'}}};
assert.deepEqual(r.pendingAnalyses(s,'a').map(j=>j.id),['1']);
assert.deepEqual(r.pendingAnalyses(s).map(j=>j.id),['1','2']);
'''],cwd=store.ROOT,check=True,timeout=15)

    def test_two_analyses_are_independent_and_duplicate_is_rejected(self):
        p=documents.ingest(test_core.pdf(),'first.pdf')
        q={**p,'id':'b'*20,'title':'Second test paper'};store.save('paper',q)
        # Keep actions queued, so no network call or paid generation is made.
        with patch.object(service.EXECUTOR,'submit'):
            a=service.analyze(p['id'],'overview')
            b=service.analyze(q['id'],'detailed')
            with self.assertRaisesRegex(ValueError,'仍在生成'):
                service.analyze(p['id'],'overview')
        self.assertNotEqual(a['id'],b['id'])
        self.assertEqual(a['paper_id'],p['id']);self.assertEqual(b['paper_id'],q['id'])
        self.assertEqual(a['mode'],'overview');self.assertEqual(b['mode'],'detailed')
        store.TASKS.pop(str(store.data_dir()),None)

    def test_executor_runs_three_jobs_and_queues_the_fourth(self):
        started=[threading.Event() for _ in range(4)]
        release=threading.Event()
        def task(ident):
            def run(progress):
                progress('test '+str(ident));started[ident].set()
                if not release.wait(5):
                    raise ValueError('Test timed out')
                return {'paper_id':str(ident)}
            return run
        jobs=[service.job('analysis',task(i),str(i)) for i in range(4)]
        try:
            for event in started[:3]:self.assertTrue(event.wait(3))
            self.assertFalse(started[3].is_set())
            self.assertEqual(store.get('job',jobs[3]['id'])['status'],'queued')
        finally:
            release.set()
        for i,job in enumerate(jobs):
            result=self.wait_job(job)
            self.assertEqual(result['status'],'completed')
            self.assertEqual(result['result']['paper_id'],str(i))
