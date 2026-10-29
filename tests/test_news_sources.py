import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from paperpilot import news_sources as n, daily, daily_filter, store


class NewsSources(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.scope = store.scope({'directory': Path(self.temp.name)})
        self.scope.__enter__()
        store.init()

    def tearDown(self):
        self.scope.__exit__(None, None, None)
        self.temp.cleanup()

    def test_user_isolation_and_validation(self):
        self.assertEqual(n.current()['selected'], list(daily.OUTLETS))
        n.save({'selected': [], 'custom': []})
        with tempfile.TemporaryDirectory() as other, store.scope({'directory': Path(other)}):
            store.init()
            self.assertEqual(n.current()['selected'], list(daily.OUTLETS))
        self.assertEqual(n.current()['selected'], [])
        for value in ('http://example.com/rss', 'https://localhost/rss', 'https://127.0.0.1/rss', 'https://10.0.0.1/rss', 'https://a:b@example.com/rss'):
            with self.assertRaises(ValueError): n.url(value)
        with patch.object(n.socket, 'getaddrinfo', return_value=[(None,None,None,None,('192.168.1.1',443))]), patch.object(n.socket, 'create_connection') as connect:
            with self.assertRaisesRegex(ValueError, '非公开'): n.fetch('https://example.com/rss')
            connect.assert_not_called()

    def test_rss_and_atom_custom_feed_filters_before_ai(self):
        now=daily.utcnow().isoformat()
        raw=f'<rss><channel><title>研究订阅</title><item><title>机器人论文</title><link>https://example.com/article</link><pubDate>{now}</pubDate><description><![CDATA[研究正文 https://arxiv.org/abs/2501.12345]]></description></item></channel></rss>'
        with patch.object(n, 'fetch', return_value=raw):
            record=n.probe('https://example.com/rss')
            n.save({'selected':[record['id']], 'custom':[record]})
            def select(rows):
                self.assertEqual(len(rows),1)
                self.assertIn('研究正文',rows[0]['selection_text'])
                return [{**rows[0],'selection_reason':'技术价值'}], {'ok':True}
            with patch.object(daily, 'articles') as builtin, patch.object(daily_filter,'select',side_effect=select), patch.object(daily,'metadata',return_value={}), patch('paperpilot.news_metadata.enrich',side_effect=lambda items,**kw:list(items)):
                result=daily.collect()
                builtin.assert_not_called()
                self.assertEqual(result['items'][0]['id'],'2501.12345')
                self.assertEqual(result['articles'][0]['source'],record['id'])
        atom=f'<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom</title><entry><title>Test</title><link href="https://example.com/a"/><published>{now}</published><summary>Evidence</summary></entry></feed>'
        self.assertEqual(len(n.parse(atom,record)[1]),1)
        with self.assertRaisesRegex(ValueError,'RSS/Atom'):n.parse('<html/>',record)

    def test_unfollow_hides_cached_articles_papers_and_status(self):
        now=daily.utcnow().isoformat()
        article={'title':'Test','source':'qbitai','channel':'website','source_url':'https://www.qbitai.com/a','published':now,'selection_reason':'技术价值'}
        store.save('daily',{'id':'latest','source_version':daily.SOURCE_VERSION,'updated_at':now,'window_hours':72,'articles':[article],'items':[{'id':'x','reports':[article]}],'source_status':[{'source':'qbitai'}],'sources_signature':n.signature(),'filtering':{'context_signature':daily_filter.context_signature()[0]}})
        self.assertEqual(len(daily.cached()['articles']),1)
        n.save({'selected':[],'custom':[]})
        cached=daily.cached()
        self.assertEqual(cached['articles'],[]);self.assertEqual(cached['items'],[]);self.assertEqual(cached['source_status'],[]);self.assertTrue(cached['stale'])
        with patch.object(daily,'collect',side_effect=lambda:(n.save({'selected':['qbitai'],'custom':[]}) or {})):
            with self.assertRaisesRegex(ValueError,'关注来源已修改'):daily.refresh(True)
        self.assertEqual(store.get('daily','latest')['updated_at'],now)

    def test_empty_selection_makes_no_model_or_remote_calls(self):
        n.save({'selected':[],'custom':[]})
        with patch.object(daily,'articles') as fetch, patch('paperpilot.providers.generate') as model:
            result=daily.refresh(True)
            self.assertEqual(result['items'],[]);self.assertEqual(result['articles'],[])
            fetch.assert_not_called();model.assert_not_called()
