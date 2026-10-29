"""Offline Windows product integration. Synthetic data; never calls a model."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from http.server import ThreadingHTTPServer
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]

BROWSER = r'''
const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.PAPERPILOT_CHROME?{executablePath:process.env.PAPERPILOT_CHROME}:{})});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 const errors=[],bad=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('response',r=>{if(r.url().startsWith(process.env.TEST_URL)&&r.status()>=400)bad.push([r.status(),r.url()])});
 await page.route('**/*',route=>route.request().url().startsWith(process.env.TEST_URL)?route.continue():route.abort());
 try {
  await page.goto(process.env.TEST_URL,{waitUntil:'networkidle'});
  await page.locator('#first-user').click();
  await page.locator('#new-username').fill('synthetic_browser');
  await page.locator('#create-user-form').evaluate(form=>form.requestSubmit());
  await page.locator('#upload').waitFor();
  await page.locator('#upload').setInputFiles(process.env.TEST_PDF);
  await page.waitForFunction(()=>new URL(location.href).searchParams.has('paper')||document.querySelector('#upload')===null);
  await page.waitForTimeout(1000);
  await page.goto(process.env.TEST_URL,{waitUntil:'networkidle'});
  for(const view of ['library','knowledge','discover','conferences','profile','settings']){
   await page.locator(`button[data-view="${view}"]`).click();
   await page.waitForTimeout(350);
   console.log('VIEW_OK',view);
  }
  await page.screenshot({path:process.env.TEST_SCREENSHOT,fullPage:true});
  if(errors.length||bad.length)throw Error(JSON.stringify({errors,bad}));
  console.log('BROWSER_UPLOAD_NAVIGATION_ASSETS_OK');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
'''


def main():
    if not sys.flags.utf8_mode:
        raise SystemExit('Run with python -X utf8 tests/verify_windows_product.py')
    with tempfile.TemporaryDirectory(prefix='paperpilot-product-') as tmp:
        os.environ['PAPERPILOT_DATA'] = str(Path(tmp) / '测试 data')
        from paperpilot import accounts, documents, exports, presentations, presentation_samples, providers, store
        from paperpilot.server import Handler
        from test_core import pdf, report
        from test_presentations import slide
        accounts.initialize()
        fixture = Path(tmp) / '合成 paper.pdf'
        fixture.write_bytes(pdf())
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(providers, 'generate', side_effect=AssertionError('Unexpected real model call')):
                result = subprocess.run(['node', '-e', BROWSER], cwd=ROOT, env={**os.environ, 'TEST_URL':f'http://127.0.0.1:{server.server_port}', 'TEST_PDF':str(fixture), 'TEST_SCREENSHOT':str(Path(tmp)/'browser.png')}, capture_output=True, text=True, timeout=100)
                print(result.stdout, flush=True)
                if result.returncode:
                    raise RuntimeError(result.stderr)
                with store.scope(accounts.binding(accounts.entry())):
                    papers = store.all_objects('paper')
                    assert len(papers) == 1, papers
                    paper = papers[0]
                    assert paper['page_count'] == 2
                    paper.update(paper_type='research', report={**report(paper), 'mode':'detailed', 'figures':paper['figures']})
                    store.save('paper', paper)
                    deck = {'slides':[slide(),dict(slide(2),layout='equation',equation=r'\mathcal{L}=\|x-y\|^2',equation_meaning='合成公式'),dict(slide(3),layout='figure',figure_id=paper['figures'][0]['id'])], 'theme':presentation_samples.DEFAULT_THEME,'style_key':presentation_samples.snapshot()[0], 'coverage':'synthetic', 'calls':[], 'generated_at':'fixture', 'provider':'fixture'}
                    with patch.object(presentations, 'generate', return_value=copy.deepcopy(deck)):
                        info = exports.export(paper['id'],'pptx',print)
                    path = documents.directory(paper['id']) / 'exports' / info['filename']
                    with zipfile.ZipFile(path) as archive:
                        assert archive.testzip() is None
                        slides=[name for name in archive.namelist() if name.startswith('ppt/slides/slide') and name.endswith('.xml')]
                        assert len(slides)==3,slides
                        assert any(name.startswith('ppt/media/') for name in archive.namelist())
                        assert any(name.startswith('ppt/notesSlides/notesSlide') for name in archive.namelist())
                        import xml.etree.ElementTree as ET
                        for name in archive.namelist():
                            if name.endswith('.xml') or name.endswith('.rels'): ET.fromstring(archive.read(name))
                    print('REAL_PPTX_EXPORT_3_SLIDES_XML_MEDIA_NOTES_OK',flush=True)
                    info=exports.export(paper['id'],'pdf',print)
                    from pypdf import PdfReader
                    path=documents.directory(paper['id'])/'exports'/info['filename']
                    assert len(PdfReader(path).pages)>0
                    print('REAL_PDF_EXPORT_OK',flush=True)
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)
    print('WINDOWS_PRODUCT_INTEGRATION_PASSED',flush=True)


if __name__ == '__main__':
    main()
