"""Offline Windows product integration. Synthetic data; never calls a model."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
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
  await page.locator('#analyze').waitFor();
  if(await page.locator('#generate-presentation,#manage-ppt-samples,#ppt-samples-dialog').count())throw Error('Removed PPT controls remain');
  await page.locator('#manage-style-samples').click();
  await page.locator('#style-samples-dialog').waitFor();
  await page.locator('#close-style-samples').click();
  console.log('READER_REPORT_AND_MATH_STYLE_OK');
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


STORAGE_BROWSER = r"""
const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.PAPERPILOT_CHROME?{executablePath:process.env.PAPERPILOT_CHROME}:{})});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',r=>r.request().url().startsWith(process.env.TEST_URL)?r.continue():r.abort());
 try{
  await page.goto(process.env.TEST_URL,{waitUntil:'networkidle'});
  await page.locator('[data-paper]').first().click();
  await page.locator('.paper-more summary').click();
  await page.locator('[data-delete-report]').click();
  await page.locator('#cancel-storage-operation').click();
  if(!await page.locator('[data-export="pdf"]').count())throw Error('Cancel removed report');
  await page.locator('#back').click();
  await page.locator('#batch-storage').click();
  await page.locator('[data-batch-operation="report"]').click();
  await page.locator('#batch-storage-all').check();
  await page.locator('[data-batch-operation="pdf"]').click();
  if(!await page.locator('#preview-batch-storage').isDisabled())throw Error('Operation switch kept selection');
  await page.locator('[data-batch-operation="report"]').click();
  await page.locator('#batch-storage-all').check();
  await page.locator('#preview-batch-storage').click();
  await page.locator('#cancel-storage-operation').click();
  await page.locator('#batch-storage').click();
  await page.locator('[data-batch-operation="report"]').click();
  await page.locator('#batch-storage-all').check();
  await page.locator('#preview-batch-storage').click();
  await page.locator('#confirm-batch-storage').click();
  await page.locator('#done-batch-storage').click();
  await page.locator('[data-paper]').first().click();
  if(await page.locator('[data-export="pdf"]').count())throw Error('Report not removed');
  await page.locator('#analyze').waitFor();
  await page.locator('#back').click();
  await page.locator('#batch-storage').click();
  await page.locator('[data-batch-storage]').first().check();
  await page.locator('#preview-batch-storage').click();
  await page.locator('#confirm-batch-storage').waitFor();
  await page.screenshot({path:process.env.TEST_STORAGE_SCREENSHOT,fullPage:true});
  await page.locator('#cancel-storage-operation').click();
  await page.locator('#batch-storage').click();
  await page.locator('#batch-storage-all').check();
  await page.locator('#preview-batch-storage').click();
  await page.locator('#confirm-batch-storage').click();
  await page.locator('#done-batch-storage').click();
  await page.locator('[data-paper]').first().click();
  await page.getByText('原文已释放',{exact:true}).waitFor();
  if(errors.length)throw Error(JSON.stringify(errors));
  console.log('REPORT_DELETE_CANCEL_AND_BATCH_RELEASE_OK');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
"""


def main():
    if not sys.flags.utf8_mode:
        raise SystemExit('Run with python -X utf8 tests/verify_windows_product.py')
    with tempfile.TemporaryDirectory(prefix='paperpilot-product-') as tmp:
        os.environ['PAPERPILOT_DATA'] = str(Path(tmp) / '测试 data')
        from paperpilot import accounts, documents, exports, providers, store
        from paperpilot.server import Handler
        from test_core import pdf, report
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
                    info=exports.export(paper['id'],'pdf',print)
                    from pypdf import PdfReader
                    path=documents.directory(paper['id'])/'exports'/info['filename']
                    assert len(PdfReader(path).pages)>0
                    print('REAL_PDF_EXPORT_OK',flush=True)
                result = subprocess.run(['node', '-e', STORAGE_BROWSER], cwd=ROOT, env={**os.environ, 'TEST_URL':f'http://127.0.0.1:{server.server_port}', 'TEST_STORAGE_SCREENSHOT':os.environ.get('TEST_STORAGE_SCREENSHOT', str(Path(tmp)/'storage-preview.png'))}, capture_output=True, text=True, timeout=100)
                print(result.stdout, flush=True)
                if result.returncode:
                    raise RuntimeError(result.stderr)
                with store.scope(accounts.binding(accounts.entry())):
                    saved = store.all_objects('paper')[0]
                    assert saved['report'] is None and saved['pdf_released']
                    assert path.exists(), 'Existing exported PDF must remain'

        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)
    print('WINDOWS_PRODUCT_INTEGRATION_PASSED',flush=True)


if __name__ == '__main__':
    main()
