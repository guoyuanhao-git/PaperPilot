import html
import threading
import unittest
from datetime import datetime, timezone
from email.utils import format_datetime
from unittest.mock import patch
import test_core
from paperpilot import daily, discovery, store


class WechatOutlets(unittest.TestCase):
    setUp = test_core.Core.setUp
    tearDown = test_core.Core.tearDown

    def feed(self, entries, name='量子位'):
        return '<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><title>'+name+'</title>'+''.join(
            '<item><title>Test</title><link>'+html.escape(url)+'</link><pubDate>'+date+'</pubDate>'+body+'</item>'
            for url,date,body in entries)+'</channel></rss>'

    def test_feed_rejects_other_sites_accounts_missing_dates_and_deduplicates_tracking(self):
        now=datetime(2026,10,14,8,tzinfo=timezone.utc)
        date=format_datetime(now)
        url='http://mp.weixin.qq.com/s?__biz=MzIzNjc1NzUzMw==&mid=123&idx=1&sn=abc'
        raw=self.feed([(url+'&scene=0',date,''),(url+'&scene=1',date,''),
            ('https://www.qbitai.com/test',date,''),
            (url.replace('MzIzNjc1NzUzMw==','WrongAccount'),date,''),
            ('https://mp.weixin.qq.com/s/no-date','','')])
        with patch('paperpilot.discovery.public_fetch',return_value=raw) as fetch:
            rows,coverage=daily.wechat_articles('qbitai',now)
        self.assertEqual(len(rows),1)
        self.assertTrue(rows[0]['source_url'].startswith('https://mp.weixin.qq.com/s?'))
        self.assertNotIn('scene',rows[0]['source_url'])
        self.assertIn('3 条',coverage)
        self.assertIn('raw.githubusercontent.com',fetch.call_args.args[0])
        with patch('paperpilot.discovery.public_fetch',return_value=raw.replace('<title>量子位</title>','<title>另一个账号</title>')):
            with self.assertRaises(ValueError):daily.wechat_articles('qbitai',now)
        for bad in ('https://mp.weixin.qq.com.evil/s/test','https://user@mp.weixin.qq.com/s/test','https://mp.weixin.qq.com/mp/profile','javascript:alert(1)'):
            self.assertEqual(daily.wechat_url(bad),'')

    def test_wechat_body_and_rss_full_content_exclude_unrelated_links(self):
        now=datetime.now(timezone.utc)
        row={'source':'qbitai','source_url':'https://mp.weixin.qq.com/s/test','channel':'wechat','published':now.isoformat()}
        raw='<nav>https://arxiv.org/abs/2610.99999</nav><div id="js_content"><a href="https://arxiv.org/abs/2610.00001">论文</a></div><aside>https://arxiv.org/abs/2610.99998</aside>'
        with patch('paperpilot.discovery.public_fetch',return_value=raw):
            _,links=daily.read_wechat_article(row,now)
        self.assertEqual(set(links),{'2610.00001'})
        feed=self.feed([(row['source_url'],format_datetime(now),'<content:encoded><![CDATA[<p>https://arxiv.org/abs/2610.00002</p>]]></content:encoded>')])
        with patch('paperpilot.discovery.public_fetch',return_value=feed):rows,_=daily.wechat_articles('qbitai',now)
        with patch('paperpilot.discovery.public_fetch',side_effect=AssertionError('Full content needs no second fetch')):
            self.assertEqual(set(daily.read_wechat_article(rows[0],now)[1]),{'2610.00002'})

    def test_challenge_stops_requests_but_preserves_title_and_excerpt_links(self):
        now=datetime.now(timezone.utc);blocked=threading.Event()
        row={'source':'qbitai','source_url':'https://mp.weixin.qq.com/s/test','channel':'wechat','title':'News',
             'published':now.isoformat(),'excerpt':'<p>https://arxiv.org/abs/2610.00001</p>'}
        with patch('paperpilot.discovery.public_fetch',return_value='<html>环境异常，请完成验证</html>') as fetch:
            first,links=daily.read_wechat_article(row,now,blocked)
            second,_=daily.read_wechat_article(row,now,blocked)
        self.assertTrue(blocked.is_set());self.assertEqual(fetch.call_count,1)
        self.assertTrue(first['links_unavailable']);self.assertTrue(second['links_unavailable'])
        self.assertEqual(set(links),{'2610.00001'})
        self.assertEqual(first['title'],'News')

    def test_unavailable_accounts_never_fall_back_to_websites(self):
        with patch('paperpilot.discovery.public_fetch',side_effect=AssertionError('No website fallback')):
            for source in ('embodied','shenlan'):
                with self.assertRaisesRegex(ValueError,'停用官网替代'):
                    daily.wechat_articles(source,daily.utcnow())
        for name in ('shenlan','leaderobot'):
            self.assertIn(name,daily.OUTLETS)
            self.assertEqual(discovery.SOURCES[name]['kind'],'news')

    def test_old_website_cache_is_hidden_and_not_revived_on_failure(self):
        now=daily.utcnow()
        website={'source':'qbitai','source_url':'https://www.qbitai.com/test','title':'Website only','published':now.isoformat()}
        old={'id':'latest','updated_at':now.isoformat(),'items':[{'id':'paper','reports':[website]}],
             'articles':[website],'source_status':[],'window_hours':72,'source_version':3}
        store.save('daily',old)
        self.assertEqual(daily.cached()['articles'],[]);self.assertEqual(daily.cached()['items'],[])
        failed={**old,'articles':[],'items':[],'source_status':[{'source':'qbitai','ok':False}]}
        with patch('paperpilot.daily.collect',return_value=failed):
            result=daily.refresh()
        self.assertEqual(result['articles'],[]);self.assertEqual(result['items'],[])
        # Even incorrectly versioned legacy rows must not enter current results.
        store.save('daily',{**old,'source_version':daily.SOURCE_VERSION})
        self.assertEqual(daily.cached()['articles'],[]);self.assertEqual(daily.cached()['items'],[])
