import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch
import test_core
from paperpilot import cancellation, documents, providers, service, store


class ChatCancellation(unittest.TestCase):
    setUp = test_core.Core.setUp
    tearDown = test_core.Core.tearDown
    wait_job = test_core.Core.wait_job

    def settle(self):
        deadline = time.monotonic()+4
        while store.TASKS.get(str(store.data_dir()),0) and time.monotonic()<deadline:
            time.sleep(.01)
        self.assertEqual(store.TASKS.get(str(store.data_dir()),0),0)

    def test_cancel_discards_late_answer_and_memory_then_allows_edited_question(self):
        paper=documents.ingest(test_core.pdf(),'chat.pdf')
        started,release=threading.Event(),threading.Event()
        def generate(config,system,messages,images):
            question=messages[-1]['content']
            if question=='mistake':
                started.set();release.wait(3)
            return {'value':'answer '+question,'provider':'fixture','model':'test','usage':{}}
        with patch('paperpilot.providers.generate',side_effect=generate), patch('paperpilot.assistant_memory.capture') as memory:
            first=service.chat(paper['id'],'mistake')
            self.assertTrue(started.wait(2))
            with self.assertRaisesRegex(ValueError,'仍有回答'):
                service.chat(paper['id'],'duplicate')
            self.assertEqual(service.cancel_chat(first['id'])['status'],'cancelled')
            second=self.wait_job(service.chat(paper['id'],'corrected'))
            self.assertEqual(second['status'],'completed')
            release.set();self.settle()
            saved=store.get('paper',paper['id'])
            self.assertEqual([m['content'] for m in saved['messages']],['corrected','answer corrected'])
            self.assertEqual(memory.call_count,1)
            self.assertEqual(memory.call_args.args[1],'corrected')
            self.assertEqual(store.get('job',first['id'])['status'],'cancelled')
            # An already committed answer is not falsely reported as cancelled.
            self.assertEqual(service.cancel_chat(second['id'])['status'],'completed')

    def test_cancel_queued_job_never_calls_model_and_is_account_scoped(self):
        paper=documents.ingest(test_core.pdf(),'queued.pdf');queued=[]
        with patch.object(service.EXECUTOR,'submit',side_effect=lambda run:queued.append(run)), patch('paperpilot.providers.generate') as generate:
            job=service.chat(paper['id'],'queued question')
            other=store.data_dir()/'other';other.mkdir()
            with store.scope({'directory':other}):
                store.init()
                with self.assertRaises(ValueError):service.cancel_chat(job['id'])
            service.cancel_chat(job['id']);queued[0]()
            generate.assert_not_called()
            self.assertEqual(store.get('job',job['id'])['status'],'cancelled')
            self.assertFalse(store.get('paper',paper['id'])['messages'])

    def test_local_process_is_terminated(self):
        control=cancellation.Control();token=cancellation.CURRENT.set(control)
        timer=threading.Timer(.2,control.cancel);timer.start();processes=[]
        real=subprocess.Popen
        def start(*args,**kwargs):
            p=real(*args,**kwargs);processes.append(p);return p
        try:
            with patch('paperpilot.cancellation.subprocess.Popen',side_effect=start):
                with self.assertRaises(cancellation.Cancelled):
                    cancellation.run_process([sys.executable,'-c','import time; time.sleep(30)'],env=None,input='test',timeout=40)
            self.assertIsNotNone(processes[0].poll())
        finally:
            timer.cancel();cancellation.CURRENT.reset(token)

    def test_http_wait_is_cancelled_and_connection_closed(self):
        control=cancellation.Control();token=cancellation.CURRENT.set(control)
        closed=threading.Event();opened=threading.Event()
        class Response:
            def close(self):closed.set()
        def request():
            with cancellation.response_connection(Response()):
                opened.set();closed.wait(3)
                return 'late answer'
        timer=threading.Thread(target=lambda:(opened.wait(2),control.cancel()));timer.start()
        try:
            with self.assertRaises(cancellation.Cancelled):cancellation.http_call(request)
            self.assertTrue(closed.wait(1))
        finally:
            timer.join(2);cancellation.CURRENT.reset(token)
