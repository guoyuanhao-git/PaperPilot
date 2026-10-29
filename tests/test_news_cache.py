import copy
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch
from paperpilot import daily, daily_filter, news_cache, news_sources, store
from paperpilot.daily_sources import SINCE


class NewsCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.scope = store.scope({'directory': Path(self.tmp.name)})
        self.scope.__enter__();store.init()
        news_sources.save({'selected':['qbitai'],'custom':[]})
        self.now = datetime(2026,10,19,12,tzinfo=daily.LOCAL_ZONE)

    def tearDown(self):
        self.scope.__exit__(None,None,None);self.tmp.cleanup()

    def row(self, i, days=0):
        return {'title':f'研究 {i}', 'source':'qbitai','channel':'website',
                'source_url':f'https://www.qbitai.com/{i}',
                'published':(self.now-timedelta(days=days)).isoformat()}

    def test_old_days_body_and_model_decisions_reused_new_only(self):
        rows=[self.row(1,1),self.row(2,2),self.row(3)]
        starts=[]
        def listing(source,now):
            starts.append(SINCE.get());return copy.deepcopy(rows),'公开列表'
        def read(row,*args):return {**row,'body':'研究正文，具有具体机制和实验'},{}
        def generate(config,system,messages,**kw):
            import json
            return {'value':{'decisions':[{'id':r['id'],'keep':True,'score':80,'reason':'研究价值'} for r in json.loads(messages[0]['content'])['candidates']]}}
        with patch.object(daily,'articles',side_effect=listing),patch.object(daily,'read_article',side_effect=read) as body,patch('paperpilot.providers.generate',side_effect=generate) as model:
            first=daily.collect(self.now)
            self.assertEqual(body.call_count,3);self.assertEqual(model.call_count,1)
            # Today's listing no longer includes yesterday: its candidates still persist.
            rows[:]=[self.row(3),self.row(4)]
            second=daily.collect(self.now+timedelta(hours=1))
            self.assertEqual(body.call_count,4);self.assertEqual(model.call_count,2)
            self.assertEqual(len(second['articles']),4);self.assertEqual(second['cache_reused_articles'],3)
            third=daily.collect(self.now+timedelta(hours=2))
            self.assertEqual(body.call_count,4);self.assertEqual(model.call_count,2)
            with patch.object(daily,'articles',side_effect=ValueError('temporary failure')):
                failed=daily.collect(self.now+timedelta(hours=3))
                self.assertEqual(len(failed['articles']),4)
                self.assertFalse(failed['source_status'][0]['ok'])
                self.assertEqual(body.call_count,4);self.assertEqual(model.call_count,2)
            self.assertEqual(starts[0],daily.window_start(self.now))
            self.assertEqual(starts[1],self.now.replace(hour=0))
            daily.collect(self.now+timedelta(days=1))
            self.assertEqual(starts[-1],daily.window_start(self.now+timedelta(days=1)))
        self.assertEqual(SINCE.get(),None)

    def test_account_isolation_change_invalidation_and_retry(self):
        config=news_sources.current();r=self.row(1,1);cache=news_cache.Cache(config,self.now)
        cache.merge('qbitai',[r]);cache.remember(r,{**r,'body':'old'},{});cache.save()
        again=news_cache.Cache(config,self.now)
        self.assertIsNotNone(again.body(r));self.assertIsNone(again.body({**r,'title':'edited'}))
        with tempfile.TemporaryDirectory() as other,store.scope({'directory':Path(other)}):
            store.init();self.assertIsNone(news_cache.Cache(config,self.now).body(r))
        self.assertEqual(news_cache.Cache({'selected':[],'custom':[]},self.now).listings,{})
        self.assertEqual(news_cache.Cache(config,self.now+timedelta(days=3)).bodies,{})
        cache.remember(r,{**r,'links_unavailable':True},{},False);cache.save()
        self.assertIsNotNone(news_cache.Cache(config,self.now+timedelta(minutes=30)).body(r,False))
        self.assertIsNone(news_cache.Cache(config,self.now+timedelta(hours=1)).body(r,False))
        self.assertIsNone(news_cache.Cache(config,self.now).body(r,True))

    def test_previous_paper_metadata_reused(self):
        r=self.row(1)
        store.save('daily',{'id':'latest','items':[{'id':'2401.12345','title':'Known paper','source_url':'https://arxiv.org/abs/2401.12345','abstract':'Known abstract'}]})
        with patch.object(daily,'articles',return_value=([r],'public')),patch.object(daily,'read_article',return_value=({**r,'body':'body'},{'2401.12345':'https://arxiv.org/abs/2401.12345'})),patch.object(daily_filter,'select',side_effect=lambda rows:(rows,{'ok':True})),patch.object(daily,'metadata',return_value={}) as metadata:
            result=daily.collect(self.now)
            self.assertEqual(metadata.call_args.args[0],[])
            self.assertEqual(result['items'][0]['title'],'Known paper')

    def test_third_party_feed_rejects_wrong_identity_and_reports_delay(self):
        raw='<rss><channel><title>甲子光年</title><item><title>研究</title><link>https://mp.weixin.qq.com/s/test</link><pubDate>Sun, 18 Oct 2026 03:00:00 +0000</pubDate></item></channel></rss>'
        with patch('paperpilot.discovery.public_fetch',return_value=raw):
            rows,coverage=daily.articles('jazzyear',self.now)
            self.assertEqual(len(rows),1);self.assertIn('BestBlogs',coverage)
            with self.assertRaisesRegex(ValueError,'身份不匹配'):daily.articles('zpotentials',self.now)
