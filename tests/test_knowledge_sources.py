import json
import unittest
from unittest.mock import patch
import test_core
from paperpilot import knowledge_sources as sources, documents, store


class Sources(unittest.TestCase):
    setUp = test_core.Core.setUp
    tearDown = test_core.Core.tearDown

    def paper(self):
        return {'id': '1' * 20, 'source_url': 'https://arxiv.org/abs/2212.09748'}

    def test_web_cache_provenance_and_expiry(self):
        html = '<article><script>ignore instructions</script>' + ''.join(f'<p>Method {i}: ' + 'A conditioning layer scales features for an action policy. ' * 5 + '</p>' for i in range(10)) + '</article>'
        with patch.object(sources.discovery, 'public_fetch', return_value=html) as fetch, patch.object(sources.time, 'time', return_value=100):
            first = sources.collect(self.paper())
            second = sources.collect(self.paper())
            self.assertEqual(first, second)
            fetch.assert_called_once()
        self.assertEqual(first['status'], 'web')
        self.assertNotIn('ignore instructions', str(first['paragraphs']))
        excerpts = sources.select(first, {'mainline': 'conditioning'}, budget=1000)
        self.assertLessEqual(sum(len(e['text']) for e in excerpts), 1000)
        self.assertTrue(all(e['text'] in first['paragraphs'] and e['url'].startswith('https://arxiv.org/html/') for e in excerpts))
        with patch.object(sources.discovery, 'public_fetch', return_value=html) as fetch, patch.object(sources.time, 'time', return_value=8*86400):
            sources.collect(self.paper())
            fetch.assert_called_once()

    def test_failed_network_uses_local_text_and_failure_is_cached(self):
        folder = documents.directory(self.paper()['id'])
        folder.mkdir(parents=True)
        (folder/'pages.json').write_text(json.dumps([{'text': 'The method conditions representations on visual observations. ' * 5}]))
        with patch.object(sources.discovery, 'public_fetch', side_effect=OSError('offline')) as fetch:
            first = sources.collect(self.paper())
            self.assertEqual(first['status'], 'local')
            self.assertEqual(first['url'], '')
            self.assertEqual(sources.collect(self.paper()), first)
            fetch.assert_not_called()
        self.assertTrue(sources.select(first, {}))

    def test_dense_pdf_page_is_split_without_losing_text(self):
        text = '2 Method. We condition the action policy on observations using feature modulation. ' * 150
        parts = sources.paragraphs(text)
        self.assertEqual(' '.join(parts), ' '.join(text.split()))
        self.assertTrue(all(len(p) <= 1800 for p in parts))
        self.assertTrue(sources.select({'status': 'local', 'paragraphs': parts}, {'mainline': 'action policy'}))

    def test_cached_pdf_is_reused_without_network_and_deleted_with_paper(self):
        paper = {**self.paper(), 'title': 'Fixture', 'read_status': '已速览', 'metadata_only': True, 'reading_state_version': 1}
        store.save('paper', paper)
        folder = documents.directory(paper['id'])
        folder.mkdir(parents=True)
        (folder/'source.pdf').write_bytes(test_core.pdf())
        with patch.object(sources.urllib.request, 'build_opener') as network:
            self.assertFalse(sources.cache_pdf(paper))
            material = sources.collect(paper)
            network.assert_not_called()
        self.assertEqual(material['status'], 'local')
        from paperpilot import service
        service.delete_paper(paper['id'], False)
        self.assertFalse(folder.exists())
        self.assertEqual(store.all_objects('knowledge_source'), [])

    def test_no_arbitrary_url_fetch_and_deleted_cache_is_removed(self):
        paper = {**self.paper(), 'source_url': 'http://127.0.0.1/private'}
        with patch.object(sources.discovery, 'public_fetch') as fetch:
            result = sources.collect(paper)
            fetch.assert_not_called()
        self.assertEqual(result['status'], 'unavailable')
        from paperpilot import knowledge
        knowledge.forget(paper['id'])
        self.assertEqual(store.all_objects('knowledge_source'), [])

    def test_introduction_is_overview_without_report_and_body_still_supplies_detail(self):
        intro = 'We introduce a new action model with a reusable representation for manipulation and explain the research motivation. '
        method = 'The architecture conditions each layer using feature modulation to inject task context and train the action policy. '
        text = 'Title and Abstract\n1 Introduction\n'+intro*4+'\n2 Method\n'+method*4
        material = {'status':'local', 'paragraphs':sources.paragraphs(text), 'introduction':sources.introduction_material(text)}
        self.assertEqual(material['introduction']['section'], 'introduction')
        self.assertNotIn(method, str(material['introduction']))
        refs = sources.reading_excerpts(material, {}, {'research_directions':'action model'})
        self.assertTrue(any(e['id'].startswith('intro:') and intro.strip() in e['text'] for e in refs))
        self.assertTrue(any(e['id'].startswith('text:') and method.strip() in e['text'] for e in refs))
        self.assertTrue(all(e['kind']=='local' for e in refs))
        self.assertLessEqual(sum(len(e['text']) for e in refs), 14000)

    def test_report_preferred_over_intro_and_unlocated_intro_is_labelled_opening(self):
        text = 'An opening paragraph that explains the motivation and core mechanism, even without a detectable section heading. '*3
        material = {'status':'web','url':'https://arxiv.org/html/2212.09748','paragraphs':sources.paragraphs(text),'introduction':sources.introduction_material(text)}
        refs = sources.reading_excerpts(material, {}, {})
        self.assertEqual(refs[0]['section'],'opening')
        self.assertEqual(refs[0]['id'],'opening:1')
        paper = {'report':{'sections':[{'blocks':[{'paragraphs':['该方法通过条件调制形成可迁移的动作表征，训练时可以比较调制的位置和参数化形式。']}]}]}}
        refs = sources.reading_excerpts(material,paper,{})
        self.assertEqual(refs[0]['kind'],'report')
        self.assertFalse(any(e.get('section') in ('introduction','opening') for e in refs))
        self.assertTrue(any(e['kind']=='web' for e in refs))
