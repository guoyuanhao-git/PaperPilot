"""Opt-in real DeepSeek acceptance. At most 20 HTTP requests, memory-only key."""
import argparse
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def synthetic_pdf():
    from PIL import Image,ImageDraw
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    image=Image.new('RGB',(700,300),'white');draw=ImageDraw.Draw(image)
    for i in range(5):draw.ellipse((30+i*125,30,95+i*125,95),fill='orange')
    for i in range(2):draw.rectangle((150+i*280,180,230+i*280,260),fill='blue')
    out=io.BytesIO();pdf=canvas.Canvas(out,pagesize=(600,800));pdf.setTitle('Synthetic visual counting fixture')
    pdf.drawString(40,750,'Synthetic visual counting study; software fixture, not a real paper.')
    pdf.drawString(40,720,'Count the colored symbols from Figure 1; answers are not in the text.')
    pdf.drawString(40,690,'Equation S = A + B; this is an illustration, no empirical claims.')
    pdf.drawImage(ImageReader(image),40,350,width=500,height=215)
    pdf.drawString(40,325,'Figure 1. Colored objects for image understanding acceptance.')
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'));pdf.setFont('STSong-Light',12)
    pdf.drawString(40,290,'合成论文：根据图像识别颜色、形状和数量，不从正文猜测。');pdf.showPage()
    pdf.setFont('Helvetica',12);pdf.drawString(40,750,'Methods: inspect the embedded image. Limitations: synthetic fixture.')
    pdf.setFont('STSong-Light',12);pdf.drawString(40,700,'本材料不包含真实科研结论，仅用于软件验收。');pdf.save();return out.getvalue()



def validate_results(results):
    for label in ('connection','overview','image','context','recovery'):
        assert results.get(label,{}).get('status')=='completed', (label,results.get(label))
    assert results['report_saved']['present'] and results['report_saved']['sections']>=4
    assert '5' in results['image']['answer'] and '2' in results['image']['answer']
    assert '7' in results['context']['answer'] and 'DS7' in results['context']['answer']
    assert results['cancel']['status']=='cancelled'
    assert results['cancel']['old_messages_preserved'] and results['cancel']['old_report_preserved']
    assert results['persisted']['report'] and results['persisted']['messages']>=6


