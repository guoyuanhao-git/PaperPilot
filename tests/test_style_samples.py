import io
import json
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from reportlab.pdfgen import canvas
import test_core
from paperpilot import store, style_samples, reading
from paperpilot.server import Handler, TOKEN


def example_pdf():
    stream=io.BytesIO();c=canvas.Canvas(stream)
    c.drawString(40,750,'Example title');c.showPage()
    for i in range(5):
        c.drawString(40,750-i*20,'Explain the intuition first, then introduce notation and connect the equation to a worked example.')
    c.save();return stream.getvalue()


class StyleSamples(unittest.TestCase):
    def setUp(self):
        test_core.Core.setUp(self)
        def generate(config, system, messages, **kwargs):
            items=json.loads(messages[0]['content'])
            return {'value':{'rules':['先解释直觉。','结合例子说明。','逐步引入符号。','联系实现。','小结回顾。'],
                             'snippets':[{'source_id':items[0]['id'],'text':items[0]['excerpt'][:100]}]},
                    'provider':'fixture','model':'fixture','usage':{}}
        self.patcher=patch('paperpilot.providers.generate',side_effect=generate)
        self.patcher.start()

    def tearDown(self):
        deadline=time.monotonic()+5
        while any(j.get('status') in ('queued','running') for j in store.all_objects('job')) and time.monotonic()<deadline:
            time.sleep(.02)
        self.patcher.stop()
        test_core.Core.tearDown(self)

    def test_upload_extract_toggle_delete_and_limits(self):
        data=example_pdf()
        items=style_samples.upload(data,'../example.pdf')
        item=items[0]
        self.assertEqual(item['name'],'example.pdf')
        self.assertEqual(item['pages'],2)
        self.assertNotIn('excerpt',item)
        self.assertIn('Explain the intuition',reading.math_style_examples())
        self.assertEqual(len(style_samples.upload(data,'duplicate.pdf')),1)
        style_samples.change(item['id'],'enable',False)
        self.assertNotIn('Explain the intuition',reading.math_style_examples())
        self.assertIn('未提供启用',reading.math_style_examples())
        style_samples.change(item['id'],'enable',True)
        for i in range(2):style_samples.upload((str(i)+'A worked explanation. '*20).encode(),f'{i}.md')
        with self.assertRaisesRegex(ValueError,'最多保留'):style_samples.upload(b'Another explanation. '*20,'new.txt')
        path=style_samples.directory()/(item['id']+'.pdf')
        style_samples.change(item['id'],'delete')
        self.assertFalse(path.exists())
        for content,name in ((b'%PDF-invalid','bad.pdf'),(b'few words','short.txt'),(b'content'*30,'script.html')):
            with self.assertRaises(ValueError):style_samples.upload(content,name)
        self.assertEqual(len(style_samples.public()),2)

    def test_reads_beyond_page_twelve_and_keeps_short_example_complete(self):
        stream=io.BytesIO();c=canvas.Canvas(stream)
        for i in range(16):
            c.drawString(40,750,f'Page {i+1}: explain symbols with a worked example, then implementation.')
            c.showPage()
        c.save()
        value=style_samples.extract_details(stream.getvalue(),'.pdf')
        self.assertTrue(value['full_text'])
        self.assertIn('Page 16:',value['excerpt'])
        self.assertEqual(value['selected_pages'],list(range(1,17)))

    def test_long_example_covers_whole_document_with_priority_passages(self):
        sections=[(i+1, f'SECTION_{i+1} '+('ordinary prose. '*70)+'\nIntuition equation example implementation. '+str(i)) for i in range(50)]
        selected,total,full=style_samples.select_passages(sections)
        self.assertFalse(full);self.assertGreater(total,18000)
        self.assertLessEqual(sum(len(text) for _,text in selected),18000)
        positions=[n for n,_ in selected]
        self.assertEqual(min(positions),1);self.assertEqual(max(positions),50)
        self.assertTrue(any(20<=n<=30 for n in positions))
        self.assertTrue(any('Intuition equation' in text for _,text in selected))

    def test_upgrades_old_excerpts_from_owned_originals_once(self):
        item=style_samples.upload(('Opening. '*400+'Late implementation example. '*400).encode(),'old.md')[0]
        old=store.get('style_sample',item['id']);old.pop('extraction_version')
        old['excerpt']=old['excerpt'][:3000];store.save('style_sample',old)
        store.save('style_cache',{'id':'old','rules':[]})
        with patch('paperpilot.providers.generate',side_effect=AssertionError('No network during upgrade')):
            style_samples.upgrade()
        current=store.get('style_sample',item['id'])
        self.assertIn('Late implementation',current['excerpt'])
        self.assertTrue(current['full_text']);self.assertEqual(store.all_objects('style_cache'),[])
        with patch.object(style_samples,'extract_details',side_effect=AssertionError('Already upgraded')):
            style_samples.upgrade()

    def test_account_isolation_and_no_shared_directory_fallback(self):
        a=store.DATA/'alice';b=store.DATA/'bob'
        with store.scope({'directory':a}):
            store.init();style_samples.upload(b'Alice style. '*40,'alice.md')
            self.assertIn('Alice style',reading.math_style_examples())
        with store.scope({'directory':b}):
            store.init()
            with patch.object(store,'ROOT',a):style_samples.migrate()
            self.assertEqual(style_samples.public(),[])
            self.assertNotIn('Alice',reading.math_style_examples())
        with store.scope({'directory':a}):self.assertEqual(len(style_samples.public()),1)

    def test_legacy_migration_preserves_originals_and_does_not_restore_removed_sample(self):
        directory=store.DATA/'references';directory.mkdir()
        original=directory/'Example_教材式重写.pdf';original.write_bytes(example_pdf())
        style_samples.migrate();self.assertEqual(len(style_samples.public()),1)
        style_samples.change(style_samples.public()[0]['id'],'delete')
        style_samples.migrate();self.assertEqual(style_samples.public(),[])
        self.assertTrue(original.exists())

    def test_upload_and_management_http(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        def post(path,raw,headers=None):
            request=urllib.request.Request(f'http://127.0.0.1:{server.server_port}'+path,raw,{'X-PaperPilot-Token':TOKEN,**(headers or {})})
            with urllib.request.urlopen(request) as result:return json.load(result)
        try:
            result=post('/api/style-samples/upload',b'My example style. '*30,{'X-Filename':'example.md'})
            ident=result['items'][0]['id']
            result=post('/api/style-samples',json.dumps({'id':ident,'action':'enable','enabled':False}).encode())
            self.assertFalse(result['items'][0]['enabled'])
            self.assertEqual(post('/api/style-samples',json.dumps({'id':ident,'action':'delete'}).encode())['items'],[])
        finally:server.shutdown();server.server_close();worker.join()
