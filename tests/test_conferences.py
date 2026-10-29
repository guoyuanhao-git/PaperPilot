import copy
import tempfile
import unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch
from paperpilot import conferences as c, conference_update as update, conference_sources as sources, store, workspace


def catalog():
    return {'schemaVersion':2,'revision':9,'updates':[], 'series':[{'id':'test','name':'Test','rank':'A','group':'机器人','topics':'学习','editions':[
        {'year':2027,'announcement':'cfp','entryKey':'abstract','paperAudience':'registered',
         'abstract':'2026-11-01T23:59:00-12:00','paper':'2026-11-08T23:59:00-12:00',
         'abstractDay':None,'paperDay':None,'verification':'verified','source':'https://example.org/cfp',
         'evidence':'official dates','checked':'2026-10-28','zone':'Etc/GMT+12','zoneLabel':'AoE'}]}]}


def extraction():
    text = ('Test 2027 Call for Papers. Mandatory abstract registration November 1, 2026. '
            'Full paper November 8, 2026, only registered authors. All deadlines 23:59 Anywhere on Earth.')
    pages = [{'id':'1','url':'https://example.org/cfp','text':text}]
    row = copy.deepcopy(catalog()['series'][0]['editions'][0])
    for k in ('verification','source','checked'): row.pop(k)
    row['note']=''
    row['proofs']=[{'field':f,'source':'1','quote':q} for f,q in (
        ('edition','Test 2027 Call for Papers.'),('rules','Mandatory abstract registration November 1, 2026.'),
        ('abstract','Mandatory abstract registration November 1, 2026.'),('paper','Full paper November 8, 2026, only registered authors.'),
        ('timezone','All deadlines 23:59 Anywhere on Earth.'))]
    return {'editions':[row],'summary':'核查成功'}, pages


