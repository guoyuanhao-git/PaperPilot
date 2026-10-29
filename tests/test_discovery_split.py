import copy
import time
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import test_core
from paperpilot import daily, store, recommendation_chat as chat, collections, abstracts, service, daily_filter


class DiscoverySplit(unittest.TestCase):
    def setUp(self):
        test_core.Core.setUp(self)
        from test_daily_filter import passthrough
        patcher=patch('paperpilot.daily_filter.select',side_effect=passthrough)
        patcher.start();self.addCleanup(patcher.stop)
        metadata_patcher=patch('paperpilot.news_metadata.resolve',return_value={});metadata_patcher.start();self.addCleanup(metadata_patcher.stop)
    tearDown = test_core.Core.tearDown
    wait_job = test_core.Core.wait_job

    def test_calendar_days_include_full_day_and_filter_papers_by_article_date(self):
        now = datetime(2026, 10, 14, 0, 30, tzinfo=daily.LOCAL_ZONE)
        posts = [{'title':'news', 'source':'qbitai', 'source_url':f'https://example.test/{i}',
                  'published':stamp} for i,stamp in enumerate([
                      '2026-10-13T16:05:00Z', '2026-10-13T15:59:59Z',
                      '2026-10-11T16:00:00Z', '2026-10-11T15:59:59Z', '2026-10-14T08:00:00Z'])]
        value = {'items':[{'id':'paper', 'published':'2020-01-01', 'reports':posts}], 'articles':posts}
        for offset, expected in [(0,0),(1,1),(2,2)]:
            result=daily.for_day(value,offset,now)
            self.assertEqual(result['articles'],[posts[expected]])
            self.assertEqual(result['items'][0]['reports'],[posts[expected]])
        self.assertTrue(daily.recent(posts[2]['published'],now))
        self.assertFalse(daily.recent(posts[3]['published'],now))
        for offset in (-1,3,True,'1'):
            with self.assertRaises(ValueError):daily.for_day(value,offset,now)

    def test_day_sorts_mixed_timezones_by_actual_time(self):
        now=datetime(2026,10,14,20,tzinfo=daily.LOCAL_ZONE)
        posts=[{'published':'2026-10-14T08:00:00Z','title':'A','source_url':'https://example.test/a'}, {'published':'2026-10-14T10:00:00+08:00','title':'B','source_url':'https://example.test/b'}]
        papers=[{'id':str(i),'reports':[p]} for i,p in enumerate(posts)]
        result=daily.for_day({'articles':list(reversed(posts)),'items':list(reversed(papers))},0,now)
        self.assertEqual(result['articles'],posts)
        self.assertEqual(result['items'],papers)

    def test_articles_without_papers_and_failed_bodies_are_kept(self):
        now = datetime.now(timezone.utc)
        rows=[{'title':title,'source':'qbitai','channel':'wechat','source_url':'https://mp.weixin.qq.com/s/'+title,
               'published':now.isoformat(),'body':body} for title,body in [('NoPaper','Industry news'),('Paper','https://arxiv.org/abs/2106.09685')]]
        rows.append({'title':'Unread','source':'qbitai','channel':'wechat','source_url':'https://mp.weixin.qq.com/s/unread','published':now.isoformat()})
        with (patch.object(daily,'OUTLETS',('qbitai',)), patch.object(daily,'articles',return_value=(rows,'test')),
              patch.object(daily,'metadata',return_value={}), patch('paperpilot.discovery.public_fetch',side_effect=ValueError('offline'))):
            result=daily.collect(now)
        self.assertEqual(len(result['articles']),3)
        self.assertEqual(len(result['items']),1)
        self.assertTrue(next(a for a in result['articles'] if a['title']=='Unread')['links_unavailable'])
        self.assertFalse(result['source_status'][0]['ok'])
        self.assertTrue(all('body' not in a for a in result['articles']))

    def test_failed_refresh_preserves_articles_and_midnight_invalidates_cache(self):
        now=datetime(2026,10,13,23,59,tzinfo=daily.LOCAL_ZONE)
        article={'selection_reason':'测试','title':'News','source':'qbitai','channel':'wechat','source_url':'https://mp.weixin.qq.com/s/a','published':now.isoformat()}
        value={'id':'latest','updated_at':now.isoformat(),'articles':[article],'items':[],
               'source_status':[],'source_version':daily.SOURCE_VERSION,'window_hours':72, 'filtering':{'ok':True,'context_signature':daily_filter.context_signature()[0]}}
        store.save('daily',value)
        with patch.object(daily,'utcnow',return_value=now):self.assertFalse(daily.cached()['stale'])
        later=now+timedelta(minutes=2)
        failed={**value,'updated_at':later.isoformat(),'articles':[], 'source_status':[{'source':'qbitai','ok':False}]}
        with patch.object(daily,'utcnow',return_value=later),patch.object(daily,'collect',return_value=failed):
            self.assertTrue(daily.cached()['stale'])
            result=daily.refresh()
            self.assertTrue(result['articles'][0]['cached'])
            self.assertEqual(len(daily.for_day(result,1,later)['articles']),1)

    def test_multi_turn_provider_switch_and_verified_cards(self):
        seen=[]
        def generate(config, system, messages, **kwargs):
            seen.append((config['provider'], copy.deepcopy(messages)))
            return {'value':{'reply':'建议阅读 A Verified Paper，先讨论适用条件。', 'brief':'找结构简单的论文，预算有限。',
                'candidates':[{'title':'A Verified Paper','reason':'适合验证关键假设'},{'title':'Unknown Paper','reason':'待确认'}]},
                'provider':config['provider'],'model':'test','usage':{}}
        with patch('paperpilot.providers.generate',side_effect=generate):
            first=self.wait_job(chat.discuss('我要找参数高效适配论文',0))
            self.assertEqual(first['status'],'completed',first.get('error'))
            c=store.settings();c['provider']='deepseek';store.save_settings(c)
            second=self.wait_job(chat.discuss('训练资源有限，能否更简单',1))
            self.assertEqual(second['status'],'completed',second.get('error'))
        self.assertEqual([s[0] for s in seen],['codex','deepseek'])
        self.assertTrue(any('我要找参数高效适配论文' in m['content'] for m in seen[1][1]))
        self.assertEqual(len(chat.current()['messages']),4)
        with self.assertRaises(ValueError):chat.discuss('stale',0)
        paper={'id':'2106.09685','title':'A Verified Paper','source':'papers_cool','abstract':'Source abstract',
               'paper_url':'https://arxiv.org/abs/2106.09685','source_url':'https://arxiv.org/abs/2106.09685'}
        with patch('paperpilot.title_search.huggingface',return_value=[]),patch('paperpilot.title_search.papers_cool',return_value=[paper]),patch('paperpilot.title_search.arxiv',return_value=[]) as ax:
            result=self.wait_job(chat.recommend(2))
        self.assertEqual(result['status'],'completed',result.get('error'))
        cards=result['result']['result']
        self.assertEqual(len(cards['items']),1)
        self.assertFalse(cards['complete']);self.assertEqual(ax.call_count,1)
        self.assertEqual(store.all_objects('favorite'),[])
        self.assertEqual(abstracts.resolve('model-recommendation',cards['id'],paper['id'])['abstract'],'Source abstract')
        saved=collections.save('model-recommendation',cards['id'],paper['id'])
        chat.reset()
        self.assertEqual(chat.current()['messages'],[])
        self.assertEqual(len(store.all_objects('recommendation_archive')),1)
        self.assertEqual(store.get('favorite',saved['id'])['paper']['id'],paper['id'])

    def test_failed_model_keeps_history_and_busy_guard(self):
        with patch('paperpilot.providers.generate',side_effect=ValueError('test failure')):
            failed=self.wait_job(chat.discuss('Test',0))
        self.assertEqual(failed['status'],'failed')
        self.assertEqual(chat.current()['revision'],0)
        public=chat.public()
        self.assertEqual(public['last_task']['question'],'Test')
        self.assertEqual(public['last_task']['status'],'failed')
        self.assertNotIn('last_task',chat.current())
        chat.reset()
        self.assertNotIn('last_task',chat.public())
        with self.assertRaises(ValueError):chat.recommend(0)
        store.save('job',{'id':'busy','kind':'recommendation-discuss','status':'running'})
        with self.assertRaises(ValueError):chat.discuss('Test',0)
        with self.assertRaises(ValueError):chat.reset()
