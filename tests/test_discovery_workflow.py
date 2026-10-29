import copy
import json
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from paperpilot import abstracts, collections, daily, discovery, service, store, daily_filter


class DiscoveryWorkflow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = store.DATA
        store.DATA = Path(self.tmp.name)
        store.init()
        from test_daily_filter import passthrough
        patcher=patch('paperpilot.daily_filter.select',side_effect=passthrough)
        patcher.start();self.addCleanup(patcher.stop)
        metadata_patcher=patch('paperpilot.news_metadata.resolve',return_value={});metadata_patcher.start();self.addCleanup(metadata_patcher.stop)
        self.now = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)

    def tearDown(self):
        store.DATA = self.old
        self.tmp.cleanup()

    def wait(self, job):
        for _ in range(200):
            value = store.get('job', job['id'])
            if value['status'] not in ('running', 'queued'):
                return value
            time.sleep(.01)
        self.fail('job timeout')

    def test_count_recommendations_not_saved_or_marked_read(self):
        rows = [{'id': f'2610.{i:05}', 'title': f'Paper {i}', 'source_url': f'https://arxiv.org/abs/2610.{i:05}', 'abstract': 'test'} for i in range(8)]
        response = {'value': {'recommendations': [{'id': p['id'], 'reason': 'fit', 'taste': 'clear', 'tracking': 'new'} for p in rows[:5]]}, 'usage': {}, 'provider': 'fixture', 'model': 'fixture'}
        with patch('paperpilot.discovery.collect', return_value=(rows, [])) as fetch, patch('paperpilot.providers.generate', return_value=response) as model:
            for _ in range(2):
                job = self.wait(service.recommend('world action model', count=5))
                self.assertEqual(job['status'], 'completed', job.get('error'))
                self.assertEqual(len(job['result']['recommendations']), 5)
            self.assertEqual(fetch.call_args.kwargs['count'], 15)
            self.assertEqual(model.call_count, 2)  # Unsaved previous results are still eligible.
        self.assertEqual(store.all_objects('favorite'), [])
        self.assertEqual(len(store.all_objects('discovery')), 1)
        for count in (0, -1, 21, 1.2, True, '5'):
            with self.assertRaises(ValueError): service.recommend('query', count=count)
        with self.assertRaises(ValueError): service.recommend('query', sources=['qbitai'])

    def test_reading_queue_explicit_persistent_deletable(self):
        paper = {'id': '2610.00001v1', 'title': 'Paper', 'source_url': 'https://arxiv.org/abs/2610.00001v1'}
        store.save('discovery', {'id': 'latest-search', 'recommendations': [paper]})
        saved = collections.save('discovery', 'latest-search', paper['id'])
        store.remove('discovery', 'latest-search')
        self.assertEqual(store.get('favorite', saved['id'])['paper']['title'], 'Paper')
        for action in ('archive', 'restore'):
            with self.assertRaises(ValueError): collections.change(saved['id'], action)
        self.assertNotIn('archived', saved)
        self.assertEqual(collections.key(paper), collections.key({**paper, 'source_url': 'https://arxiv.org/abs/2610.00001v2'}))
        store.save('paper', {'id': 'unrelated', 'title': 'Library'})
        collections.change(saved['id'], 'delete')
        self.assertEqual(store.all_objects('favorite'), [])
        self.assertEqual(len(store.all_objects('paper')), 1)
        with self.assertRaises(ValueError): collections.save('daily', '', 'invented')

    def test_legacy_archived_queue_migration_keeps_cards_and_order(self):
        for i, archived in enumerate((False, True)):
            store.save('favorite', {'id':str(i), 'paper':{'title':str(i)},
                                    'created_at':'original', 'archived':archived})
        original = store.all_objects('favorite')
        collections.migrate()
        actual = store.all_objects('favorite')
        self.assertEqual(actual, [{k:v for k,v in f.items() if k!='archived'} for f in original])
        collections.migrate()
        self.assertEqual(store.all_objects('favorite'), actual)

    def test_favorites_and_abstracts_resolve_the_same_trusted_cards(self):
        paper = {'id': '2610.00001', 'title': 'Paper', 'abstract': 'Original abstract.'}
        for origin, kind, field in [('discovery', 'discovery', 'recommendations'),
                                    ('hf-listing', 'hf_listing', 'items'),
                                    ('title-search', 'title_search', 'items')]:
            with self.subTest(origin=origin):
                store.save(kind, {'id': 'run', field: [paper]})
                self.assertEqual(abstracts.resolve(origin, 'run', paper['id']), paper)
                self.assertEqual(collections.save(origin, 'run', paper['id'])['paper'], paper)
                with self.assertRaises(ValueError):
                    collections.save(origin, 'run', 'not-in-results')
                with self.assertRaises(ValueError):
                    abstracts.resolve(origin, 'run', 'not-in-results')
        with patch('paperpilot.daily.cached', return_value={'items': [paper]}):
            self.assertEqual(abstracts.resolve('daily', '', paper['id']), paper)
            self.assertEqual(collections.save('daily', '', paper['id'])['paper'], paper)
        self.assertEqual(abstracts.resolve('favorite', '', paper['id']), paper)
        with self.assertRaises(ValueError):
            collections.save('favorite', '', paper['id'])
        for origin in ('profile-chat', 'research-chat', 'invented'):
            with self.assertRaises(ValueError):
                abstracts.resolve(origin, 'run', paper['id'])

    def test_links_body_boundaries_and_provenance(self):
        body = '<nav>https://arxiv.org/abs/2610.99999</nav><div id="js_content"><p>https://arxiv.org/pdf/2610.00001v2.pdf</p><script>https://arxiv.org/abs/2610.99998</script><a href="https://openreview.net/forum?id=TestA">paper</a></div><aside>https://arxiv.org/abs/2610.99997</aside>'
        links = daily.paper_links(daily.article_body(body, 'qbitai'))
        self.assertEqual(set(links), {'2610.00001', 'https://openreview.net/forum?id=TestA'})
        self.assertEqual(daily.paper_links('javascript:alert(1)'), {})
        self.assertTrue(daily.recent(daily.window_start(self.now).isoformat(), self.now))
        self.assertFalse(daily.recent((daily.window_start(self.now)-timedelta(seconds=1)).isoformat(), self.now))
        self.assertFalse(daily.recent((self.now+timedelta(seconds=1)).isoformat(), self.now))
        def articles(source, now):
            if source == 'jiqizhixin': raise ValueError('需权限')
            return ([{'source': source, 'source_url': 'https://mp.weixin.qq.com/s/'+source, 'title': '报道'+source, 'channel': 'wechat', 'published': now.isoformat(), 'body': 'https://arxiv.org/abs/2610.00001'}], '公开列表')
        with patch('paperpilot.daily.articles', side_effect=articles), patch('paperpilot.daily.metadata', return_value={'2610.00001': {'title': 'Actual paper'}}):
            result = daily.collect(self.now)
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(len(result['articles']),12)
        self.assertEqual({r['source'] for r in result['items'][0]['reports']}, {a['source'] for a in result['articles']})
        self.assertNotIn('jiqizhixin', {a['source'] for a in result['articles']})
        self.assertEqual(result['items'][0]['title'], 'Actual paper')
        self.assertFalse(next(s for s in result['source_status'] if s['source']=='jiqizhixin')['ok'])

    def test_feed_uses_report_dates_not_paper_dates(self):
        from email.utils import format_datetime
        raw='<rss><channel><title>量子位</title>'
        for index, date in enumerate((self.now, self.now-timedelta(days=4))):
            raw += f'<item><title>Old paper covered today</title><link>https://mp.weixin.qq.com/s/test{index}</link><pubDate>{format_datetime(date)}</pubDate></item>'
        raw+='</channel></rss>'
        with patch('paperpilot.discovery.public_fetch',return_value=raw) as fetch:
            rows, coverage=daily.wechat_articles('qbitai',self.now)
        self.assertEqual(len(rows),1)
        self.assertIn('Wechat-Scholar',coverage)
        self.assertEqual(fetch.call_count,1)
        self.assertEqual(rows[0]['published'],self.now.isoformat())

    def test_cache_expiry_filters_old_reports_and_keeps_failed_source_cache(self):
        report = {'source': 'qbitai', 'source_url': 'https://mp.weixin.qq.com/s/test', 'channel':'wechat', 'title': '标题', 'published': self.now.isoformat()}
        result = {'id': 'latest', 'updated_at': self.now.isoformat(), 'items': [{'id': 'test', 'reports': [report]}], 'articles':[{**report,'selection_reason':'研究信息'}], 'source_status': [], 'filtering': {'context_signature':daily_filter.context_signature()[0], 'ok':True}}
        with patch('paperpilot.daily.utcnow', return_value=self.now), patch('paperpilot.daily.collect', return_value=copy.deepcopy(result)) as collect:
            daily.refresh(); daily.refresh(); daily.refresh(True)
            self.assertEqual(collect.call_count, 1)
        later = self.now + timedelta(hours=2)
        failure = {**result, 'updated_at': later.isoformat(), 'items': [], 'source_status': [{'source': 'qbitai', 'ok': False}]}
        with patch('paperpilot.daily.utcnow', return_value=later), patch('paperpilot.daily.collect', return_value=failure):
            value = daily.refresh()
            self.assertTrue(value['items'][0]['reports'][0]['cached'])
        with patch('paperpilot.daily.utcnow', return_value=self.now+timedelta(hours=73)):
            self.assertEqual(daily.cached()['items'], [])

    def test_settings_migrate_old_news_choices(self):
        settings = store.settings()
        settings['discovery_sources'] = ['qbitai', 'huggingface']
        settings['schedule']['sources'] = ['aiera']
        store.save_settings(settings)
        self.assertEqual(store.settings()['discovery_sources'], ['huggingface'])
        self.assertEqual(store.settings()['schedule']['sources'], ['arxiv'])

    def test_import_consumes_favorite_only_after_success(self):
        from test_core import pdf
        item = {'id': '2109.00001', 'kind': 'paper', 'title': 'Verified Paper Title', 'source_url': 'https://arxiv.org/abs/2109.00001', 'published': '2021-09-01T00:00:00Z', 'abstract': 'Verified source abstract', 'authors': ['Example Author']}
        favorite = store.save('favorite', {'id': collections.key(item), 'paper': item, 'created_at': 'now', 'archived': False})
        with patch('paperpilot.discovery.download', side_effect=ValueError('下载失败')):
            failed = self.wait(service.import_paper(favorite_id=favorite['id']))
        self.assertEqual(failed['status'], 'failed')
        self.assertEqual(len(store.all_objects('favorite')), 1)
        with patch('paperpilot.discovery.download', return_value=(pdf(), 'paper.pdf', item['source_url'])), patch('paperpilot.news_metadata.resolve') as lookup:
            result = self.wait(service.import_paper(favorite_id=favorite['id']))
            lookup.assert_not_called()
        self.assertEqual(result['status'], 'completed', result.get('error'))
        self.assertEqual(store.all_objects('favorite'), [])
        paper = store.get('paper', result['result']['paper_id'])
        self.assertEqual(paper['publication_month'], '2021-09')
        self.assertEqual(paper['title'], item['title'])
        self.assertEqual(paper['original_title'], item['title'])
        self.assertEqual(paper['abstract'], item['abstract'])
        self.assertEqual(paper['authors'], item['authors'])
        self.assertIsNone(paper['report'])
        self.assertTrue((store.DATA/'papers'/paper['id']/'source.pdf').exists())

    def test_report_date_uses_publication_not_generation_or_pdf_creation(self):
        from paperpilot import publication
        paper = {'source_url': 'https://arxiv.org/abs/2109.00001v3', 'report': {'title': '论文中文解读', 'generated_at': '2026-10-12'}}
        publication.apply(paper);publication.apply(paper)
        self.assertEqual(paper['report']['title'], '2109 · 论文中文解读')
        paper.update(publication_month='2022-01', publication_date_source='手动填写')
        publication.apply(paper)
        self.assertEqual(paper['report']['title'], '2201 · 论文中文解读')
        unknown = {'filename': '2026-10-12.pdf', 'report': {'title': '未知日期'}, 'CreationDate': '2021-09'}
        self.assertEqual(publication.apply(unknown)['report']['title'], '未知日期')
        uploaded = {'source_url': ''}
        publication.apply(uploaded, 'Title\narXiv:2109.00001v2 [cs.AI] 3 Oct 2022')
        self.assertEqual(uploaded['publication_month'], '2021-09')
        with self.assertRaises(ValueError): publication.validate_month('2021-13')
        with self.assertRaises(ValueError): publication.validate_month('2099-01')
