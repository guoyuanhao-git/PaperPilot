import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from pathlib import Path

import test_core
import test_knowledge
from paperpilot import knowledge, knowledge_schedule as schedule, store, user_profile, service


class KnowledgeSchedule(unittest.TestCase):
    setUp = test_knowledge.Knowledge.setUp
    tearDown = test_core.Core.tearDown
    paper = test_knowledge.Knowledge.paper
    model = test_knowledge.Knowledge.model
    wait_job = test_core.Core.wait_job

    def enable(self):
        return schedule.configure({'enabled': True, 'weekday': 6, 'time': '10:00'})

    def moment(self, day=18, hour=10):
        return datetime(2026, 10, day, hour, tzinfo=schedule.TZ)

    def generate(self):
        for line in knowledge.mainline_options():
            knowledge.build(lambda _: None, mainline=line['key'])
        if not knowledge.mainline_options():
            knowledge.build(lambda _: None, scope='starred')

    def test_deadline_boundaries_and_timezone(self):
        config = schedule.settings()
        self.assertEqual(schedule.slot(config, self.moment(hour=9)), self.moment(day=11))
        self.assertEqual(schedule.slot(config, self.moment()), self.moment())
        self.assertEqual(schedule.slot(config, self.moment(day=19)), self.moment())
        self.assertEqual(schedule.slot(config, self.moment().astimezone()), self.moment())
        self.assertFalse(config['enabled'])
        for value in ({'enabled': 1, 'weekday': 6, 'time': '10:00'},
                      {'enabled': True, 'weekday': 7, 'time': '10:00'},
                      {'enabled': True, 'weekday': 6, 'time': '24:00'}):
            with self.assertRaises(ValueError): schedule.configure(value)

    def test_no_change_and_unread_import_do_not_call_model(self):
        self.enable()
        p = self.paper();p['read_status'] = '未标记';store.save('paper', p)
        with patch('paperpilot.providers.generate') as call:
            self.assertIsNone(schedule.tick(self.moment()))
            self.assertIsNone(schedule.tick(self.moment(day=19)))
            call.assert_not_called()
        self.assertEqual(schedule.status(self.moment(day=19))['state'], 'synced')

    def test_core_then_lines_and_next_week_batches_changes(self):
        self.paper(1, True);self.paper(2)
        user_profile.save({'mainlines': [{'title': 'A'}, {'title': 'B'}]})
        self.enable()
        phases = []
        original = knowledge.build_graph
        def record(progress, scope, **kwargs):
            phases.append((scope, kwargs['configuration']['_knowledge_mainline']))
            return original(progress, scope, **kwargs)
        with patch('paperpilot.providers.generate', side_effect=self.model), patch.object(knowledge, 'build_graph', side_effect=record):
            job = schedule.tick(self.moment(day=19))  # Missed Sunday, catches up Monday.
            self.assertEqual(self.wait_job(job)['status'], 'completed')
            self.assertEqual([p[0] for p in phases], ['starred', 'all', 'all'])
            self.assertFalse(schedule.plan()['core']);self.assertFalse(schedule.plan()['mainlines'])
            self.paper(3)
            self.assertIsNone(schedule.tick(self.moment(day=20)))
            self.assertFalse(schedule.plan()['core']);self.assertEqual(len(schedule.plan()['mainlines']), 2)
            phases.clear()
            job = schedule.tick(self.moment() + timedelta(weeks=4))
            self.assertEqual(self.wait_job(job)['status'], 'completed')
            self.assertEqual([p[0] for p in phases], ['all', 'all'])
            self.assertIsNone(schedule.tick(self.moment() + timedelta(weeks=4)))

    def test_profile_notes_membership_and_provider_change(self):
        self.paper(1, True);self.paper(2)
        user_profile.save({'research_directions':'Learning', 'mainlines':[{'title':'A'},{'title':'B'}]})
        with patch('paperpilot.providers.generate', side_effect=self.model): self.generate()
        self.assertFalse(schedule.plan()['mainlines'])
        # Switching a provider is not a change to the research inputs.
        config = store.settings();config['provider'] = 'deepseek'
        with patch('paperpilot.store.settings', return_value=config):
            self.assertFalse(schedule.plan()['core']);self.assertFalse(schedule.plan()['mainlines'])
        profile = user_profile.get();profile['mainlines'][0]['detail']='New focus';profile.pop('mainline_detail');user_profile.save(profile)
        self.assertFalse(schedule.plan()['core']);self.assertEqual(len(schedule.plan()['mainlines']),1)
        p=store.get('paper',f'{2:020x}');p['notes']='Personal observation';store.save('paper',p)
        self.assertFalse(schedule.plan()['core']);self.assertEqual(len(schedule.plan()['mainlines']),2)
        p=store.get('paper',f'{1:020x}');p.update(starred=False,liked=True);store.save('paper',p)
        self.assertTrue(schedule.plan()['core'])
        with patch('paperpilot.providers.generate', side_effect=self.model): self.generate()
        p.update(liked=False,read_status='未标记');store.save('paper',p)
        self.assertTrue(schedule.plan()['core'])
        with patch('paperpilot.providers.generate', side_effect=self.model): self.generate()
        store.remove('paper', f'{2:020x}');knowledge.forget(f'{2:020x}')
        self.assertTrue(schedule.plan()['mainlines'])

    def test_partial_failure_keeps_core_and_retries_only_pending(self):
        self.paper(1, True);self.paper(2)
        user_profile.save({'mainlines':[{'title':'A'}, {'title':'B'}]});self.enable()
        original = knowledge.build_graph
        failed_key = knowledge.mainline_options()[0]['key']
        def fail(progress, scope, **kwargs):
            if kwargs['configuration']['_knowledge_mainline']==failed_key:raise ValueError('模拟网络失败')
            return original(progress,scope,**kwargs)
        with patch('paperpilot.providers.generate', side_effect=self.model), patch.object(knowledge,'build_graph',side_effect=fail):
            job=schedule.tick(self.moment())
            self.assertEqual(self.wait_job(job)['status'],'failed')
        self.assertFalse(schedule.plan()['core']);self.assertEqual(len(schedule.plan()['mainlines']),1)
        self.assertEqual(schedule.status(self.moment())['state'],'failed')
        self.assertIsNone(schedule.tick(self.moment(day=19)))
        with patch('paperpilot.providers.generate',side_effect=self.model), patch.object(knowledge,'build_graph',wraps=original) as build:
            self.assertEqual(self.wait_job(schedule.tick(self.moment(day=19),retry=True))['status'],'completed')
            self.assertEqual(build.call_count,1)
        self.assertEqual(schedule.status(self.moment(day=19))['state'],'synced')

    def test_busy_and_interrupted_jobs_and_manual_exclusion(self):
        self.paper(1,True);self.enable()
        store.save('job',{'id':'manual','kind':'knowledge','status':'running'})
        self.assertIsNone(schedule.tick(self.moment()))
        self.assertNotIn('checked_slot',schedule.settings())
        store.remove('job','manual')
        store.save('job',{'id':'auto','kind':'knowledge-auto','status':'running'})
        with self.assertRaisesRegex(ValueError,'每周'):knowledge.start(scope='starred')
        config=schedule.settings();config.update(job_id='auto',checked_slot=self.moment().isoformat());store.save('knowledge_schedule',config)
        store.init()  # Simulated restart reconciles an interrupted job as failed.
        self.assertEqual(schedule.status(self.moment())['state'],'failed')
        self.assertIsNone(schedule.tick(self.moment(day=19)))

    def test_disabled_and_accounts_are_isolated(self):
        self.paper(1,True);self.enable()
        for name in ('a','b'):
            with store.scope({'directory':Path(self.tmp.name)/name}):store.init()
        with store.scope({'directory':Path(self.tmp.name)/'a'}):
            self.enable();self.paper(1,True)
        with store.scope({'directory':Path(self.tmp.name)/'b'}):
            self.assertFalse(schedule.settings()['enabled']);self.assertIsNone(schedule.tick(self.moment()))
            self.assertEqual(schedule.plan(),{'core':False,'mainlines':[]})
        with store.scope({'directory':Path(self.tmp.name)/'a'}):
            schedule.configure({'enabled':False,'weekday':6,'time':'10:00'})
            with patch.object(knowledge,'build_graph') as build:
                self.assertEqual(schedule.work(lambda _:None),{'paused':True})
                build.assert_not_called()

    def test_source_change_during_build_keeps_original_graph(self):
        self.paper(1,True);self.enable()
        with patch('paperpilot.providers.generate',side_effect=self.model):self.generate()
        old=store.get('knowledge','core:starred')
        p=store.get('paper',f'{1:020x}');p['notes']='first edit';store.save('paper',p)
        def mutate(*args,**kwargs):
            result=self.model(*args,**kwargs)
            p['notes']='second edit while generating';store.save('paper',p)
            return result
        with patch('paperpilot.providers.generate',side_effect=mutate):
            self.assertEqual(self.wait_job(schedule.tick(self.moment()))['status'],'failed')
        self.assertEqual(store.get('knowledge','core:starred'),old)
        self.assertTrue(schedule.plan()['core'])
