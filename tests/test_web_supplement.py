import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from paperpilot import store, web_supplement as web, title_search, daily


class WebSupplement(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.scope = store.scope({'directory': Path(self.tmp.name)})
        self.scope.__enter__(); store.init()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(lambda: self.scope.__exit__(None, None, None))
        self.key = patch('paperpilot.providers.api_key', return_value='test-key')
        self.key.start(); self.addCleanup(self.key.stop)

    def enable(self, flag=True):
        config = store.settings(); config['web_supplement_enabled'] = flag; store.save_settings(config)

    def test_disabled_never_uses_key_network_or_cache(self):
        with patch('paperpilot.providers.post_json') as post:
            self.assertEqual(web.Session().search('Test Paper'), [])
            self.assertEqual(web.Session().fetch('https://example.org/article'), {})
        post.assert_not_called(); self.assertEqual(web.usage()['attempts'], 0)

    def test_success_cache_live_disable_and_account_isolation(self):
        self.enable()
        with patch('paperpilot.providers.post_json', return_value={'results':[{'title':'Paper'}]}) as post:
            self.assertEqual(len(web.Session().search('Test Paper')), 1)
            session = web.Session(); session.search('Test Paper')
            self.assertEqual(session.summary()['cache_hits'], 1)
            self.assertEqual(web.usage()['estimated_cny'], .005)
            self.enable(False); self.assertEqual(session.search('Test Paper'), [])
            with tempfile.TemporaryDirectory() as other, store.scope({'directory': Path(other)}):
                store.init(); self.assertFalse(web.enabled()); self.assertEqual(web.usage()['attempts'], 0)
                self.enable(); web.Session().search('Test Paper')
            self.assertEqual(post.call_count, 2)

    def test_request_limits_errors_and_estimates(self):
        self.enable()
        with patch('paperpilot.providers.post_json', return_value={'results':[{}]}) as post:
            session = web.Session(searches=1)
            session.search('a'*200); session.search('different title')
            self.assertEqual(post.call_count, 1)
            self.assertLessEqual(len(post.call_args.args[1]['query']), 128)
        store.save('web_usage', {'id':web.day_id(), 'attempts':60, 'successful':1, 'unknown':0})
        with patch('paperpilot.providers.post_json') as post:
            self.assertEqual(web.Session().search('budget'), [])
            post.assert_not_called()
        store.save('web_usage', {'id':web.day_id(), 'attempts':0, 'successful':0, 'unknown':0})
        with patch('paperpilot.providers.post_json', side_effect=ValueError('模型服务返回 HTTP 429：额度限制')) as post:
            session=web.Session(); session.search('rate limited'); session.search('no retry')
            self.assertEqual(post.call_count, 1); self.assertEqual(web.usage()['estimated_cny'], 0)
        with patch('paperpilot.providers.post_json', side_effect=TimeoutError):
            web.Session().search('timeout')
        self.assertEqual(web.usage()['unknown'], 1)

    def test_known_articles_only_preserve_dates_and_extract_markdown_links(self):
        row={'source':'qbitai','channel':'website','title':'Source title',
             'source_url':'https://www.qbitai.com/2026/10/1.html','published':'2026-10-19T12:00:00+08:00'}
        session=web.Session()
        with patch.object(session, 'fetch', return_value={'title':'Remote title','content':'Actual article. '*30+r' [paper](https\:\/\/arxiv\.org\/abs\/2401\.12345)'}) as fetch:
            result, links=web.supplement_article(row,session)
            self.assertEqual(result['published'],row['published']); self.assertEqual(result['title'],row['title'])
            self.assertIn('2401.12345',links)
            self.assertIsNone(web.supplement_article({**row,'source_url':'https://unrelated.example/a'}, session))
            self.assertEqual(fetch.call_count,1)
        with patch.object(session,'fetch',return_value={'content':'环境异常 '*100}):
            self.assertIsNone(web.supplement_article(row,session))

    def test_verified_original_title_required_not_search_summary(self):
        session=web.Session()
        hit={'title':'Invented Paper','url':'https://arxiv.org/abs/2401.12345','summary':'Invented abstract'}
        with patch('paperpilot.discovery.public_fetch',return_value='<meta name="citation_title" content="Real Paper">'):
            p=web.verify_paper(hit,session)
            self.assertEqual(p['title'],'Real Paper'); self.assertEqual(p['abstract'],'')
        with patch('paperpilot.discovery.public_fetch',side_effect=ValueError), patch.object(session,'fetch',return_value={'title':'Invented Paper','content':'# Unrelated Page'}):
            self.assertIsNone(web.verify_paper(hit,session))
        self.assertEqual(web.primary_url('https://random.blog/a'), '')
        for url in ('http://127.0.0.1/private','https://user:pass@example.com/a','https://localhost/a'):
            with self.assertRaises(ValueError):session.fetch(url)

    def test_fallback_is_not_called_on_existing_verified_results(self):
        self.enable()
        paper={'id':'p','title':'A Known Paper','source':'arxiv','paper_url':'https://arxiv.org/abs/2401.12345','authors':[]}
        response={'value':{'candidates':[]},'provider':'codex','model':'test','usage':{}}
        with patch('paperpilot.title_search.huggingface',return_value=[paper]), patch('paperpilot.title_search.papers_cool',return_value=[]), patch('paperpilot.title_search.arxiv',return_value=[]), patch('paperpilot.providers.generate',return_value=response), patch.object(web,'find_papers') as fallback:
            result=title_search.search('A Known Paper')
            self.assertEqual(len(result['items']),1);fallback.assert_not_called()

    def test_alias_fallback_merges_only_verified_candidates(self):
        self.enable()
        paper={'id':'p','title':'A Distinctive Paper','source':'deepseek_web','paper_url':'https://arxiv.org/abs/2401.12345','authors':[]}
        response={'value':{'candidates':[{'title':paper['title'],'relation':'alias'}]},'provider':'deepseek','model':'test','usage':{}}
        with patch('paperpilot.title_search.huggingface',return_value=[]), patch('paperpilot.title_search.papers_cool',return_value=[]), patch('paperpilot.title_search.arxiv',return_value=[]), patch('paperpilot.providers.generate',return_value=response), patch.object(web,'find_papers',return_value=([paper],[])) as fallback:
            result=title_search.search('ADP')
            self.assertEqual(result['items'][0]['title'],paper['title']);self.assertEqual(fallback.call_count,1)

    def test_daily_fetch_is_in_account_scope_and_keeps_baseline_when_disabled(self):
        self.enable()
        row={'source':'qbitai','channel':'website','title':'Article', 'links_unavailable':True,
             'source_url':'https://www.qbitai.com/2026/10/1.html','published':daily.utcnow().isoformat()}
        def select(rows):
            return [dict(r,selection_reason='Research') for r in rows], {'ok':True}
        def fetch(url):
            self.assertEqual(store.data_dir(),Path(self.tmp.name))
            return {'content':'Research text. '*30+' https://arxiv.org/abs/2401.12345'}
        from paperpilot import news_sources
        news_sources.save({'selected':['qbitai'],'custom':[]})
        with patch.object(daily,'articles',return_value=([row],'test')), patch.object(daily,'read_article',return_value=(row,{})), patch.object(web.Session,'fetch',side_effect=fetch) as remote, patch('paperpilot.daily_filter.select',side_effect=select), patch.object(daily,'metadata',return_value={}), patch('paperpilot.news_metadata.enrich',side_effect=lambda rows,**kwargs:list(rows)):
            result=daily.collect()
            self.assertEqual(result['articles'][0]['body_source'],'deepseek_fetch')
            self.assertEqual(result['items'][0]['id'],'2401.12345')
            self.enable(False); result=daily.collect()
            self.assertEqual(remote.call_count,1)
            # Disabling networking prevents new paid calls; existing evidence remains reusable.
            self.assertEqual(result['items'][0]['id'],'2401.12345')

    def test_malformed_response_is_optional_failure_not_search_crash(self):
        self.enable()
        with patch('paperpilot.providers.post_json',return_value={'results':None}):
            session=web.Session()
            self.assertEqual(web.find_papers('Paper',session),([],[]))
            self.assertTrue(session.summary()['errors'])


if __name__ == '__main__': unittest.main()
