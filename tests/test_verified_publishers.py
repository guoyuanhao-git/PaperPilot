import unittest
from datetime import datetime
from unittest.mock import patch
from paperpilot import daily,daily_sources as s,discovery


class VerifiedPublishers(unittest.TestCase):
    def test_list_and_body_identity_dates_and_boundaries(self):
        now=datetime(2026,10,19,12,tzinfo=daily.LOCAL_ZONE)
        raw='<h1>Xbot具身知识库</h1><div data-author-id="190"><article class="article-content-item"><h3><a href="https://www.x-techcon.com/article/123.html">Paper news</a></h3><p>2026-10-19 11:00:00</p></article></div>'
        row=s.verified_publisher_rows(raw,'xbotics')[0]
        self.assertEqual(row['published'],'2026-10-19T11:00:00+08:00')
        body='<a href="https://www.x-techcon.com/author/190.html">Xbotics具身智能实验室</a><li class="article-time"><span>2026-10-19 11:00:00</span></li><div id="article-body-wrap">研究 https://arxiv.org/abs/2610.12345</div><aside>https://arxiv.org/abs/2610.99999</aside>'
        with patch.object(discovery,'public_fetch',return_value=body):
            result,links=s.read_website_article(row,now)
            self.assertEqual(list(links),['2610.12345'])
        with patch.object(discovery,'public_fetch',return_value=body.replace('author/190','author/999')):
            with self.assertRaisesRegex(ValueError,'身份不匹配'):s.read_website_article(row,now)
        with patch.object(discovery,'public_fetch',return_value=body.replace('2026-10-19','2026-10-10')):
            self.assertEqual(s.read_website_article(row,now)[1],{})
        with self.assertRaisesRegex(ValueError,'身份不匹配'):s.verified_publisher_rows(raw.replace('Xbot具身知识库','Other'),'xbotics')

    def test_zhiding_charset_routing_and_own_column_only(self):
        now=datetime(2026,10,19,12,tzinfo=daily.LOCAL_ZONE)
        raw='<title>至顶AI实验室-至顶网</title><article class="feed-item"><h3><a href="//www.zhiding.cn/zd-ai-lab/2026/1019/123.shtml">测试</a></h3><div class="times">2026-10-19</div></article>'
        with patch.object(discovery,'public_fetch',return_value=raw) as fetch:
            rows,coverage=s.website_articles('zhidingai',now)
            self.assertEqual(len(rows),1);self.assertEqual(fetch.call_args.kwargs['encoding'],'gb18030')
            self.assertIn('不保证',coverage)
        with self.assertRaises(ValueError):s.verified_publisher_rows(raw.replace('/zd-ai-lab/','/other/'),'zhidingai')
        body='<div class="article-head">至顶AI实验室<div class="byline">2026-10-19</div></div><div class="article-layout shell"><div class="txts">研究 https://arxiv.org/abs/2610.12345</div></div><footer>https://arxiv.org/abs/2610.99999</footer>'
        with patch.object(discovery,'public_fetch',return_value=body):
            result,links=s.read_website_article(rows[0],now)
            self.assertEqual(list(links),['2610.12345'])
