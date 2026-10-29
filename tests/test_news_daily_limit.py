import copy
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch
from paperpilot import daily, daily_filter, news_sources, discovery, store


class DailyLimit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.scope = store.scope({'directory': Path(self.tmp.name)})
        self.scope.__enter__()
        store.init()
        self.now = datetime(2026, 10, 19, 12, tzinfo=daily.LOCAL_ZONE)

    def tearDown(self):
        self.scope.__exit__(None, None, None)
        self.tmp.cleanup()

    def rows(self, count=20, day=0, prefix='a'):
        return [{'title': f'{prefix} article {i}', 'source': 'qbitai', 'channel': 'website',
                 'source_url': f'https://www.qbitai.com/{prefix}{day}-{i}',
                 'published': (self.now-timedelta(days=day, minutes=i)).isoformat(),
                 'selection_reason': '研究价值', 'selection_score': i, 'selection_text': '研究正文'}
                for i in range(count)]

    def edition(self, rows):
        return {'id': 'latest', 'articles': rows,
                'items': [{'id': str(i), 'reports': [a]} for i, a in enumerate(rows)],
                'updated_at': self.now.isoformat(), 'window_hours':72,
                'source_version': daily.SOURCE_VERSION, 'sources_signature':news_sources.signature(),
                'source_status': [], 'filtering': {'ok': True, 'context_signature': daily_filter.context_signature()[0]}}

    def test_each_day_global_ranking_and_related_papers(self):
        rows = sum((self.rows(day=day) for day in range(3)), [])
        edition = self.edition(rows)
        for day in range(3):
            result = daily.for_day(edition, day, self.now)
            self.assertEqual(len(result['articles']), 12)
            self.assertEqual(len(result['items']), 12)
            self.assertEqual({a['selection_score'] for a in result['articles']}, set(range(8,20)))
        self.assertEqual(len(daily.limit_articles(self.rows(2))),2)
        duplicates = self.rows(1) + [{**self.rows(1)[0], 'source_url':'https://www.jiqizhixin.com/a', 'source':'jiqizhixin', 'selection_score':99}]
        self.assertEqual(len(daily.limit_articles(duplicates)),1)
        self.assertEqual(daily.limit_articles(duplicates)[0]['source'],'jiqizhixin')

    def test_beijing_calendar_boundary_and_invalid_dates(self):
        rows = self.rows(12)
        for a in rows: a['published'] = '2026-10-18T16:00:00Z'
        extra = {**self.rows(1,prefix='b')[0], 'published':'2026-10-18T15:59:59Z'}
        result = daily.limit_edition(self.edition(rows+[extra,{**extra,'published':'unknown'}]))
        self.assertEqual(len(daily.for_day(result,0,self.now)['articles']),12)
        self.assertEqual(len(daily.for_day(result,1,self.now)['articles']),1)

    def test_old_cache_and_failed_source_merge_remain_capped(self):
        old = self.edition(self.rows())
        store.save('daily',old)
        with patch.object(daily,'utcnow',return_value=self.now):
            self.assertEqual(len(daily.cached()['articles']),12)
        new = self.edition(self.rows(12,prefix='b'))
        new['source_status']=[{'source':'qbitai','ok':False}]
        with patch.object(daily,'utcnow',return_value=self.now+timedelta(hours=2)), patch.object(daily,'collect',return_value=new):
            result=daily.refresh(True)
        self.assertEqual(len(result['articles']),12)
        urls={a['source_url'] for a in result['articles']}
        self.assertTrue(all(r['source_url'] in urls for p in result['items'] for r in p['reports']))
        self.assertEqual(len(store.get('daily','latest')['articles']),12)

    def test_model_priority_is_validated_cached_and_capped(self):
        def generate(config, system, messages, **kwargs):
            import json
            candidates=json.loads(messages[0]['content'])['candidates']
            return {'value': {'decisions': [{'id':a['id'],'keep':True,'reason':'技术信息','score':int(a['title'].rsplit(' ',1)[1])} for a in candidates]}}
        with patch('paperpilot.providers.generate',side_effect=generate) as model:
            first,status=daily_filter.select(self.rows())
            self.assertEqual(len(first),20)
            self.assertEqual(status['selected'],20)
            calls=model.call_count
            self.assertEqual(daily_filter.select(self.rows())[0],first)
            self.assertEqual(model.call_count,calls)
        with patch('paperpilot.providers.generate',return_value={'value':{'decisions':[]}}):
            self.assertEqual(daily_filter.select(self.rows(1,prefix='invalid'))[0],[])

    def test_all_requested_names_and_unverified_sources_do_not_masquerade(self):
        names={discovery.SOURCES[s]['name'] for s in daily.OUTLETS}
        requested={'机器之心','新智元','量子位','DeepTech深科技','AI科技评论','Z Finance','Z Potentials','甲子光年','智能纪元AGI','极市平台','至顶AI实验室','Xbotics具身智能实验室','具身智能之心','具身纪元','深蓝具身智能','SourceMind','罗博脉动RoboVibe','物理AI之心','石麻笔记'}
        self.assertTrue(requested <= names)
        with patch('paperpilot.discovery.public_fetch') as fetch:
            with self.assertRaisesRegex(ValueError,'暂未接入'):
                daily.articles('sourcemind',self.now)
            fetch.assert_not_called()
        feed='<rss><channel><title>AI科技评论</title><item><title>研究进展</title><link>https://mp.weixin.qq.com/s/test</link><pubDate>Mon, 19 Oct 2026 03:00:00 +0000</pubDate></item></channel></rss>'
        with patch('paperpilot.discovery.public_fetch',return_value=feed):
            rows,_=daily.articles('aitechreview',self.now)
            self.assertEqual(rows[0]['channel'],'wechat')
        with patch('paperpilot.discovery.public_fetch',return_value=feed.replace('AI科技评论','Other')):
            with self.assertRaisesRegex(ValueError,'身份不匹配'): daily.articles('aitechreview',self.now)

    def test_model_batches_do_not_share_a_three_day_quota(self):
        import json
        def generate(config, system, messages, **kwargs):
            self.assertIn('不分配入选名额', system)
            self.assertIn('不由你计数或截断', system)
            candidates=json.loads(messages[0]['content'])['candidates']
            for row in candidates:
                self.assertRegex(row['publication_date'], r'^2026-10-\d{2}$')
            return {'value': {'decisions': [
                {'id':row['id'],'keep':True,'reason':'技术信息','score':80}
                for row in candidates]}}
        # Distinct articles across days; the model batches are not daily quotas.
        rows=sum((self.rows(day=day,prefix=f'day{day}') for day in range(3)),[])
        with patch('paperpilot.providers.generate',side_effect=generate):
            articles,status=daily_filter.select(rows)
            self.assertEqual(len(articles),60)
            self.assertEqual(status['selected'],60)
            self.assertEqual(status['reviewed'],60)
            for day in range(3):
                edition=daily.for_day(self.edition(articles),day,self.now)
                self.assertEqual(len(edition['articles']),12)

    def pool_edition(self, count=23):
        rows = self.rows(count)
        value = self.edition(rows)
        value['article_pool'] = rows
        value['paper_pool'] = value['items']
        store.save('daily', daily.limit_edition(value))
        return value

    def test_more_four_at_a_time_without_model_and_retry_idempotent(self):
        self.pool_edition()
        with patch.object(daily, 'utcnow', return_value=self.now), patch('paperpilot.news_metadata.enrich', side_effect=lambda rows, **kw: rows), patch('paperpilot.providers.generate') as model:
            first = daily.for_day(daily.cached())
            self.assertEqual(len(first['articles']), 12)
            self.assertTrue(first['has_more'])
            more = daily.more(0, 12, first['date'])
            self.assertEqual(len(more['articles']), 16)
            self.assertEqual(more['articles'][:12], first['articles'])
            self.assertEqual(len(more['items']), 16)
            self.assertEqual(daily.more(0, 12, first['date'])['articles'], more['articles'])
            more = daily.more(0, 16, first['date'])
            self.assertEqual(len(more['articles']), 20)
            more = daily.more(0, 20, first['date'])
            self.assertEqual(len(more['articles']), 23)
            self.assertFalse(more['has_more'])
            self.assertEqual(len({a['source_url'] for a in more['articles']}), 23)
            model.assert_not_called()

    def test_more_excludes_skipped_and_other_days(self):
        from paperpilot import hotspot_triage
        value = self.pool_edition(18)
        value['article_pool'] += self.rows(20, day=1)
        store.save('daily', daily.limit_edition(value))
        # First 12 have scores 6..17. The next candidate (score 5) is skipped.
        skipped = value['article_pool'][5]
        with patch.object(daily, 'utcnow', return_value=self.now), patch.object(hotspot_triage, 'public', return_value=[{'identity':hotspot_triage.identity(skipped, 'article')}]), patch('paperpilot.news_metadata.enrich', side_effect=lambda rows, **kw: rows):
            result = daily.more(0, 12, self.now.date().isoformat())
            self.assertEqual(len(result['articles']), 16)
            self.assertNotIn(skipped['source_url'], {a['source_url'] for a in result['articles']})
            self.assertEqual(len(daily.for_day(daily.cached(), 1)['articles']), 12)

    def test_more_failure_does_not_advance_and_refresh_keeps_expansion(self):
        value = self.pool_edition()
        with patch.object(daily, 'utcnow', return_value=self.now), patch('paperpilot.news_metadata.enrich', side_effect=ValueError('offline')):
            with self.assertRaisesRegex(ValueError, 'offline'):
                daily.more(0, 12, self.now.date().isoformat())
            self.assertEqual(len(daily.cached()['articles']), 12)
        with patch.object(daily, 'utcnow', return_value=self.now), patch('paperpilot.news_metadata.enrich', side_effect=lambda rows, **kw: rows):
            daily.more(0, 12, self.now.date().isoformat())
            with self.assertRaisesRegex(ValueError, '日期已变化'):
                daily.more(0, 16, '2026-10-18')
        with patch.object(daily, 'utcnow', return_value=self.now+timedelta(hours=2)), patch.object(daily, 'collect', return_value=value):
            refreshed = daily.refresh(True)
            self.assertEqual(len(refreshed['articles']), 16)
