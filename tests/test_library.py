"""Reading actions, distinct paper counts, migration and independent stars."""
import subprocess
import shutil
import unittest
from datetime import datetime
from unittest.mock import patch
import test_core
from paperpilot import documents, library, service, store


class Library(unittest.TestCase):
    setUp = test_core.Core.setUp
    tearDown = test_core.Core.tearDown
    wait_job = test_core.Core.wait_job

    def paper(self, mode='overview'):
        p = documents.ingest(test_core.pdf(), 'fixture.pdf')
        self.assertEqual(p['read_status'], '未标记')
        p.update(publication_month='2021-06', short_title='Fixture')
        p['report'] = {'mode': mode, 'generated_at': '2026-10-13T02:00:00+00:00'}
        library.report_ready(p)
        return store.save('paper', p)

    def finish(self, p, at='2026-10-13T03:00:00+00:00'):
        with patch('paperpilot.library.now', return_value=at):
            return library.change(p['id'], 'finish', p['report']['generated_at'])

    def test_like_star_switches_are_exclusive_and_preserve_reading(self):
        p = self.finish(self.paper())
        events = p['reading_completions']
        for choice in ('liked', 'starred', 'liked', 'none'):
            p = library.change(p['id'], 'preference', preference=choice)
            self.assertEqual(p['liked'], choice == 'liked')
            self.assertEqual(p['starred'], choice == 'starred')
            self.assertEqual(p['read_status'], '已速览')
            self.assertEqual(p['reading_completions'], events)
        p = library.change(p['id'], 'preference', preference='liked')
        p = library.change(p['id'], 'star', starred=True)
        self.assertFalse(p['liked']); self.assertTrue(p['starred'])
        for invalid in (None, True, 'favorite', ['liked']):
            with self.assertRaises(ValueError):
                library.change(p['id'], 'preference', preference=invalid)
        self.assertTrue(store.get('paper', p['id'])['starred'])

    def test_liked_paper_remains_liked_when_reading_completes(self):
        p = self.paper()
        library.change(p['id'], 'preference', preference='liked')
        p = self.finish(p)
        self.assertTrue(p['liked']); self.assertFalse(p['starred'])
        p = library.change(p['id'], 'start')
        self.assertTrue(p['liked']); self.assertEqual(p['read_status'], '未标记')
        p = library.change(p['id'], 'preference', preference='none')
        self.assertEqual(p['read_status'], '未标记')

    def test_modes_stars_notes_and_idempotent_completion(self):
        p = self.paper()
        self.assertEqual(p['read_status'], '待阅读')
        p = library.change(p['id'], 'star', starred=True)
        p = self.finish(p)
        self.assertEqual(p['read_status'], '已速览')
        self.assertTrue(p['starred'])
        self.assertEqual(p['notes'], '')
        p = self.finish(p)
        self.assertEqual(len(p['reading_completions']), 1)
        p = library.change(p['id'], 'star', starred=False)
        self.assertEqual(p['read_status'], '已速览')
        p = library.change(p['id'], 'start')
        self.assertEqual(p['read_status'], '未标记')
        p = self.finish(p)
        self.assertEqual(len(p['reading_completions']), 2)
        for mode in ('detailed', 'deep'):
            p['report'].update(mode=mode, generated_at='2026-10-13T04:00:00+00:00')
            library.report_ready(p)
            store.save('paper', p)
            p = self.finish(p)
            self.assertEqual(p['read_status'], '已精读')
        at = datetime.fromisoformat('2026-10-13T15:00:00+08:00')
        self.assertEqual(library.statistics([p], at), {'today': 1, 'week': 1})

    def test_missing_or_stale_report_cannot_complete(self):
        p = documents.ingest(test_core.pdf(), 'fixture.pdf')
        with self.assertRaises(ValueError):
            library.change(p['id'], 'finish')
        p = self.paper()
        with self.assertRaises(ValueError):
            library.change(p['id'], 'finish', 'old-report')
        self.assertEqual(store.get('paper', p['id'])['reading_completions'], [])
        with self.assertRaises(ValueError):
            library.change(p['id'], 'star', starred='true')

    def test_sunday_and_midnight_boundaries_unique_papers(self):
        def paper(*times):
            return {'reading_completions': [{'at': t} for t in times]}
        saturday = '2026-10-10T15:59:59+00:00'
        sunday = '2026-10-10T16:00:00+00:00'
        monday = '2026-10-11T16:00:00+00:00'
        rows = [paper(saturday), paper(sunday, sunday), paper(monday)]
        self.assertEqual(library.statistics(rows, datetime.fromisoformat('2026-10-11T00:00:00+08:00')), {'today': 1, 'week': 1})
        self.assertEqual(library.statistics(rows, datetime.fromisoformat('2026-10-12T00:00:00+08:00')), {'today': 1, 'week': 2})

    def test_delete_removes_counts_even_with_retained_history_and_reimport_resets(self):
        p = self.finish(self.paper())
        at = datetime.fromisoformat('2026-10-13T15:00:00+08:00')
        self.assertEqual(library.statistics(store.all_objects('paper'), at)['today'], 1)
        service.delete_paper(p['id'], True)
        self.assertEqual(library.statistics(store.all_objects('paper'), at), {'today': 0, 'week': 0})
        self.assertEqual(store.get('reading_history', p['id'])['read_status'], '已速览')
        p = documents.ingest(test_core.pdf(), 'fixture.pdf')
        self.assertEqual(p['read_status'], '未标记')
        self.assertEqual(p['reading_completions'], [])

    def test_migrate_manual_states_without_inventing_counts(self):
        p = {'id': 'legacy', 'read_status': '收藏', 'report': {'mode': 'overview'}}
        store.save('paper', p)
        library.migrate()
        p = store.get('paper', 'legacy')
        self.assertTrue(p['starred'])
        self.assertEqual(p['read_status'], '待阅读')
        self.assertEqual(p['reading_completions'], [])
        library.migrate()
        self.assertEqual(p, store.get('paper', 'legacy'))

    def test_successful_regeneration_resets_but_failure_preserves_completion(self):
        p = self.finish(self.paper())
        p['paper_type'] = 'research'; store.save('paper', p)
        with patch('paperpilot.reading.build', side_effect=ValueError('fixture failure')):
            job = self.wait_job(service.analyze(p['id'], 'detailed'))
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(store.get('paper', p['id'])['read_status'], '已速览')
        with patch('paperpilot.reading.build', return_value=({'figure_captions': []}, [])):
            job = self.wait_job(service.analyze(p['id'], 'detailed'))
        self.assertEqual(job['status'], 'completed', job.get('error'))
        saved = store.get('paper', p['id'])
        self.assertEqual(saved['read_status'], '待阅读')
        self.assertEqual(saved['reading_completions'], p['reading_completions'])

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_library_grouping_and_publication_date_sort(self):
        subprocess.run(['node', '-e', r'''
const assert=require('node:assert/strict'),v=require('./web/library-view.js');
assert.equal(v.title({title:'OpenVLA: A Model',publication_month:'2024-06'}),'2406 · OpenVLA: A Model');
assert.equal(v.title({title:'OpenVLA',publication_month:'2024-06',report:{title:'2406 · Existing report title'}}),'2406 · Existing report title');
assert.equal(v.title({title:'Unknown month'}),'Unknown month');
const a={id:'a',read_status:'未标记',added_at:'2026-10-13'},b={id:'b',read_status:'待阅读',added_at:'2026-10-12',report:{generated_at:'2026-10-14'}},c={id:'c',read_status:'已速览',added_at:'2026-10-13',report:{generated_at:'2026-10-12'}},d={id:'d',read_status:'已精读',added_at:'2026-10-12',report:{generated_at:'2026-10-13'}};
b.publication_month='2020-10';c.publication_month='2021-06';d.publication_month='2022-11';
const papers=[a,b,c,d];
assert.deepEqual(v.rows(papers,'reading').map(p=>p.id),['a','b']);
assert.deepEqual(v.rows(papers,'read').map(p=>p.id),['d','c']);
b.starred=true;c.starred=true;
assert.deepEqual(v.rows(papers,'starred').map(p=>p.id),['c','b']);
assert.deepEqual(v.rows([b,a,c,d],'reading').map(p=>p.id),['a']);
c.report=null;d.report=null;d.starred=true;
assert.deepEqual(v.rows(papers,'starred').map(p=>p.id),['d','c','b']);
d.starred=false;
assert.deepEqual(v.counts(papers),{reading:1,read:1,liked:0,starred:2});
c.starred=false;assert.equal(v.group(c),'read');b.starred=false;assert.equal(v.group(b),'reading');
b.liked=true;c.liked=true;assert.deepEqual(v.rows(papers,'liked').map(p=>p.id),['c','b']);assert.deepEqual(v.counts(papers),{reading:1,read:1,liked:2,starred:0});b.liked=false;assert.equal(v.group(b),'reading');c.liked=false;assert.equal(v.group(c),'read');
'''], cwd=store.ROOT, check=True, capture_output=True)
