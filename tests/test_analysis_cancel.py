"""Stopping a reading task must never replace a saved report with a late result."""
import threading
import unittest
from unittest.mock import patch
import test_core
import test_chat_cancel
from paperpilot import documents, service, store


class AnalysisCancellation(unittest.TestCase):
    setUp = test_core.Core.setUp
    tearDown = test_core.Core.tearDown
    wait_job = test_core.Core.wait_job
    settle = test_chat_cancel.ChatCancellation.settle

    def test_cancel_running_preserves_report_and_can_restart(self):
        paper = documents.ingest(test_core.pdf(), 'reading.pdf')
        paper['report'] = {'title': 'saved report'}
        store.save('paper', paper)
        started, release = threading.Event(), threading.Event()
        def build(*args):
            started.set()
            release.wait(3)
            return {'title': 'late result'}, []
        with patch('paperpilot.reading.build', side_effect=build), patch('paperpilot.assistant_memory.capture'):
            first = service.analyze(paper['id'], 'overview')
            self.assertTrue(started.wait(2))
            self.assertEqual(service.cancel_analysis(first['id'])['status'], 'cancelled')
            # A different mode can be queued immediately, independently of the old response.
            queued = []
            with patch.object(service.EXECUTOR, 'submit', side_effect=lambda run: queued.append(run)):
                second = service.analyze(paper['id'], 'deep')
                self.assertEqual(second['mode'], 'deep')
                service.cancel_analysis(second['id'])
                queued[0]()
            release.set()
            self.settle()
        self.assertEqual(store.get('paper', paper['id'])['report']['title'], 'saved report')
        self.assertEqual(store.get('job', first['id'])['status'], 'cancelled')

    def test_queued_cancel_is_scoped_and_never_builds(self):
        paper = documents.ingest(test_core.pdf(), 'queued.pdf')
        queued = []
        with patch.object(service.EXECUTOR, 'submit', side_effect=lambda run: queued.append(run)), patch('paperpilot.reading.build') as build:
            job = service.analyze(paper['id'], 'overview')
            with self.assertRaises(ValueError):
                service.cancel_chat(job['id'])
            other = store.data_dir() / 'other'; other.mkdir()
            with store.scope({'directory': other}):
                store.init()
                with self.assertRaises(ValueError):
                    service.cancel_analysis(job['id'])
            service.cancel_analysis(job['id'])
            queued[0]()
            build.assert_not_called()
            self.assertEqual(store.get('job', job['id'])['status'], 'cancelled')

    def test_committed_report_cannot_be_cancelled(self):
        paper = documents.ingest(test_core.pdf(), 'committed.pdf'); queued = []
        with patch.object(service.EXECUTOR, 'submit', side_effect=lambda run: queued.append(run)):
            job = service.analyze(paper['id'], 'overview')
            control = service.CHAT_CONTROLS[(str(store.data_dir()), job['id'])]
            control.committed = True
            self.assertEqual(service.cancel_analysis(job['id'])['status'], 'completed')
            self.assertFalse(control.event.is_set())
            control.committed = False
            service.cancel_analysis(job['id']); queued[0]()
