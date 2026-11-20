import copy
import tempfile
import unittest
from pathlib import Path
from paperpilot import documents, store
from test_core import pdf


class FigureRemoval(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.scope = store.scope({'directory':Path(self.temp.name)})
        self.scope.__enter__()
        store.init()
        self.paper = documents.ingest(pdf(), 'synthetic.pdf')
        self.figure = copy.deepcopy(self.paper['figures'][0])
        self.paper['report'] = {'figures':[copy.deepcopy(self.figure)], 'sections':[{'figures':[self.figure['id']]}]}
        self.paper['notes'] = 'Keep notes'
        store.save('paper', self.paper)

    def tearDown(self):
        self.scope.__exit__(None, None, None)
        self.temp.cleanup()

    def test_removal_preserves_report_images_and_reserves_ids(self):
        image = documents.figure_bytes(self.paper['id'], self.figure)
        original = (documents.directory(self.paper['id'])/'source.pdf').read_bytes()
        updated = documents.remove_figure(self.paper['id'], self.figure['id'], self.figure)
        self.assertEqual(updated['figures'], [])
        self.assertEqual(updated['report'], self.paper['report'])
        self.assertEqual(updated['notes'], 'Keep notes')
        self.assertEqual(documents.figure_bytes(self.paper['id'], updated['report']['figures'][0]), image)
        self.assertEqual((documents.directory(self.paper['id'])/'source.pdf').read_bytes(), original)
        self.assertGreater(documents.next_figure_number(updated), int(self.figure['id'][4:]))
        # Even after deleting the report, a new crop cannot reuse the removed ID.
        updated['report'] = None
        self.assertGreater(documents.next_figure_number(updated), int(self.figure['id'][4:]))

    def test_duplicate_aliases_removed_and_inventory_does_not_restore_candidate(self):
        alias = dict(self.figure, id='fig-99', duplicate_of=self.figure['id'])
        self.paper['figures'].append(alias)
        store.save('paper', self.paper)
        updated = documents.remove_figure(self.paper['id'], self.figure['id'], self.figure)
        self.assertEqual(updated['figures'], [])
        self.assertEqual(documents.next_figure_number(updated), 100)
        updated['figure_inventory_version'] = 0
        documents.inventory(updated)
        self.assertEqual(updated['figures'], [])

    def test_changed_figure_or_running_job_refuses_removal(self):
        with self.assertRaisesRegex(ValueError, '已变化'):
            documents.remove_figure(self.paper['id'], self.figure['id'], dict(self.figure,caption='stale'))
        store.save('job', {'id':'busy','paper_id':self.paper['id'],'status':'running'})
        with self.assertRaisesRegex(ValueError, '任务正在运行'):
            documents.remove_figure(self.paper['id'], self.figure['id'], self.figure)
        self.assertEqual(store.get('paper',self.paper['id'])['figures'],self.paper['figures'])

    def test_account_isolation(self):
        with tempfile.TemporaryDirectory() as other, store.scope({'directory':Path(other)}):
            store.init()
            with self.assertRaises(ValueError):
                documents.remove_figure(self.paper['id'], self.figure['id'], self.figure)
        self.assertEqual(store.get('paper',self.paper['id'])['figures'],self.paper['figures'])