def main(port):
    from paperpilot import accounts,credentials,providers,store,service
    from paperpilot.server import Handler
    from paperpilot.model_setup import LocalClient
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f'http://127.0.0.1:{port}/api/session',timeout=5) as response:session=json.load(response)
    accounts.ROOT=store.DATA;user=accounts.entry(session['active'])
    if not user:raise ValueError('Current configured account not found')
    with store.scope(accounts.binding(user)):
        config=store.settings();secret=providers.api_key('deepseek')
    assert secret and config['provider']=='deepseek','Save DeepSeek configuration first'
    events=[];results={};lock=threading.Lock();original=providers._post_json
    def counted(url,body,key,timeout):
        with lock:
            if len(events)>=20:raise ValueError('DeepSeek acceptance budget exhausted (20)')
            event={'request':len(events)+1,'model':body.get('model'),'images':sum(1 for m in body.get('messages',[]) if isinstance(m.get('content'),list) for part in m['content'] if part.get('type')=='image_url'),'status':'running'}
            events.append(event)
        start=time.monotonic()
        try:
            response=original(url,body,key,timeout);event.update(status='returned',usage=response.get('usage',{}));return response
        except Exception as error:
            event.update(status='error',error_type=type(error).__name__);raise
        finally:
            event['elapsed_seconds']=round(time.monotonic()-start,2)
            print('HTTP_ATTEMPT',json.dumps(event,ensure_ascii=False),flush=True)
    providers._post_json=counted
    with tempfile.TemporaryDirectory(prefix='ppds-') as folder:
        store.DATA=Path(folder)/'中文 data';accounts.ROOT=None;accounts.initialize();accounts.create('dsaccept')
        with store.scope(accounts.binding(accounts.entry())):
            store.save_settings(copy.deepcopy(config));keyslot=providers.session_key('deepseek');providers.KEYS[keyslot]=secret
        secret='';credentials.CACHE.clear()
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        c=LocalClient(server.server_port,accounts.entry()['id'])
        def rawjob(ident):
            with opener.open(urllib.request.Request(c.url+'/api/job/'+ident,headers=c.headers),timeout=10) as response:return json.load(response)
        def wait(job,label):
            start=time.monotonic()
            while True:
                job=rawjob(job['id'])
                if job['status'] in ('completed','failed','cancelled'):break
                if time.monotonic()-start>600:raise TimeoutError('Acceptance job exceeded 600 seconds')
                time.sleep(.5)
            results[label]={'status':job['status'],'error':job.get('error'),'elapsed_seconds':round(time.monotonic()-start,2)}
            print('JOB',label,json.dumps(results[label],ensure_ascii=False),flush=True);return job
        def paper():return next(p for p in c.call('/api/bootstrap')['papers'] if p['id']==ident)
        try:
            print('CONFIG',json.dumps({'model':config['deepseek']['model'],'endpoint':config['deepseek']['base_url']},ensure_ascii=False),flush=True)
            wait(c.call('/api/test-provider',{}),'connection')
            req=urllib.request.Request(c.url+'/api/upload',data=synthetic_pdf(),headers={**c.headers,'Content-Type':'application/pdf','X-Filename':'synthetic.pdf'})
            with opener.open(req,timeout=30) as response:uploaded=json.load(response)
            ident=uploaded['id'];print('UPLOAD',uploaded['page_count'],len(uploaded['figures']),flush=True)
            wait(c.call('/api/analyze',{'id':ident,'mode':'overview'}),'overview')
            saved=paper();results['report_saved']={'present':bool(saved.get('report')),'sections':len((saved.get('report') or {}).get('sections',[]))}
            for label,question in [('image','请只依据图1图像数出橙色圆形和蓝色方形各几个，正文没有答案。答案末尾附标记 DS7。'),('context','根据你上一条的两个计数，总共几个？复述我上一条要求的标记。')]:
                wait(c.call('/api/chat',{'id':ident,'question':question}),label)
                messages=paper().get('messages',[])
                results[label]['answer']=messages[-1]['content'] if messages and messages[-1]['role']=='assistant' else None
                print('ANSWER',label,results[label]['answer'],flush=True)
            old=paper()
            js=r'''const {chromium}=require('playwright');(async()=>{const b=await chromium.launch();try{const p=await b.newPage();await p.goto(URL_VALUE,{waitUntil:'networkidle'});await p.locator('#open-paper-chat').click();await p.locator('#question').fill('请结合图1详细解释50种图像计数混淆情形，每种写一段。这是取消验收。');let response=p.waitForResponse(r=>r.url().endsWith('/api/chat')&&r.request().method()==='POST');await p.locator('#ask').click();console.log('JOB '+(await(await response).json()).id);await p.locator('#stop-paper-answer').waitFor();await p.waitForTimeout(500);await p.locator('#stop-paper-answer').click();await p.locator('#ask').waitFor();console.log('STOP_CLICKED')}finally{await b.close()}})().catch(e=>{console.error(e);process.exitCode=1});'''.replace('URL_VALUE',json.dumps(c.url+'/?paper='+ident+'&account='+accounts.entry()['id']))
            for attempt in range(2):
                run=subprocess.run(['node','-e',js],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=70)
                if run.returncode:results['cancel']={'status':'ui_failed','error':'Browser stop interaction failed'};break
                cancelid=run.stdout.split('JOB ')[1].splitlines()[0];cancelled=rawjob(cancelid)
                if cancelled['status']=='cancelled':
                    time.sleep(5);after=paper();results['cancel']={'status':'cancelled','old_messages_preserved':after.get('messages')==old.get('messages'),'old_report_preserved':after.get('report')==old.get('report')};break
            else:results['cancel']={'status':'not_captured'}
            print('CANCEL',json.dumps(results.get('cancel')),flush=True)
            wait(c.call('/api/chat',{'id':ident,'question':'取消测试结束。请只简短回答图中总共多少个对象。'}),'recovery')
            reopened=paper();results['persisted']={'report':reopened.get('report')==saved.get('report'),'messages':len(reopened.get('messages',[]))}
        finally:
            with store.scope(accounts.binding(accounts.entry())):
                for pending in store.all_objects('job'):
                    if pending['status'] in ('queued','running'):
                        if pending.get('kind')=='chat':service.cancel_chat(pending['id'])
                        elif pending.get('kind')=='analysis':service.cancel_analysis(pending['id'])
            server.shutdown();server.server_close();thread.join(timeout=5)
            # Allow late cancelled HTTP workers to finish/close before reporting.
            deadline=time.monotonic()+35
            while any(e['status']=='running' for e in events) and time.monotonic()<deadline:time.sleep(.2)
            providers.KEYS.pop(keyslot,None);providers._post_json=original
            print('FINAL_DEEPSEEK_ACCEPTANCE',json.dumps({'requests':len(events),'limit':20,'results':results,'http_attempts':events},ensure_ascii=False),flush=True)
    validate_results(results)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source-port',type=int,default=8766);parser.add_argument('--real',action='store_true',help='Explicitly authorize up to 20 paid requests')
    args=parser.parse_args()
    if not args.real:parser.error('--real is required for paid acceptance')
    main(args.source_port)