class Conferences(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.scope=store.scope({'directory':Path(self.temp.name)/'first'})
        self.scope.__enter__();store.init()

    def tearDown(self):
        self.scope.__exit__(None,None,None);self.temp.cleanup()

    def test_initial_catalog_has_13_series_but_no_seed_deadlines(self):
        with patch.object(sources,'fetch_page',side_effect=AssertionError('GET must not fetch')):
            result=c.current(force=True)
        self.assertEqual(len(result['catalog']['series']),13)
        self.assertIn('eccv',{s['id'] for s in result['catalog']['series']})
        for series in result['catalog']['series']:
            for edition in series['editions']:
                self.assertIsNone(edition['abstract']);self.assertIsNone(edition['paper'])
                self.assertIsNone(edition['checked'])
        self.assertNotIn('home',result)
        self.assertFalse(result['schedule']['enabled'])

    def test_import_preserves_full_data_without_remote_refresh(self):
        value=catalog();value['updates']=[{'kind':'check','note':'keep history'}]
        self.assertEqual(c.import_catalog(value)['catalog'],value)
        self.assertEqual(c.current(force=True)['catalog'],value)

    def test_rejects_older_versions_missing_history_unsafe_sources(self):
        value=catalog();c.import_catalog(value)
        for mutation in ('older','missing','unsafe','undated'):
            changed=copy.deepcopy(value);changed['revision']+=1
            if mutation=='older':changed['revision']=1
            if mutation=='missing':changed['series'][0]['editions'][0]['year']+=1
            if mutation=='unsafe':changed['series'][0]['editions'][0]['source']='javascript:alert(1)'
            if mutation=='undated':changed['series'][0]['editions'][0]['abstract']=None
            with self.assertRaises(ValueError):c.import_catalog(changed)
            self.assertEqual(c.saved()['catalog'],value)

    def test_focus_schedule_navigation_account_isolation(self):
        c.import_catalog(catalog());c.focus('test');c.configure(True)
        settings=store.settings();workspace.save({'hidden_modules':['knowledge','conferences']})
        self.assertEqual(store.settings(),settings)
        with store.scope({'directory':Path(self.temp.name)/'second'}):
            store.init()
            self.assertIsNone(c.current()['focus']);self.assertFalse(c.configuration()['enabled'])
            self.assertEqual(workspace.current()['hidden_modules'],[])
        self.assertEqual(c.current()['focus'],'test')
        with self.assertRaises(ValueError):c.focus('unknown')
        self.assertIsNone(c.focus(None)['focus'])

    def test_weekly_slot_and_catchup_only_once_and_not_while_busy(self):
        before=datetime.fromisoformat('2026-11-01T09:59:00+08:00')
        after=datetime.fromisoformat('2026-11-01T10:01:00+08:00')
        self.assertEqual(c.weekly_slot(before).date().isoformat(),'2026-10-25')
        self.assertEqual(c.weekly_slot(after).date().isoformat(),'2026-11-01')
        c.configure(True)
        store.save('job',{'id':'reading','status':'running'})
        with patch('paperpilot.service.job') as job:
            c.tick(after);job.assert_not_called()
        store.save('job',{'id':'reading','status':'completed'})
        with patch('paperpilot.service.job',return_value={'id':'check','kind':'conferences','status':'queued'}) as job:
            c.tick(after);c.tick(after)
            job.assert_called_once()

    def test_official_quotes_required_and_invited_stage_not_new_entry(self):
        value,pages=extraction();series=catalog()['series'][0]
        checked=update.validated_editions(value,pages,series,'2026-10-28')
        self.assertEqual(checked[0]['checked'],'2026-10-28')
        for key in ('quote','date','year','date_year','invited','clock','offset','conference'):
            bad=copy.deepcopy(value);row=bad['editions'][0]
            if key=='quote':row['proofs'][0]['quote']='Test 2099 Call for Papers.'
            if key=='date':row['abstract']='2026-11-02T23:59:00-12:00'
            if key=='year':row['year']=2028
            if key=='date_year':row['abstract']='2025-11-01T23:59:00-12:00'
            if key=='invited':row.update(paperAudience='invited',entryKey='paper')
            if key=='clock':row['abstract']='2026-11-01T13:59:00-12:00'
            if key=='offset':row['abstract']='2026-11-01T23:59:00+00:00'
            if key=='conference':row['proofs'][0]['quote']='2027 Call for Papers.'
            with self.assertRaises(ValueError,msg=key):update.validated_editions(bad,pages,series,'2026-10-28')

    def test_unsubstantiated_time_is_reduced_to_verified_date(self):
        value,pages=extraction()
        value['editions'][0]['proofs']=[p for p in value['editions'][0]['proofs'] if p['field']!='timezone']
        row=update.validated_editions(value,pages,catalog()['series'][0],'2026-10-28')[0]
        self.assertIsNone(row['abstract']);self.assertEqual(row['abstractDay'],'2026-11-01')

    def test_repeated_identical_pages_reuse_extraction(self):
        value,pages=extraction();registry={'id':'test'};series=catalog()['series'][0]
        with patch.object(sources,'collect',return_value=(pages,[])),patch.object(update,'extract',return_value=(value,{})) as model:
            update.check_one(registry,series,{},'2026-10-28');update.check_one(registry,series,{},'2026-11-01')
            model.assert_called_once()

    def test_failure_and_missing_dates_preserve_prior_date_and_checked(self):
        original=catalog();c.import_catalog(original)
        with patch.object(c,'REGISTRY',[{'id':'test','name':'Test'}]),patch.object(update,'check_one',side_effect=ValueError('offline')):
            with self.assertRaises(ValueError):update.run(lambda _:None)
        self.assertEqual(c.saved()['catalog']['series'],original['series'])
        self.assertEqual(c.saved()['catalog']['updates'][0]['checks'][0]['outcome'],'failed')
        row=copy.deepcopy(original['series'][0]['editions'][0]);row.update(abstract=None,entryKey=None,checked='2026-11-01')
        with patch.object(c,'REGISTRY',[{'id':'test','name':'Test'}]),patch.object(update,'check_one',return_value=([row],'未找到摘要截止',[])):
            update.run(lambda _:None)
        self.assertEqual(c.saved()['catalog']['series'],original['series'])

    def test_new_meeting_preserves_old_cfp(self):
        original=catalog();c.import_catalog(original)
        row=copy.deepcopy(original['series'][0]['editions'][0]);row.update(year=2028,announcement='meeting',abstract=None,paper=None,entryKey=None,paperAudience='all',verification='notlisted')
        with patch.object(c,'REGISTRY',[{'id':'test','name':'Test'}]),patch.object(update,'check_one',return_value=([row],'仅公布会期',[])):
            update.run(lambda _:None)
        editions=c.saved()['catalog']['series'][0]['editions']
        self.assertEqual(editions[0],original['series'][0]['editions'][0]);self.assertEqual(len(editions),2)

    def test_official_links_only_and_page_budget(self):
        registry={'sources':['https://example.org/'],'domains':['example.org']}
        series={'editions':[]}
        def page(url,domains):
            return url,'Test 2027 Call for Papers', [('https://evil.test/dates','Dates'),('/2028/dates','Dates 2028'),('/2027/dates','Dates 2027')]
        with patch.object(sources,'fetch_page',side_effect=page) as fetch:
            pages,failures=sources.collect(registry,series)
        self.assertEqual(len(pages),3)
        self.assertTrue(all(call.args[0].startswith('https://example.org/') for call in fetch.call_args_list))
        self.assertFalse(sources.allowed('https://example.org.evil.test/',registry['domains']))
        self.assertFalse(sources.allowed('https://example.org:123/',registry['domains']))
