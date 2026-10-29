import json
import tempfile
import time
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from paperpilot import abstracts, collections, discovery, store, title_search
from paperpilot.server import Handler, TOKEN


def paper(title='Deep Residual Learning for Image Recognition', ident='1512.03385v1'):
    return {'id': ident, 'title': title, 'paper_url': 'https://arxiv.org/abs/' + ident,
            'source_url': 'https://arxiv.org/abs/' + ident, 'source': 'arxiv',
            'abstract': 'An original abstract.', 'authors': ['Kaiming He'], 'published': '2015-12-10'}


class TitleSearch(unittest.TestCase):
    real_hf = staticmethod(title_search.huggingface)
    real_cool = staticmethod(title_search.papers_cool)
    real_arxiv = staticmethod(title_search.arxiv)
    def setUp(self):
        self.original = store.DATA
        self.tmp = tempfile.TemporaryDirectory()
        store.DATA = Path(self.tmp.name); store.init()
        self.patches = [patch('paperpilot.title_search.huggingface', return_value=[]),
            patch('paperpilot.title_search.papers_cool', return_value=[]),
            patch('paperpilot.title_search.arxiv', return_value=[]),
            patch('paperpilot.providers.generate', return_value={'value':{'candidates':[]},
                'provider':'deepseek', 'model':'test-model', 'usage':{}})]
        for mock in self.patches: mock.start()
        self.addCleanup(lambda: [mock.stop() for mock in reversed(self.patches)])

    def tearDown(self):
        store.DATA = self.original; self.tmp.cleanup()

    def test_title_prefix_ranking_dedup_and_no_abstract_only_results(self):
        original = paper()
        hf = {**original, 'source':'hf_papers', 'abstract':''}
        rows = [paper('Who invented deep residual learning?', '2509.24732'),
                paper('Quantum particles', '2401.00001'), hf, original]
        result = title_search.rank_and_merge(rows, 'Deep Residual Learning')
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['title'], original['title'])
        self.assertEqual(result[0]['abstract'], original['abstract'])
        self.assertEqual(result[0]['source'], 'hf_papers')

    def test_union_cached_results_and_one_model_call(self):
        other = paper('Deep Residual Learning for Control', '2608.02365')
        with patch('paperpilot.title_search.huggingface', return_value=[paper()]) as hf, \
             patch('paperpilot.title_search.papers_cool', return_value=[other]) as cool, \
             patch('paperpilot.title_search.arxiv', return_value=[paper(), other]) as arxiv, \
             patch('paperpilot.providers.generate', return_value={'value':{'candidates':[]}, 'provider':'deepseek','model':'test','usage':{}}) as model:
            first = title_search.search('Deep Residual Learning')
            second = title_search.search('deep residual learning')
        self.assertEqual(first['id'], second['id'])
        self.assertEqual([hf.call_count,cool.call_count,arxiv.call_count,model.call_count], [1,1,1,1])
        self.assertEqual(len(first['items']), 2)
        self.assertEqual([s['source'] for s in first['source_status']], ['hf_papers','papers_cool','arxiv'])

    def test_arxiv_fallback_for_failure_empty_and_unrelated_hf_results(self):
        for first in ([], [paper('Unrelated quantum article')], ValueError('Unavailable')):
            hf = patch('paperpilot.title_search.huggingface', side_effect=first) if isinstance(first, Exception) else patch('paperpilot.title_search.huggingface', return_value=first)
            with hf, patch('paperpilot.title_search.papers_cool', return_value=[]), patch('paperpilot.title_search.arxiv', return_value=[paper()]) as arxiv:
                # Clear only the isolated test cache between cases.
                for cached in store.all_objects('title_search'): store.remove('title_search', cached['id'])
                result = title_search.search('Deep Residual Learning')
            self.assertEqual(arxiv.call_count, 1)
            self.assertEqual(result['items'][0]['title'], paper()['title'])
            self.assertEqual([s['source'] for s in result['source_status']], ['hf_papers', 'papers_cool', 'arxiv'])
            self.assertEqual(result['complete'], not isinstance(first, Exception))
        saved = collections.save('title-search', result['id'], paper()['id'])
        self.assertEqual(saved['paper']['title'], paper()['title'])
        self.assertEqual(abstracts.resolve('title-search', result['id'], paper()['id'])['abstract'], paper()['abstract'])
        with self.assertRaises(ValueError): collections.save('title-search', result['id'], 'forged')

    def test_total_failure_is_not_successful_empty_result(self):
        with patch('paperpilot.title_search.huggingface', side_effect=TimeoutError), \
             patch('paperpilot.title_search.papers_cool', side_effect=TimeoutError), \
             patch('paperpilot.title_search.arxiv', side_effect=urllib.error.HTTPError('', 429, '', {}, None)):
            result = title_search.search('FastWAM')
        self.assertEqual(result['items'], [])
        self.assertFalse(result['complete'])
        self.assertTrue(all(not s['ok'] for s in result['source_status']))

    def test_invalid_input(self):
        for query in (None, {}, '', 'a', '  ', '!!', 'a'*301):
            with self.assertRaises(ValueError): title_search.search(query)

    def test_dimension_typography_matching_and_database_queries(self):
        canonical = 'An Image is Worth 16x16 Words: Transformers for Image Recognition at Scale'
        for dimension in ('16×16', '16 x 16', '16 X 16', r'16 \times 16'):
            query = canonical.replace('16x16', dimension)
            self.assertTrue(title_search.same_title(query, canonical))
            self.assertIn(canonical, title_search.query_variants(query))
        self.assertFalse(title_search.same_title(canonical, canonical.replace('16x16', '32x32')))
        self.assertFalse(title_search.same_title(canonical, canonical.replace('16x16', '1616')))
        self.assertFalse(title_search.same_title(canonical, canonical.replace('16x16', '16+16')))
        self.assertFalse(title_search.same_title(canonical, 'Channel Vision Transformers: '+canonical))

    def test_pi_subscripts_unicode_latex_and_plain_names(self):
        for expected, forms in [('pi0', ('π₀', r'$\pi_0$', 'Pi_0')),
                                ('pi0.5', ('π₀.₅', r'$\pi_{0.5}$', 'Pi_{0.5}'))]:
            for form in forms:
                self.assertTrue(title_search.same_title(expected+': Model', form+': Model'))
                self.assertIn(expected+': Model', title_search.query_variants(form.strip('$')+': Model'))
        self.assertFalse(title_search.same_title('π₀: Model', 'π₀.₅: Model'))

    def test_same_acronym_union_and_related_candidate_exact_verification(self):
        first = paper('Faster-WAM: Efficient Inference-Time Future Conditioning for Robust World Action Models', '2608.04404')
        second = paper('Faster-WAM: Do World Action Models Need Deep Action Modules?', '2608.02365')
        original = paper('Fast-WAM: Do World Action Models Need Test-time Future Imagination?', '2603.16666')
        invented = 'Fast-WAM: Do World Action Models Need Imaginary Modules?'
        candidates = [{'title':p['title'],'relation':relation} for p,relation in
                      [(first,'alias'),(second,'alias'),(original,'related')]] + [{'title':invented,'relation':'related'}]
        def hf(q): return [first] if q == 'FasterWAM' else [original]
        def cool(q): return [second] if q == 'FasterWAM' else []
        with patch('paperpilot.title_search.huggingface', side_effect=hf) as h, \
             patch('paperpilot.title_search.papers_cool', side_effect=cool) as c, \
             patch('paperpilot.providers.generate', return_value={'value':{'candidates':candidates},'provider':'deepseek','model':'test','usage':{}}):
            result = title_search.search('FasterWAM')
        self.assertEqual({p['id'] for p in result['items']}, {'2608.04404','2608.02365','2603.16666'})
        self.assertEqual(next(p for p in result['items'] if p['id']=='2603.16666')['match_type'], 'related')
        self.assertFalse(result['candidates'][-1]['verified'])
        self.assertNotIn(original['title'], [call.args[0] for call in c.call_args_list])

    def test_alias_absent_from_title_and_profile_context_cache_invalidation(self):
        from paperpilot import user_profile
        reply = {'value':{'candidates':[{'title':paper()['title'],'relation':'alias'}]},'provider':'codex','model':'test','usage':{}}
        def hf(query): return [] if query == 'ResNet' else [paper()]
        with patch('paperpilot.title_search.huggingface', side_effect=hf), \
             patch('paperpilot.providers.generate', return_value=reply) as model:
            first = title_search.search('ResNet')
            self.assertEqual(first['items'][0]['match_type'], 'alias')
            user_profile.save({'mainline':'manual research only'})
            second = title_search.search('ResNet')
            self.assertNotEqual(first['cache_key'], second['cache_key'])
            self.assertEqual(model.call_count, 2)
            self.assertIn('manual research only', model.call_args.args[2][0]['content'])
            self.assertNotIn('本科物理学', model.call_args.args[2][0]['content'])

    def test_model_failure_and_invalid_output_keep_original_union(self):
        for value in (ValueError('private diagnostic'), {'value':{'candidates':'broken'}}):
            mocked = patch('paperpilot.providers.generate', side_effect=value) if isinstance(value, Exception) else patch('paperpilot.providers.generate', return_value=value)
            with mocked, patch('paperpilot.title_search.huggingface', return_value=[paper()]):
                for prior in store.all_objects('title_search'): store.remove('title_search',prior['id'])
                result = title_search.search('Deep Residual Learning')
            self.assertEqual(len(result['items']), 1)
            self.assertFalse(result['model_status']['ok'])
            self.assertNotIn('private diagnostic', json.dumps(result))

    def test_related_candidates_are_name_disambiguation_not_general_recommendations(self):
        value = {'value':{'candidates':[
            {'title':'Fast-WAM: Do World Action Models Need Test-time Future Imagination?', 'relation':'related'},
            {'title':'Copper-Policy: Focus on the Representation for Robust Robot Manipulation', 'relation':'related'}]},
            'provider':'deepseek','model':'test','usage':{}}
        with patch('paperpilot.providers.generate', return_value=value):
            candidates, _ = title_search.resolve_titles('FasterWAM', [], store.settings(), '')
        self.assertEqual(len(candidates), 1)
        self.assertTrue(candidates[0]['title'].startswith('Fast-WAM:'))

    def test_duplicate_versions_merge_sources_but_not_shared_acronym(self):
        first = paper('Faster-WAM: One Approach', '2608.04404v1')
        second = paper('Faster-WAM: Another Approach', '2608.02365')
        rows = title_search.merge_verified([dict(first,source='hf_papers'), dict(first,id='2608.04404v2',source='papers_cool',paper_url='https://arxiv.org/abs/2608.04404v2'), second])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['sources'], ['hf_papers','papers_cool'])
        self.assertFalse(title_search.same_title(first['title'], second['title']))

    def test_cool_priority_between_hf_and_arxiv(self):
        with patch('paperpilot.title_search.huggingface', return_value=[]), \
             patch('paperpilot.title_search.papers_cool', return_value=[{**paper(), 'source':'papers_cool'}]), \
             patch('paperpilot.title_search.arxiv', return_value=[]):
            result = title_search.search('Deep Residual Learning')
        self.assertEqual([s['source'] for s in result['source_status']], ['hf_papers', 'papers_cool', 'arxiv'])
        saved = collections.save('title-search', result['id'], paper()['id'])
        self.assertEqual(saved['paper']['source'], 'papers_cool')

    def test_cool_html_metadata_and_venue_fallback(self):
        card = '''<input id="search-query"><div class="papers"><div id="2603.16666" class="panel paper">
          <h2><a href="https://arxiv.org/abs/2603.16666"><span>#1</span></a>
          <a class="title-link notranslate" href="/arxiv/2603.16666">Fast-WAM: World <em>Action</em> Models</a>
          <a class="title-pdf" data="https://arxiv.org/pdf/2603.16666">PDF</a></h2>
          <p><a class="author">Alice &amp; Bob</a></p><p class="summary">An <b>original</b> abstract.</p>
          <p><span class="date-data">2026-03-17 00:00:00 UTC</span></p><div></div></div></div>'''
        with patch('paperpilot.title_search.papers_cool', wraps=self.real_cool), patch('paperpilot.discovery.public_fetch', return_value=card) as fetch:
            rows = title_search.papers_cool('FastWAM')
        self.assertEqual(fetch.call_count, 2)
        self.assertIn('query=Fast+WAM', fetch.call_args.args[0])
        self.assertEqual(rows[0]['title'], 'Fast-WAM: World Action Models')
        self.assertEqual(rows[0]['abstract'], 'An original abstract.')
        self.assertEqual(rows[0]['authors'], ['Alice & Bob'])
        self.assertEqual(rows[0]['published'], '2026-03-17')
        self.assertEqual(rows[0]['paper_url'], 'https://arxiv.org/abs/2603.16666')
        empty = '<input id="search-query"><p>Total: 0</p>'
        with patch('paperpilot.title_search.papers_cool', wraps=self.real_cool), patch('paperpilot.discovery.public_fetch', side_effect=[empty, card]) as fetch:
            self.assertEqual(len(title_search.papers_cool('FastWAM')), 1)
        self.assertIn('/venue/search?', fetch.call_args.args[0])
        self.assertEqual(title_search.cool_items(empty), [])
        for bad in ('<html>Challenge required</html>', '<input id="search-query"><p>Total: 20</p>'):
            with self.assertRaises(ValueError): title_search.cool_items(bad)

    def test_cool_failure_falls_back_to_arxiv(self):
        with patch('paperpilot.title_search.huggingface', return_value=[]), \
             patch('paperpilot.title_search.papers_cool', side_effect=ValueError('Unexpected page')), \
             patch('paperpilot.title_search.arxiv', return_value=[paper()]):
            result = title_search.search('Deep Residual Learning')
        self.assertEqual(result['items'][0]['title'], paper()['title'])
        self.assertFalse(result['complete'])
        self.assertFalse(result['source_status'][1]['ok'])

    def test_fastwam_alias_matches_hyphenated_title_not_fasterwam(self):
        fast = paper('Fast-WAM: Do World Action Models Need Test-time Future Imagination?', '2603.16666')
        faster = paper('Faster-WAM: Efficient World Action Models', '2608.04404')
        for query in ('FastWAM', 'Fast-WAM', 'Fast WAM', 'fastwam'):
            rows = title_search.rank_and_merge([faster, fast], query)
            self.assertEqual([p['id'] for p in rows], ['2603.16666'])
        with patch('paperpilot.title_search.arxiv', wraps=self.real_arxiv), patch('paperpilot.discovery.search', return_value=[]) as search:
            title_search.arxiv('FastWAM')
        self.assertEqual(search.call_args.args[0], 'ti:"Fast WAM" OR ti:"FastWAM"')
        self.assertEqual(search.call_args.kwargs['sort_by'], 'relevance')
        self.assertEqual(search.call_args.kwargs['recent_days'], 0)
        unrelated = paper('GigaWorld-Policy-0.5: A Faster and Stronger WAM Empowered by AutoResearch', '2609.00001')
        self.assertEqual(title_search.rank_and_merge([unrelated, faster], 'FasterWAM'), [faster])

    def test_hf_official_search_and_variant_fallback(self):
        payload = [{'paper': {'id':'2603.16666', 'title':'Fast-WAM: Do World Action Models Need Test-time Future Imagination?',
                    'authors':[{'name':'Tianyuan Yuan'}], 'summary':'Original abstract', 'publishedAt':'2026-03-17'}}]
        with patch('paperpilot.title_search.huggingface', wraps=self.real_hf), patch('paperpilot.discovery.public_fetch', return_value=json.dumps(payload)) as fetch:
            result = title_search.search('FastWAM')
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(fetch.call_args.args[0]).query)
        self.assertEqual(params['q'], ['Fast-WAM'])
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(result['items'][0]['paper_url'], 'https://arxiv.org/abs/2603.16666')
        with patch('paperpilot.title_search.huggingface', wraps=self.real_hf), patch('paperpilot.discovery.public_fetch', return_value='[]') as fetch:
            self.assertEqual(title_search.huggingface('ResNet'), [])
        self.assertEqual(fetch.call_count, 2)

    def test_endpoint_ignores_legacy_source_and_retired_chat_endpoints_are_gone(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        root = f'http://127.0.0.1:{server.server_port}'
        def post(path, body):
            req = urllib.request.Request(root + path, json.dumps(body).encode(),
                {'Content-Type':'application/json', 'X-PaperPilot-Token':TOKEN})
            with urllib.request.urlopen(req) as response: return json.load(response)
        try:
            with patch('paperpilot.title_search.huggingface', return_value=[paper()]), \
                 patch('paperpilot.providers.generate', return_value={'value':{'candidates':[]},'provider':'codex','model':'test','usage':{}}):
                result = post('/api/title-search', {'query':'Deep Residual Learning', 'source':'crossref'})
                self.assertEqual(result['source_status'][0]['source'], 'hf_papers')
                job = post('/api/title-search', {'query':'Deep Residual Learning', 'async':True})
                for _ in range(100):
                    with urllib.request.urlopen(root+'/api/job/'+job['id']) as response: job=json.load(response)
                    if job['status'] not in ('queued','running'): break
                    time.sleep(.01)
                self.assertEqual(job['status'], 'completed')
                self.assertEqual(job['result']['id'], result['id'])
                fav = post('/api/favorite', {'origin':'title-search', 'run_id':result['id'], 'paper_id':paper()['id']})
                self.assertEqual(fav['paper']['title'], paper()['title'])
                for path in ('/api/research-chat','/api/profile-discuss','/api/profile-discussion-reset','/api/profile-mainline'):
                    with self.assertRaises(urllib.error.HTTPError) as error: post(path, {})
                    self.assertEqual(error.exception.code, 404)
                p = post('/api/profile', {'profile':{'mainline':'手填主线', 'mainline_detail':'手填补充'}})['profile']
                self.assertEqual(p['mainline'], '手填主线')
                with urllib.request.urlopen(root + '/api/bootstrap') as response: state=json.load(response)
                self.assertNotIn('research_chat', state); self.assertNotIn('profile_chat', state)
        finally:
            server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__': unittest.main()
