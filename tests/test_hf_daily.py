import copy
import json
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from paperpilot import abstracts, collections, daily, hf_daily, store
from paperpilot.server import Handler, TOKEN


def row(number, published='2021-09-01T00:00:00Z'):
    return {'paper':{'id':f'2610.{number:05}', 'title':f'Paper {number}', 'summary':'Original abstract',
                     'publishedAt':published, 'submittedOnDailyAt':'2026-10-13T00:00:00Z'},
            'publishedAt':published}


class HfDaily(unittest.TestCase):
    def setUp(self):
        self.original=store.DATA
        self.tmp=tempfile.TemporaryDirectory()
        store.DATA=Path(self.tmp.name);store.init()
        self.now=datetime(2026,10,12,18,tzinfo=timezone.utc)  # Oct 13 in the user's timezone.

    def tearDown(self):
        store.DATA=self.original;self.tmp.cleanup()

    def test_all_pages_and_old_papers_newly_collected(self):
        batches=[[row(i) for i in range(1,101)], [row(101),row(102)], []]
        with patch('paperpilot.discovery.public_fetch',side_effect=[json.dumps(x) for x in batches]) as fetch, patch('paperpilot.providers.generate',side_effect=AssertionError('No model calls')):
            papers,status=hf_daily.edition('2026-10-13')
        self.assertEqual(len(papers),102)
        self.assertTrue(status['ok'])
        self.assertEqual(papers[0]['published'][:7],'2021-09')
        self.assertEqual(papers[0]['daily_at'][:10],'2026-10-13')
        self.assertTrue(all(p['listing_date']=='2026-10-13' for p in papers))
        self.assertEqual([urllib.parse.parse_qs(urllib.parse.urlsplit(c.args[0]).query)['p'] for c in fetch.call_args_list],[['0'],['1'],['2']])

    def test_local_dates_deduplication_and_empty_edition(self):
        def edition(day):
            papers=[] if day=='2026-10-11' else [{'id':'2610.00001','listing_date':day}]
            return papers,{'source':'huggingface','date':day,'ok':True,'count':len(papers)}
        with patch('paperpilot.hf_daily.edition',side_effect=edition):
            value=hf_daily.collect(3,self.now)
        self.assertEqual(value['dates'],['2026-10-13','2026-10-12','2026-10-11'])
        self.assertEqual(len(value['items']),1)
        self.assertEqual(value['items'][0]['listing_date'],'2026-10-13')
        self.assertTrue(value['complete'])

    def test_repeating_page_is_partial_and_network_failure_keeps_known_cards(self):
        with patch('paperpilot.discovery.public_fetch',return_value=json.dumps([row(1)])) as fetch:
            papers,status=hf_daily.edition('2026-10-13')
        self.assertEqual(fetch.call_count,2);self.assertEqual(len(papers),1)
        self.assertFalse(status['ok']);self.assertIn('重复',status['message'])
        with patch('paperpilot.discovery.public_fetch',side_effect=[json.dumps([row(1)]),TimeoutError]):
            papers,status=hf_daily.edition('2026-10-13')
        self.assertEqual(len(papers),1);self.assertFalse(status['ok'])

    def test_cache_force_and_date_change(self):
        value={'id':'run1','days':1,'dates':['2026-10-13'],'updated_at':self.now.isoformat(),'items':[], 'source_status':[], 'complete':True}
        with patch('paperpilot.hf_daily.utcnow',return_value=self.now),patch('paperpilot.hf_daily.collect',return_value=copy.deepcopy(value)) as collect:
            hf_daily.refresh(1);hf_daily.refresh(1);hf_daily.refresh(1,True)
            self.assertEqual(collect.call_count,1)
        later=self.now+timedelta(minutes=1)
        value.update(id='run2',updated_at=later.isoformat())
        with patch('paperpilot.hf_daily.utcnow',return_value=later),patch('paperpilot.hf_daily.collect',return_value=copy.deepcopy(value)) as collect:
            hf_daily.refresh(1,True);self.assertEqual(collect.call_count,1)
        tomorrow=self.now+timedelta(days=1)
        with patch('paperpilot.hf_daily.utcnow',return_value=tomorrow),patch('paperpilot.hf_daily.collect',return_value={**value,'id':'run3','dates':['2026-10-14']}) as collect:
            hf_daily.refresh(1);self.assertEqual(collect.call_count,1)

    def test_listing_favorites_and_abstracts_use_server_snapshot(self):
        paper={'id':'2610.00001','title':'Paper','abstract':'Original abstract','paper_url':'https://arxiv.org/abs/2610.00001'}
        store.save('hf_listing',{'id':'run','items':[paper]})
        with patch('paperpilot.providers.generate',side_effect=AssertionError('No model calls')):
            favorite=collections.save('hf-listing','run',paper['id'])
            self.assertEqual(abstracts.resolve('hf-listing','run',paper['id']),paper)
        self.assertEqual(favorite['paper'],paper)
        self.assertEqual(store.all_objects('paper'),[])
        with self.assertRaises(ValueError):collections.save('hf-listing','run','forged')
        with self.assertRaises(ValueError):abstracts.resolve('hf-listing','run','forged')

    def test_three_day_boundary_and_old_cache_requests_refresh(self):
        self.assertTrue(daily.recent(daily.window_start(self.now).isoformat(),self.now))
        self.assertFalse(daily.recent((daily.window_start(self.now)-timedelta(seconds=1)).isoformat(),self.now))
        store.save('daily',{'id':'latest','updated_at':self.now.isoformat(),'items':[],'source_status':[],'window_hours':48})
        with patch('paperpilot.daily.utcnow',return_value=self.now):
            self.assertTrue(daily.cached()['stale'])

    def test_endpoint_no_model_or_keyword_requirement(self):
        value={'id':'run','days':3,'dates':['2026-10-13','2026-10-12','2026-10-11'],'updated_at':self.now.isoformat(),'items':[], 'source_status':[], 'complete':True}
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        url=f'http://127.0.0.1:{server.server_port}/api/hf-list'
        try:
            with patch('paperpilot.hf_daily.collect',return_value=value),patch('paperpilot.hf_daily.utcnow',return_value=self.now),patch('paperpilot.providers.generate',side_effect=AssertionError('No model calls')):
                request=urllib.request.Request(url,json.dumps({'days':3}).encode(),{'Content-Type':'application/json','X-PaperPilot-Token':TOKEN})
                with urllib.request.urlopen(request) as response:
                    result=json.load(response)
            self.assertEqual(result['dates'],value['dates'])
            self.assertEqual(store.all_objects('discovery'),[])
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_invalid_ranges_rejected(self):
        for days in (0,2,4,'3',True,3.0,None):
            with self.assertRaises(ValueError):hf_daily.validate_days(days)


if __name__=='__main__':unittest.main()
