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
   if(view==='conferences'){
    const cards=page.locator('#cards .card');await cards.first().waitFor();
    if(await cards.count()!==13||await cards.locator('.rating').count()!==26)throw Error('Missing parallel conference ratings');
    if(await cards.locator('.direction-tag').count()!==13)throw Error('Missing direction tags');
    for(const card of await cards.all()){
     if(await card.locator('.direction-tag').innerText()!==await card.getAttribute('data-group'))throw Error('Direction tag lost');
    }
    const icra=page.locator('#cards [data-series="icra"]');
    if((await icra.locator('.rating').allTextContents()).join('|')!=='CCF-B|TH-A')throw Error('ICRA classifications incorrect');
    const corl=page.locator('#cards [data-series="corl"]');
    if((await corl.locator('.rating').allTextContents()).join('|')!=='CCF-N|TH-N')throw Error('Unlisted classification incorrect');
    await icra.locator('.rating').last().click();
    const detail=page.locator('#details');await detail.waitFor();
    const text=await detail.innerText();
    if(!text.includes('2019-08-13')||!text.includes('2026 · 第七版')||!text.includes('第 11 页'))throw Error('Missing classification provenance');
    await detail.locator('.close').click();
    await icra.locator('[data-focus]').click();
    await page.locator('#spotlight [data-focus="icra"][aria-pressed="true"]').waitFor();
    if((await page.locator('#spotlight .rating').allTextContents()).join('|')!=='CCF-B|TH-A')throw Error('Focused classifications missing');
    await page.screenshot({path:process.env.TEST_CONFERENCE_SCREENSHOT||process.env.TEST_SCREENSHOT+'.conferences.png',fullPage:true});
    await page.locator('#about').click();
    if(!(await page.locator('#ranking-sources').innerText()).includes('TH-CPL'))throw Error('Missing directory sources');
    await page.locator('#about-dialog .close').click();
    console.log('CONFERENCE_PARALLEL_RATINGS_AND_FOCUS_OK');
   }
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
  await page.evaluate(()=>window.scrollTo(0,document.body.scrollHeight));
  await page.locator('#floating-paper-figures').waitFor({state:'visible'});
  const readingY=await page.evaluate(()=>window.scrollY);
  await page.locator('#floating-paper-figures').click();
  await page.locator('[data-picker-crop]').first().click();
  await page.locator('#crop-dialog').waitFor();
  await page.locator('#cancel-crop').click();
  if(Math.abs(await page.evaluate(()=>window.scrollY)-readingY)>3)throw Error('Figure picker moved reading position');
  await page.locator('.report-crop').first().click();
  await page.locator('#crop-dialog').waitFor();
  const directY=await page.evaluate(()=>window.scrollY);
  await page.locator('#crop-caption').fill('当前位置修改图注');
  await page.locator('#save-crop').click();
  await page.locator('#crop-dialog').waitFor({state:'hidden'});
  if(Math.abs(await page.evaluate(()=>window.scrollY)-directY)>3)throw Error('Direct figure save moved reading position');
  await page.locator('#open-paper-chat').click();
  await page.locator('#open-paper-figures').click();
  await page.locator('#paper-figures-dialog').waitFor();
  await page.locator('#close-paper-figures').click();
  await page.locator('#close-paper-chat').click();
  console.log('IN_PLACE_FIGURE_PICKER_DIRECT_EDIT_AND_CHAT_LAYOUT_OK');
  const initialFigures=await page.locator('[data-remove-figure]').count();
  if(!initialFigures)throw Error('Missing removal control');
  const figureId=await page.locator('[data-crop]').first().getAttribute('data-crop');
  const cropButton=page.locator(`[data-crop="${figureId}"]`).first();
  async function saveCaption(expected,kind){
   const response=page.waitForResponse(r=>r.url().endsWith('/api/paper-update')&&r.request().method()==='POST');
   await page.locator('#save-crop').click();
   const saved=await (await response).json();
   const figure=saved.figures.find(f=>f.id===figureId),reported=saved.report.figures.find(f=>f.id===figureId);
   if(!figure||figure.caption!==expected||figure.kind!==kind||reported?.caption!==expected)throw Error('Caption identity not synchronized');
   if(saved.figures.length!==initialFigures)throw Error('Caption correction created another figure');
   await page.locator('#crop-dialog').waitFor({state:'hidden'});
   return figure;
  }
  await cropButton.click();await page.locator('#crop-mode-text').click();
  await page.locator('#crop-source-caption').fill('figure 10: Corrected caption.');
  await page.locator('#crop-caption').fill('手动填写的中文图注');
  let corrected=await saveCaption('figure 10: Corrected caption.','figure');
  if(corrected.caption_zh!=='手动填写的中文图注')throw Error('Manual Chinese lost');
  await cropButton.click();await page.locator('#crop-mode-text').click();
  // Select actual PDF text to correct the now-wrong Figure 10 without translating.
  const captionLine=page.locator('#crop-text-layer span').filter({hasText:'Figure 1.'}).first();
  await captionLine.waitFor();
  const original=await captionLine.evaluate(el=>{
   const range=document.createRange();range.selectNodeContents(el);
   const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);
   el.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));return el.textContent.trim();
  });
  if(!(await page.locator('#crop-caption-status').innerText()).includes('Figure 1'))throw Error('Selected label not detected');
  corrected=await saveCaption(original,'figure');
  if(corrected.caption_zh)throw Error('Old translation retained after changing source');
  await cropButton.click();await page.locator('#crop-mode-text').click();
  await page.locator('#crop-caption').fill('用户新输入的表注');
  await page.locator('#crop-source-caption').fill('Table 4 Corrected table caption');
  corrected=await saveCaption('Table 4 Corrected table caption','table');
  if(corrected.caption_zh!=='用户新输入的表注')throw Error('New manual Chinese overwritten');
  await cropButton.click();await page.locator('#crop-mode-text').click();
  await page.locator('#crop-source-caption').fill('Figure 99: Cancel this edit.');
  await page.locator('#cancel-crop').click();
  if(!(await cropButton.locator('..').locator('..').innerText()).includes('Table 4'))throw Error('Cancel changed saved label');
  console.log('CAPTION_SELECTION_RENUMBERS_WITHOUT_TRANSLATION_AND_PRESERVES_ID_OK');
  await page.locator('[data-remove-figure]').first().click();
  await page.locator('#cancel-storage-operation').click();
  if(await page.locator('[data-remove-figure]').count()!==initialFigures)throw Error('Cancel removed candidate');
  await page.locator('[data-remove-figure]').first().click();
  await page.locator('#confirm-remove-figure').click();
  await page.locator('#paper-storage-dialog').waitFor({state:'hidden'});
  if(await page.locator('[data-remove-figure]').count()!==initialFigures-1)throw Error('Candidate remained');
  if(!await page.locator('[data-export="pdf"]').count())throw Error('Candidate removal lost report');
  console.log('FIGURE_REMOVAL_CANCEL_AND_REPORT_PRESERVATION_OK');
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
