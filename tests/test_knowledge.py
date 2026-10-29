import json
import unittest
from unittest.mock import patch
import test_core
from paperpilot import user_profile, providers, credentials, store, knowledge, paper_identity, historical, documents, library, service


class Knowledge(unittest.TestCase):
    def setUp(self):
        test_core.Core.setUp(self)
        patcher = patch('paperpilot.knowledge_sources.collect', return_value={'status': 'unavailable', 'paragraphs': []})
        patcher.start()
        self.addCleanup(patcher.stop)
    tearDown = test_core.Core.tearDown
    wait_job = test_core.Core.wait_job

    def paper(self, i=1, starred=False):
        p = {'id': f'{i:020x}', 'title': f'Method {i}: Representation Learning', 'publication_month': '2021-06', 'short_title': f'M{i}',
             'abstract': f'Method {i} learns reusable representations through low rank adaptation.', 'notes': '', 'starred': starred,
             'read_status': '已速览', 'reading_state_version': 1, 'reading_completions': [], 'reading_session': 0, 'added_at': service.now(),
             'metadata_only': True, 'report': None, 'figures': [], 'source_url': 'https://arxiv.org/abs/2106.09685', 'page_count': 0, 'messages': [], 'feedback': ''}
        return store.save('paper', p)

    def model(self, config, system, messages, **kwargs):
        self.assertEqual(config['codex_reasoning_effort'], 'high' if config.get('knowledge_deep_thinking', False) else config['reasoning']['knowledge'])
        self.assertEqual(config['deepseek']['thinking'], 'high' if config.get('knowledge_deep_thinking', False) else 'low')
        rows = json.loads(messages[0]['content'].split('\n', 1)[1])
        if 'choices' in kwargs['schema']['properties']:
            value = {'choices': [{'id': r['id'], 'keep': [e['id'] for e in r['links']], 'role': 'specialist', 'reason': '独立的方法关系。'} for r in rows]}
        elif 'papers' in kwargs['schema']['properties']:
            value = {'papers': [{'id': r['id'], 'tags': ['representation learning', 'low rank adaptation'], 'insight': '通过低秩结构学习可迁移表示。', 'relevance': 2} for r in rows]}
        else:
            value = {'pairs': [{'id': r['id'], 'related': True, 'relation': '低秩表示', 'reason': '两者均讨论低秩适应，可回读机制差异。', 'research_use': '可对比动作模型中低秩参数的适应效率；迁移需要验证。', 'priority': 2, 'evidence_a': next(iter(r['A']['evidence'])), 'evidence_b': next(iter(r['B']['evidence']))} for r in rows]}
        return {'value': value}

    def test_likes_belong_to_domain_even_unread_and_mainline_reuses_their_edges(self):
        self.paper(1, True)
        for i in (2, 3):
            p = self.paper(i)
            p.update(liked=True, read_status='未标记')
            store.save('paper', p)
        self.paper(4)
        with patch('paperpilot.providers.generate', side_effect=self.model):
            knowledge.build(lambda _: None)
        core = knowledge.current('starred')
        self.assertEqual(len(core['nodes']), 3)
        self.assertEqual(core['liked_count'], 2)
        self.assertEqual(len(core['edges']), 3)  # Including like-like evidence.
        main = knowledge.current()
        self.assertEqual(len(main['nodes']), 4)
        self.assertTrue(all(e in main['edges'] for e in core['edges']))
        p = store.get('paper', f'{2:020x}')
        library.change(p['id'], 'preference', preference='none')
        self.assertTrue(knowledge.current('starred')['stale'])
        self.assertNotIn(p['id'], [n['id'] for n in knowledge.current()['nodes']])

    def test_profile_layers_and_display_have_separate_invalidation(self):
        self.paper(1, True); self.paper(2, True); self.paper(3)
        user_profile.save({'research_directions': '通用表示学习', 'mainline': '低秩动作模型', 'goals': '验证数据效率', 'display_name': 'private-name'})
        systems = []
        def model(*args, **kwargs):
            systems.append((args[0]['_knowledge_mainline'], args[1]))
            return self.model(*args, **kwargs)
        with patch('paperpilot.providers.generate', side_effect=model) as call:
            knowledge.build(lambda _: None)
            for layer, system in systems:
                self.assertIn('通用表示学习', system)
                self.assertNotIn('private-name', system)
                if layer == knowledge.CORE_KEY:
                    self.assertNotIn('低秩动作模型', system)
                    self.assertNotIn('验证数据效率', system)
                else:
                    self.assertIn('低秩动作模型', system)
                    self.assertIn('验证数据效率', system)
            core = store.get('knowledge', 'core:starred')
            first = call.call_count
            user_profile.save_display({'display_name': 'changed', 'gender': '女'})
            self.assertFalse(knowledge.current()['stale'])
            knowledge.build(lambda _: None)
            self.assertEqual(call.call_count, first)
            user_profile.save({**user_profile.get(), 'mainline': '柔体接触仿真'})
            self.assertTrue(knowledge.current()['stale'])
            self.assertFalse(knowledge.current()['starred_graph']['stale'])
            def unrelated(*args, **kwargs):
                out = model(*args, **kwargs)
                for row in out['value'].get('pairs', []): row['related'] = False
                return out
            call.side_effect = unrelated
            knowledge.build(lambda _: None)
            self.assertEqual(knowledge.current()['edges'], core['edges'])
            self.assertEqual(len(knowledge.current()['nodes']), 3)
            self.assertEqual(store.get('knowledge', 'core:starred')['edges'], core['edges'])
            user_profile.save({**user_profile.get(), 'research_directions': '计算仿真'})
            self.assertTrue(knowledge.current()['starred_graph']['stale'])

    def test_profile_edit_during_generation_keeps_saved_graph(self):
        self.paper(1, True)
        with patch('paperpilot.providers.generate', side_effect=self.model):
            knowledge.build(lambda _: None)
        prior = store.get('knowledge', 'core:starred')
        def mutate(*args, **kwargs):
            result = self.model(*args, **kwargs)
            user_profile.save({'research_directions': 'edited during generation'})
            return result
        with patch('paperpilot.providers.generate', side_effect=mutate), self.assertRaisesRegex(ValueError, '研究档案有变化'):
            knowledge.build(lambda _: None, rebuild=True, scope='starred')
        self.assertEqual(store.get('knowledge', 'core:starred'), prior)

    def test_online_excerpt_provenance_and_relevance_are_retained(self):
        self.paper(1, True); self.paper(2, True)
        material = {'status': 'web', 'url': 'https://arxiv.org/html/2106.09685', 'paragraphs': ['The architecture uses feature modulation to condition the policy on a task embedding, enabling controlled adaptation across tasks.']}
        def model(*args, **kwargs):
            result = self.model(*args, **kwargs)
            for row in result['value'].get('pairs', []):
                row.update(evidence_a='opening:1', evidence_b='opening:1', priority=3)
            return result
        with patch('paperpilot.knowledge_sources.collect', return_value=material), patch('paperpilot.providers.generate', side_effect=model):
            knowledge.build(lambda _: None)
        graph = knowledge.current()
        edge = graph['edges'][0]
        self.assertEqual(edge['quote_a'], material['paragraphs'][0])
        self.assertEqual(edge['source_a'], {'kind': 'web', 'url': material['url'], 'section': 'opening'})
        self.assertEqual(edge['priority'], 3)
        self.assertEqual(graph['evidence_coverage']['web'], 2)
        self.assertTrue(edge['research_use'])

    def test_reading_report_is_secondary_evidence_and_invalidates_cache(self):
        paper = self.paper(1, True)
        paper['report'] = {'sections': [{'key': 'method', 'blocks': [{'paragraphs': ['该方法通过条件特征调制控制策略表示，适合进一步比较动作模型的条件注入位置。']}]}]}
        store.save('paper', paper)
        seen = []
        def model(*args, **kwargs):
            seen.append(args[2][0]['content'])
            self.assertIn('二级解读', args[1])
            return self.model(*args, **kwargs)
        with patch('paperpilot.providers.generate', side_effect=model):
            knowledge.build(lambda _: None)
        self.assertTrue(any('report:1' in text for text in seen))
        self.assertEqual(knowledge.current()['evidence_coverage']['report'], 1)
        self.assertFalse(knowledge.current()['stale'])
        paper['report']['sections'][0]['blocks'][0]['paragraphs'] = ['新的阅读报告补充了原文没有直接证明的推断，应保留为待验证的阅读线索。']
        store.save('paper', paper)
        self.assertTrue(knowledge.current()['stale'])

    def test_mainline_graphs_context_caches_and_results_are_independent(self):
        a, b = self.paper(1, True), self.paper(2, True)
        self.paper(3)
        lines = [{'title': '动作模型主线', 'detail': '数据效率'}, {'title': '柔体仿真主线', 'detail': '接触建模'}]
        user_profile.save({'mainlines': lines})
        first, second = [line['key'] for line in knowledge.mainline_options()]
        seen = []
        def focused(*args, **kwargs):
            system = args[1]
            seen.append(system)
            result = self.model(*args, **kwargs)
            for row in result['value'].get('pairs', []):
                row['related'] = args[0]['_knowledge_mainline'] == knowledge.CORE_KEY or '动作模型主线' in system
            return result
        with patch('paperpilot.providers.generate', side_effect=focused) as call:
            knowledge.build(lambda _: None, mainline=first)
            first_saved = store.get('knowledge', knowledge.namespaced('current', first))
            self.assertEqual(len(first_saved['edges']), 3)
            first_calls = call.call_count
            self.assertTrue(all('柔体仿真主线' not in s for s in seen))
            seen.clear()
            knowledge.build(lambda _: None, mainline=second)
            self.assertTrue(all('柔体仿真主线' in s and '动作模型主线' not in s for s in seen))
            self.assertEqual(call.call_count, first_calls+2)
            self.assertEqual(knowledge.current(mainline=second)['edges'], knowledge.current('starred')['edges'])
            self.assertEqual(store.get('knowledge', knowledge.namespaced('current', first)), first_saved)
            knowledge.build(lambda _: None, mainline=first)
            self.assertEqual(call.call_count, first_calls+2)
            self.assertFalse(knowledge.current(mainline=first)['stale'])
            self.assertFalse(knowledge.current(mainline=second)['stale'])
        # Reordering does not swap saved graphs; editing one detail affects only that graph.
        user_profile.save({'mainlines': [lines[1], {**lines[0], 'detail': '新的目标'}]})
        self.assertEqual(knowledge.mainline_options()[0]['key'], second)
        self.assertTrue(knowledge.current(mainline=first)['stale'])
        self.assertFalse(knowledge.current(mainline=second)['stale'])
        service.delete_paper(a['id'], False)
        self.assertTrue(all(a['id'] not in [n['id'] for n in graph['nodes']] and all(a['id'] not in (e['source'], e['target']) for e in graph['edges']) for graph in store.all_objects('knowledge')))
        self.assertTrue(all(n.get('paper_id') != a['id'] for n in store.all_objects('knowledge_node')))
        self.assertTrue(all(a['id'] not in e['papers'] for e in store.all_objects('knowledge_edge')))

    def test_mainline_selection_validation_and_running_job_metadata(self):
        user_profile.save({'mainlines': [{'title': 'A'}, {'title': 'B'}]})
        first, second = [line['key'] for line in knowledge.mainline_options()]
        for bad in (None, 1, [], 'line-does-not-exist'):
            with self.assertRaises(ValueError): knowledge.start(mainline=bad)
        running = store.save('job', {'id': 'running', 'kind': 'knowledge', 'status': 'running', 'mainline_key': first})
        self.assertEqual(knowledge.start(mainline=first), running)
        with self.assertRaisesRegex(ValueError, '另一研究主线'):
            knowledge.start(mainline=second)
        store.remove('job', 'running')
        self.paper(1, True)
        with patch('paperpilot.providers.generate', side_effect=self.model):
            job = self.wait_job(knowledge.start(mainline=first))
        self.assertEqual(job['mainline_key'], first)
        self.assertEqual(job['result']['mainline_key'], first)
        self.assertEqual(job['status'], 'completed')
        user_profile.save({'mainlines': [{'title': 'B'}]})
        with self.assertRaisesRegex(ValueError, '变更或移除'):
            knowledge.current(mainline=first)
        self.assertEqual(knowledge.current(mainline=second)['nodes'], [])

    def test_http_mainline_selection_generation_and_invalid_selection(self):
        import threading
        import urllib.request
        import urllib.error
        from http.server import ThreadingHTTPServer
        from paperpilot.server import Handler, TOKEN
        user_profile.save({'mainlines': [{'title': '模型主线'}, {'title': '仿真主线'}]})
        first, second = [line['key'] for line in knowledge.mainline_options()]
        self.paper(1, True); self.paper(2, True)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        def request(path, body=None):
            data = json.dumps(body).encode() if body is not None else None
            req = urllib.request.Request(f'http://127.0.0.1:{server.server_port}'+path, data, {'X-PaperPilot-Token': TOKEN})
            with urllib.request.urlopen(req) as response: return json.load(response)
        try:
            graph = request('/api/knowledge?mainline='+first)
            self.assertEqual(graph['mainline_key'], first)
            self.assertEqual(graph['nodes'], [])
            with patch('paperpilot.providers.generate', side_effect=self.model):
                job = self.wait_job(request('/api/knowledge-update', {'mainline': first}))
            self.assertEqual(job['status'], 'completed')
            graph = request('/api/bootstrap?knowledge_mainline='+first)['knowledge']
            self.assertEqual(graph['mainline_key'], first)
            self.assertEqual(len(graph['nodes']), 2)
            self.assertEqual(request('/api/knowledge?mainline='+second)['nodes'], [])
            with self.assertRaises(urllib.error.HTTPError) as error:
                request('/api/knowledge-update', {'mainline': 'bad'})
            self.assertEqual(error.exception.code, 400)
        finally:
            server.shutdown(); server.server_close()

    def test_identity_validation_manual_precedence_and_collision(self):
        a = self.paper()
        b = self.paper(2)
        b['short_title'] = 'm1'
        with self.assertRaisesRegex(ValueError, '已存在'):
            paper_identity.validate(b, True)
        b.update(short_title='', short_title_source='manual')
        paper_identity.infer(b)
        self.assertEqual(b['short_title'], '')
        b.pop('short_title_source')
        paper_identity.infer(b)
        self.assertEqual(b['short_title'], 'Method 2')
        store.save('paper', {**a, 'short_title': ''})
        with self.assertRaisesRegex(ValueError, '短标题'):
            library.change(a['id'], 'star', starred=True)
        with self.assertRaises(ValueError):
            paper_identity.validate({**b, 'publication_month': ''}, True)

    def test_graph_incremental_scopes_notes_and_deletion(self):
        a, b, c = self.paper(1, True), self.paper(2, True), self.paper(3)
        with patch('paperpilot.providers.generate', side_effect=self.model) as call:
            knowledge.build(lambda _: None)
            self.assertEqual(call.call_count, 4)  # Favorites first, then remaining nodes/relationships.
            self.assertFalse(knowledge.current()['stale'])
            knowledge.build(lambda _: None)
            self.assertEqual(call.call_count, 4)
            a['notes'] = '我想比较低秩约束对策略学习的影响。'
            store.save('paper', a)
            self.assertTrue(knowledge.current()['stale'])
            knowledge.build(lambda _: None)
            self.assertEqual(call.call_count, 8)
        g = knowledge.current()
        self.assertEqual(len(g['nodes']), 3)
        self.assertEqual(sum(n['starred'] for n in g['nodes']), 2)
        self.assertEqual(len(g['edges']), 3)
        c.update(read_status='未标记')
        store.save('paper', c)
        self.assertEqual(len(knowledge.current()['nodes']), 2)
        self.assertEqual(len(knowledge.current()['edges']), 1)
        service.delete_paper(a['id'], False)
        self.assertEqual(len(knowledge.current()['nodes']), 1)
        self.assertFalse(any(a['id'] in x.get('papers', []) for x in store.all_objects('knowledge_edge')))

    def test_invalid_model_and_concurrent_mutation_preserve_old_graph(self):
        a, b = self.paper(), self.paper(2, True)
        with patch('paperpilot.providers.generate', side_effect=self.model):
            knowledge.build(lambda _: None)
        prior = store.get('knowledge', 'current')
        a['notes'] = 'changed'
        store.save('paper', a)
        def bad(*args, **kwargs):
            result = self.model(*args, **kwargs)
            if 'pairs' in result['value']:
                result['value']['pairs'][0]['evidence_a'] = 'abstract:999'
            return result
        with patch('paperpilot.providers.generate', side_effect=bad), self.assertRaisesRegex(ValueError, '片段编号'):
            knowledge.build(lambda _: None)
        self.assertEqual(store.get('knowledge', 'current'), prior)
        def mutate(*args, **kwargs):
            result = self.model(*args, **kwargs)
            store.save('paper', {**b, 'notes': 'edited while generating'})
            return result
        with patch('paperpilot.providers.generate', side_effect=mutate), self.assertRaisesRegex(ValueError, '变化'):
            knowledge.build(lambda _: None)
        self.assertEqual(store.get('knowledge', 'current'), prior)

    def test_favorites_complete_first_and_survive_second_stage_failure(self):
        a, b, c = self.paper(1, True), self.paper(2, True), self.paper(3)
        phases = []
        def staged(config, system, messages, **kwargs):
            rows = json.loads(messages[0]['content'].split('\n', 1)[1])
            if 'papers' in kwargs['schema']['properties']:
                phases.append([r['id'] for r in rows])
                if any(r['id'] == c['id'] for r in rows):
                    saved = store.get('knowledge', 'core:starred')
                    self.assertEqual(len(saved['edges']), 1)
                    raise ValueError('second stage unavailable')
            return self.model(config, system, messages, **kwargs)
        with patch('paperpilot.providers.generate', side_effect=staged), self.assertRaisesRegex(ValueError, 'second stage'):
            knowledge.build(lambda _: None)
        self.assertEqual(set(phases[0]), {a['id'], b['id']})
        favorite = knowledge.current()['starred_graph']
        self.assertFalse(favorite['stale'])
        self.assertEqual(len(favorite['nodes']), 2)
        # All papers are historical metadata-only imports, with no personal notes.
        edge = favorite['edges'][0]
        self.assertIn(edge['quote_a'], (a['abstract'], b['abstract']))
        self.assertIn(edge['quote_b'], (a['abstract'], b['abstract']))
        with patch('paperpilot.providers.generate', side_effect=self.model):
            knowledge.build(lambda _: None)
        self.assertEqual(len(knowledge.current()['edges']), 3)
        service.delete_paper(a['id'], False)
        self.assertEqual(len(knowledge.current()['starred_graph']['nodes']), 1)
        self.assertEqual(store.get('knowledge', 'core:starred')['edges'], [])

    def test_evidence_ids_preserve_original_typography_and_exclude_empty_notes(self):
        content = {'abstract': 'We use π₀. This is a 16×16 model.\n\nAnother paragraph.', 'notes': ''}
        refs = knowledge.evidence(content)
        self.assertEqual(refs['abstract:1'], 'We use π₀.')
        self.assertEqual(refs['abstract:2'], 'This is a 16×16 model.')
        self.assertFalse(any(key.startswith('notes:') for key in refs))
        self.assertTrue(all(text in content['abstract'] for text in refs.values()))

    def test_negative_relations_accept_null_or_omitted_inapplicable_fields(self):
        self.paper(1, True); self.paper(2, True)
        def negative(*args, **kwargs):
            result = self.model(*args, **kwargs)
            for row in result['value'].get('pairs', []):
                row.update(related=False, relation=None, reason=None, evidence_a=None)
                row.pop('evidence_b')
            return result
        with patch('paperpilot.providers.generate', side_effect=negative) as call:
            knowledge.build(lambda _: None)
            self.assertEqual(call.call_count, 3)
        self.assertEqual(knowledge.current()['edges'], [])
        self.assertEqual(len(knowledge.current()['nodes']), 2)

    def test_only_invalid_rows_repaired_and_successful_rows_cached(self):
        self.paper(1, True); self.paper(2, True); self.paper(3, True)
        calls = []
        def imperfect(*args, **kwargs):
            result = self.model(*args, **kwargs)
            if 'pairs' in result['value']:
                rows = result['value']['pairs']
                calls.append([r['id'] for r in rows])
                if len(calls) == 1:
                    rows[0]['evidence_a'] = 'nonexistent'
                    rows[1]['related'] = 'false'
            return result
        with patch('paperpilot.providers.generate', side_effect=imperfect):
            knowledge.build(lambda _: None)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1], calls[0][:2])
        self.assertEqual(len(knowledge.current()['edges']), 3)

    def test_missing_rows_and_invalid_json_get_one_repair(self):
        self.paper(1, True); self.paper(2, True)
        calls = 0
        def imperfect(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise providers.StructuredOutputError('{broken', {}, 'invalid json')
            result = self.model(*args, **kwargs)
            if calls == 3:
                result['value'] = {'pairs': []}
            return result
        with patch('paperpilot.providers.generate', side_effect=imperfect):
            knowledge.build(lambda _: None)
        self.assertEqual(calls, 5)
        self.assertEqual(len(knowledge.current()['edges']), 1)

    def test_overlay_rebuild_cannot_rewrite_core_and_core_rebuild_is_explicit(self):
        self.paper(1, True); self.paper(2, True); self.paper(3)
        with patch('paperpilot.providers.generate', side_effect=self.model):
            knowledge.build(lambda _: None)
        core = store.get('knowledge', 'core:starred')
        def negative(*args, **kwargs):
            result = self.model(*args, **kwargs)
            for row in result['value'].get('pairs', []): row['related'] = False
            return result
        with patch('paperpilot.providers.generate', side_effect=negative) as call:
            knowledge.build(lambda _: None, rebuild=True)
            self.assertEqual(knowledge.current()['edges'], core['edges'])
            self.assertEqual(call.call_count, 2)  # Only overlay nodes and edges.
            self.assertEqual(store.get('knowledge', 'core:starred')['edges'], core['edges'])
            knowledge.build(lambda _: None, rebuild=True, scope='starred')
            self.assertEqual(knowledge.current('starred')['edges'], [])
            self.assertTrue(knowledge.current()['stale'])
            knowledge.build(lambda _: None)
            self.assertEqual(knowledge.current()['edges'], [])

    def test_incremental_keeps_prior_links_when_candidate_ranking_changes(self):
        self.paper(1, True); self.paper(2)
        with patch('paperpilot.providers.generate', side_effect=self.model):
            knowledge.build(lambda _: None)
        with patch('paperpilot.knowledge.graph_pairs', return_value=set()), patch('paperpilot.providers.generate', side_effect=self.model) as call:
            knowledge.build(lambda _: None)
            call.assert_not_called()
            self.assertEqual(len(knowledge.current()['edges']), 1)
            knowledge.build(lambda _: None, rebuild=True)
            self.assertEqual(knowledge.current()['edges'], [])
            knowledge.build(lambda _: None)
            self.assertEqual(knowledge.current()['edges'], [])

    def test_rebuild_reanalyzes_only_selected_layer_and_rejects_invalid_request(self):
        self.paper(1, True); self.paper(2, True); self.paper(3)
        with patch('paperpilot.providers.generate', side_effect=self.model) as call:
            knowledge.build(lambda _: None)
            first = call.call_count
            knowledge.build(lambda _: None, rebuild=True)
            self.assertEqual(call.call_count, first + 2)
            knowledge.build(lambda _: None)
            self.assertEqual(call.call_count, first + 2)
        with self.assertRaisesRegex(ValueError, '布尔'):
            knowledge.start('true')
        with self.assertRaises(ValueError): knowledge.start(scope='unknown')

    def test_new_read_paper_only_extends_overlay_new_favorite_extends_both(self):
        self.paper(1, True); self.paper(2, True); self.paper(3)
        with patch('paperpilot.providers.generate', side_effect=self.model):
            knowledge.build(lambda _: None)
        core = store.get('knowledge', 'core:starred')
        phases = []
        def model(*args, **kwargs):
            phases.append((args[0]['_knowledge_mainline'], json.loads(args[2][0]['content'].split('\n', 1)[1])))
            return self.model(*args, **kwargs)
        self.paper(4)
        with patch('paperpilot.providers.generate', side_effect=model):
            knowledge.build(lambda _: None)
        self.assertTrue(all(layer != knowledge.CORE_KEY for layer, _ in phases))
        self.assertEqual(store.get('knowledge', 'core:starred')['nodes'], core['nodes'])
        self.assertEqual(store.get('knowledge', 'core:starred')['edges'], core['edges'])
        phases.clear()
        new = self.paper(5, True)
        with patch('paperpilot.providers.generate', side_effect=model):
            knowledge.build(lambda _: None)
        core_pairs = [row for layer, rows in phases if layer == knowledge.CORE_KEY for row in rows if 'A' in row]
        self.assertEqual(len(core_pairs), 2)
        self.assertTrue(all(new['id'] in (row['A']['id'], row['B']['id']) for row in core_pairs))
        newcore = store.get('knowledge', 'core:starred')
        self.assertTrue(all(edge in newcore['edges'] for edge in core['edges']))
        self.assertEqual([e for e in knowledge.current()['edges'] if e['layer']=='core'], newcore['edges'])
        # Existing read papers now have a chance to connect to the new favorite.
        self.assertEqual(len(knowledge.current()['edges']), 10)

    def test_historical_verification_partial_failure_and_no_reading_counts(self):
        rows = historical.parse('2106 | Method 1: Representation Learning | M1\n2021-07 | Method 2: Representation Learning | M2', 'starred')
        def lookup(title, **kwargs):
            return {'title': title, 'abstract': 'An actual source abstract.', 'paper_url': 'https://arxiv.org/abs/2106.09685'}, '2021-06'
        with patch('paperpilot.historical.lookup', side_effect=lookup):
            job = self.wait_job(historical.start('2106 | Method 1: Representation Learning | M1\n2107 | Method 2: Representation Learning | M2', 'starred'))
            self.assertEqual(job['status'], 'completed')
            self.assertEqual([r['ok'] for r in job['result']['results']], [True, False])
            with self.assertRaisesRegex(ValueError, '已在论文库'):
                historical.import_one(rows[0], 'read')
        papers = store.all_objects('paper')
        self.assertEqual(papers[0]['read_status'], '已精读')
        self.assertTrue(papers[0]['starred'])
        self.assertTrue(papers[0]['metadata_only'])
        self.assertEqual(library.statistics(papers), {'today': 0, 'week': 0})
        self.assertFalse(documents.directory(papers[0]['id']).exists())

    def test_lookup_exact_match_fallback_and_no_fabricated_month(self):
        match = {'title': 'Exact: Full Title', 'abstract': 'Real abstract', 'published': '2021-06-17', 'paper_url': 'https://arxiv.org/abs/2106.09685'}
        with patch('paperpilot.title_search.huggingface', return_value=[{**match, 'title':'Exact: Wrong Title'}]), patch('paperpilot.title_search.papers_cool', return_value=[match]), patch('paperpilot.title_search.arxiv') as arxiv:
            self.assertEqual(historical.lookup(match['title'])[1], '2021-06')
            arxiv.assert_not_called()
        with patch('paperpilot.title_search.huggingface', return_value=[]), patch('paperpilot.title_search.papers_cool', side_effect=ValueError('offline')), patch('paperpilot.title_search.arxiv', return_value=[]), patch('paperpilot.historical.identify', return_value=[]), self.assertRaisesRegex(ValueError, '未能核实'):
            historical.lookup('Exact: Full Title')

    def test_vit_import_accepts_multiplication_typography_without_confusing_titles(self):
        title = 'An Image Is Worth 16×16 Words: Transformers for Image Recognition at Scale'
        canonical = title.replace('16×16', '16x16')
        match = {'title':canonical, 'abstract':'Verified original abstract.',
                 'published':'2020-10-22', 'paper_url':'https://arxiv.org/abs/2010.11929'}
        wrong = {**match, 'title':canonical.replace('16x16', '32x32')}
        with patch('paperpilot.title_search.huggingface', return_value=[wrong]), \
             patch('paperpilot.title_search.papers_cool', return_value=[match]), \
             patch('paperpilot.title_search.arxiv') as arxiv:
            row = historical.parse('2010 | '+title+' | ViT', 'read')[0]
            paper = historical.import_one(row, 'read')
            self.assertEqual(paper['original_title'], canonical)
            self.assertEqual(paper_identity.label(paper), '2010 ViT')
            self.assertTrue(paper['metadata_only'])
            self.assertEqual(paper['read_status'], '已速览')
            arxiv.assert_not_called()

    def test_hydration_preserves_identity_notes_and_delete_removes_pdf(self):
        p = self.paper(starred=False)
        p['liked'] = True
        p['notes'] = 'Preserve my own notes'
        store.save('paper', p)
        hydrated = documents.ingest(test_core.pdf(), 'fixture.pdf', p['source_url'], target_id=p['id'])
        self.assertFalse(hydrated['metadata_only'])
        for key in ('id', 'notes', 'read_status', 'short_title', 'publication_month', 'starred', 'liked'):
            self.assertEqual(hydrated[key], p[key])
        folder = documents.directory(p['id'])
        self.assertTrue((folder / 'source.pdf').exists())
        self.assertEqual(documents.ingest(test_core.pdf(), 'again.pdf')['id'], p['id'])
        service.delete_paper(p['id'], False)
        self.assertFalse(folder.exists())

    def test_retrieval_is_bounded_and_includes_favorite_pairs(self):
        nodes = [{'id': str(i), 'title': 'robot model', 'tags': ['robot learning'], 'starred': i<4} for i in range(100)]
        pairs = knowledge.candidate_pairs(nodes)
        self.assertLessEqual(len(pairs), 800)
        self.assertIn(('0', '1'), pairs)
        with self.assertRaises(ValueError):
            knowledge.indexed([{'id':'1'}, {'id':'1'}], {'1'})

    def test_graph_thinking_setting_and_cache_invalidation(self):
        self.assertFalse(store.settings()['knowledge_deep_thinking'])
        self.assertEqual(knowledge.config()['codex_reasoning_effort'], 'medium')
        self.assertEqual(knowledge.config()['deepseek']['thinking'], 'low')
        self.paper()
        with patch('paperpilot.providers.generate', side_effect=self.model):
            knowledge.build(lambda _: None)
        self.assertFalse(knowledge.current()['stale'])
        c = store.settings()
        c['reasoning_policy']={'custom_enabled':True,'overrides':{'knowledge':'high'}}
        store.save_settings(c)
        self.assertEqual(knowledge.config()['codex_reasoning_effort'], 'high')
        self.assertEqual(knowledge.config()['deepseek']['thinking'], 'high')
        self.assertTrue(knowledge.current()['stale'])

    def test_profile_display_is_separate_and_not_in_model_context(self):
        user_profile.save({'institution': '旧学校', 'mainline': 'existing'})
        self.assertEqual(user_profile.get()['school'], '旧学校')
        user_profile.save_display({'display_name': 'UNIQUE_DISPLAY_ONLY', 'gender': '女'})
        user_profile.save_research({'display_name': 'obsolete', 'gender': '男', 'school': '示例大学', 'department': '示例学院', 'laboratory': '示例实验室', 'mainline':'new'})
        p = user_profile.get()
        self.assertEqual(p['display_name'], 'UNIQUE_DISPLAY_ONLY')
        self.assertEqual(p['gender'], '女')
        self.assertEqual(p['institution'], '示例大学-示例学院-示例实验室')
        self.assertNotIn('UNIQUE_DISPLAY_ONLY', user_profile.context())
        self.assertNotIn('性别', user_profile.context())
        self.assertEqual(user_profile.context().count('示例大学'), 1)
        user_profile.save_display({'display_name':'changed', 'gender':''})
        self.assertEqual(user_profile.get()['mainline'], 'new')

    def test_key_reset_blocks_environment_fallback_until_confirmation(self):
        import threading
        import urllib.request
        import urllib.error
        from http.server import ThreadingHTTPServer
        from paperpilot.server import Handler, TOKEN
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        def post(body):
            req = urllib.request.Request(f'http://127.0.0.1:{server.server_port}/api/deepseek-key', json.dumps(body).encode(), {'X-PaperPilot-Token':TOKEN})
            with urllib.request.urlopen(req) as r:
                return json.load(r)
        try:
            with patch.dict('os.environ', {'DEEPSEEK_API_KEY':'sk-environment-test'}):
                with self.assertRaises(urllib.error.HTTPError):
                    post({'action':'confirm', 'key':'new-key'})
                result = post({'action':'reset'})
                self.assertFalse(result['capabilities']['keys']['deepseek'])
                self.assertEqual(providers.api_key('deepseek'), '')
                result = post({'action':'confirm', 'key':'sk-newly-set-fixture'})
                self.assertEqual(providers.api_key('deepseek'), 'sk-newly-set-fixture')
                self.assertNotIn('sk-newly-set-fixture', json.dumps(result))
                self.assertTrue(result['capabilities']['keys']['deepseek'])
        finally:
            server.shutdown()
            server.server_close()

    def test_profile_lists_preserve_legacy_and_feed_models_once(self):
        legacy = '大模型架构 具身智能\n保留已有的自由填写内容'
        user_profile.save({'research_directions':legacy})
        self.assertEqual(user_profile.get()['research_direction_items'],[legacy])
        saved = user_profile.save({'research_direction_items':['大模型架构','具身智能','仿真 benchmark'], 'current_project_items':['模型学习','数据生成']})
        self.assertEqual(saved['research_directions'],'大模型架构\n具身智能\n仿真 benchmark')
        self.assertEqual(saved['current_projects'],'模型学习\n数据生成')
        self.assertEqual(user_profile.context().count('仿真 benchmark'),1)
        self.assertNotIn('research_direction_items', user_profile.context())
        user_profile.save({**saved,'research_directions':'旧客户端的新内容'})
        self.assertEqual(user_profile.get()['research_direction_items'],['旧客户端的新内容'])
        with self.assertRaisesRegex(ValueError,'5 条'):
            user_profile.validate({'research_direction_items':['x']*6})
        with self.assertRaisesRegex(ValueError,'合计最多'):
            user_profile.validate({'research_direction_items':['x'*2000,'y'*2000]})

    def test_users_and_providers_share_policy_schema_and_validation(self):
        from pathlib import Path
        captures = []
        roots = [Path(self.tmp.name)/name for name in ('one','two')]
        for root in roots:
            with store.scope({'directory':root}):
                store.init()
                user_profile.save({'research_directions':'same direction'})
                for provider in ('codex','deepseek'):
                    c = knowledge.config(knowledge.CORE_KEY)
                    c['provider'] = provider
                    def capture(config, system, messages, **kwargs):
                        captures.append((system,messages,kwargs['schema']))
                        return {'value':{'papers':[]}}
                    with patch('paperpilot.providers.generate', side_effect=capture):
                        knowledge.invoke(c,'same instruction',[],{'type':'object'})
                    # Both adapters pass through the same strict application validators.
                    with self.assertRaisesRegex(ValueError,'relevance'):
                        knowledge.node_value({'tags':['method'],'insight':'机制','relevance':'3'})
        self.assertEqual(len(captures),4)
        self.assertTrue(all(item==captures[0] for item in captures))

    def test_json_integer_scores_accept_lossless_numbers_but_never_guess(self):
        value = knowledge.node_value({'tags': ['method'], 'insight': '机制', 'relevance': 3.0})
        self.assertEqual(value['relevance'], 3)
        self.assertIs(type(value['relevance']), int)
        for invalid in ('3', 'high', 2.5, 4, True, None, float('inf')):
            with self.assertRaises(ValueError):
                knowledge.integer_score(invalid, 0, 3, 'relevance')

    def test_truncation_splits_without_losing_successes_and_has_finite_singleton_budget(self):
        payloads = [{'id':str(i)} for i in range(3)]
        calls=[]; config=knowledge.config()
        def invoke(c,prompt,rows,schema):
            calls.append((len(rows), providers.output_limit(c)))
            if len(rows)>1 or providers.output_limit(c)<131072:
                raise providers.GenerationLimitError({'max_tokens':providers.output_limit(c),'content_chars':0})
            return {'papers':[{'id':r['id'],'tags':['method'],'insight':'机制','relevance':2} for r in rows]}
        with patch('paperpilot.knowledge.invoke',side_effect=invoke):
            result=list(knowledge.validated_batch(config,'Analyze',payloads,{},'papers',knowledge.node_value,lambda _:None))
        self.assertEqual({r[0] for r in result},{'0','1','2'})
        self.assertEqual(max(limit for _,limit in calls),131072)
        self.assertTrue(config['output_tokens_auto'])
        calls.clear()
        def always(c,*args):
            calls.append(providers.output_limit(c))
            raise providers.GenerationLimitError({'max_tokens':providers.output_limit(c),'content_chars':0})
        with patch('paperpilot.knowledge.invoke',side_effect=always), self.assertRaisesRegex(ValueError,'停止自动重试'):
            list(knowledge.validated_batch(config,'Analyze',payloads[:1],{},'papers',knowledge.node_value,lambda _:None))
        self.assertEqual(calls,[65536,131072])  # Light reasoning shares the automatic output budget.
        calls.clear();config.update(output_tokens_auto=False,output_tokens=2000)
        with patch('paperpilot.knowledge.invoke',side_effect=always), self.assertRaisesRegex(ValueError,'停止自动重试'):
            list(knowledge.validated_batch(config,'Analyze',payloads[:1],{},'papers',knowledge.node_value,lambda _:None))
        self.assertEqual(calls,[2000])

    def test_one_current_graph_when_provider_changes(self):
        self.paper(1, True); self.paper(2, True)
        user_profile.save({'mainlines': [{'title': 'A'}]})
        line = knowledge.default_mainline()
        for provider in ('deepseek', 'codex'):
            c = knowledge.config(line); c['provider'] = provider
            with patch('paperpilot.providers.generate', side_effect=self.model):
                knowledge.build(lambda _: None, mainline=line, configuration=c)
            graph = knowledge.current(mainline=line)
            self.assertEqual(graph['provider'], provider)
            self.assertNotIn('available_providers', graph)
            self.assertFalse(graph['stale'])
        self.assertEqual(len(store.all_objects('knowledge')), 2)  # one core, one mainline
        self.assertEqual(store.all_objects('knowledge_snapshot'), [])
        c = store.settings(); c['provider'] = 'deepseek'; store.save_settings(c)
        self.assertEqual(knowledge.current(mainline=line)['generated_at'], graph['generated_at'])
        self.assertFalse(knowledge.current(mainline=line)['stale'])

    def test_mainlines_share_current_core_and_mark_old_dependencies_stale(self):
        self.paper(1, True); self.paper(2, True); self.paper(3)
        user_profile.save({'mainlines': [{'title': 'A'}, {'title': 'B'}]})
        lines = [l['key'] for l in knowledge.mainline_options()]
        def distinct(*args, **kwargs):
            result = self.model(*args, **kwargs)
            for row in result['value'].get('pairs', []):
                row['relation'] = args[0]['provider'] + ' relation'
            return result
        for line, provider in zip(lines, ('codex', 'deepseek')):
            c = knowledge.config(line); c['provider'] = provider
            with patch('paperpilot.providers.generate', side_effect=distinct):
                knowledge.build(lambda _: None, mainline=line, configuration=c)
        first, second = [knowledge.current(mainline=line) for line in lines]
        self.assertEqual(first['starred_graph']['provider'], 'deepseek')
        self.assertEqual(first['starred_graph']['edges'], second['starred_graph']['edges'])
        self.assertTrue(first['stale'])
        self.assertFalse(second['stale'])

    def test_parallel_batches_keep_user_context_and_stop_scheduling_after_failure(self):
        import threading
        active=0;maximum=0;lock=threading.Lock();gate=threading.Barrier(2)
        root=store.data_dir()
        def analyze(batch):
            nonlocal active,maximum
            self.assertEqual(store.data_dir(),root)
            with lock:active+=1;maximum=max(maximum,active)
            gate.wait(timeout=2)
            with lock:active-=1
            return batch
        with store.scope({'directory':root}):
            result=list(knowledge.parallel_batches([[1],[2],[3],[4]],analyze))
        self.assertEqual(sorted(result),[[1],[2],[3],[4]])
        self.assertEqual(maximum,2)
        called=[]
        def fail(batch):
            called.append(batch)
            raise ValueError('known failure')
        with self.assertRaisesRegex(ValueError,'known failure'):
            list(knowledge.parallel_batches([[1],[2],[3],[4]],fail))
        self.assertLessEqual(len(called),2)
