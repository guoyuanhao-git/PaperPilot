let storageDialogRevision=0;
function paperMore(p){return `<details class="paper-more"><summary aria-label="论文更多操作" title="更多操作">⋯</summary><div class="paper-more-menu"><button class="textbtn" data-storage="${p.id}">${p.pdf_released?'恢复原文':'释放原文空间'}</button>${p.source_storage&&!p.pdf_released?`<button class="textbtn" data-storage="${p.id}" data-manual-restore="1">上传替换原文</button>`:''}<button class="textbtn danger" data-delete="${p.id}">移除论文</button></div></details>`}
function storageSize(bytes){return bytes<=0?'0 KB':bytes>=1048576?(bytes/1048576).toFixed(1)+' MB':Math.max(1,Math.round(bytes/1024))+' KB'}
async function openPaperStorage(id,manual=false){
 document.querySelectorAll('.paper-more[open]').forEach(el=>el.open=false);
 const revision=++storageDialogRevision;
 const paper=state.papers.find(p=>p.id===id);if(!paper)return;
 const restoring=paper.pdf_released||manual;
 const dialog=$('#paper-storage-dialog'),content=$('#paper-storage-content');
 $('#paper-storage-title').textContent=restoring?'恢复原文':'释放原文空间';
 content.innerHTML='<p class="muted" role="status">正在检查本地文件…</p>';dialog.showModal();
 $('#close-paper-storage').onclick=()=>dialog.close();
 try{
  const plan=restoring?null:await request('/api/paper-storage-preview',{id});
  if(!dialog.open||revision!==storageDialogRevision)return;
  const canDownload=restoring?paper.pdf_released&&Boolean(paper.source_storage?.restore_url):plan.can_download;
  content.innerHTML=`<p class="storage-paper-title">${esc(paper.title)}</p>${plan?`<div class="storage-space">预计释放 <strong>${storageSize(plan.bytes)}</strong></div><p>保留摘要、正文文字、阅读报告及其图表、个人思考、对话与知识图谱。</p><p class="hint">清理本地原始 PDF、整页图片、未被报告使用的图片缓存和导出临时文件。电脑中原来上传的文件不受影响。</p>`:'<p>恢复原文后可重新解读、查看全部图表和调整裁剪。可手动上传同一论文的新版本；已有报告继续使用原来的图表，新报告成功保存后会清理不再使用的旧图。</p>'}<p class="${canDownload?'hint':'storage-notice'}">${canDownload?'自动下载会核对原文件。手动上传可使用新版本，并优先保留你的选择。':'可手动上传此论文的 PDF，手动选择优先于自动下载。'}</p><p id="paper-storage-error" class="error" role="alert" hidden></p><div class="row storage-actions">${plan?'<button id="confirm-release-pdf" class="secondary danger">确认释放</button><button id="cancel-release-pdf" class="secondary">取消</button>':`${canDownload?'<button id="restore-source-pdf" class="secondary">自动下载原文</button>':''}<label class="secondary storage-upload">手动上传 PDF<input id="restore-source-upload" type="file" accept="application/pdf"></label>`}</div>`;
  const showError=e=>{const el=$('#paper-storage-error');if(el){el.hidden=false;el.textContent=e.message}};
  if(plan){
   $('#cancel-release-pdf').onclick=()=>dialog.close();
   if(plan.bytes<=0){$('#confirm-release-pdf').disabled=true;showError(new Error('保留报告图表后没有可释放空间，建议继续保留原文。'))}
   $('#confirm-release-pdf').onclick=async()=>{
    const button=$('#confirm-release-pdf');button.disabled=true;button.textContent='正在释放…';
    $('#close-paper-storage').disabled=true;$('#cancel-release-pdf').disabled=true;dialog.oncancel=e=>e.preventDefault();
    try{const result=await request('/api/paper-storage-release',{id});acceptPaperUpdate(result.paper);const position=ViewContinuity.capture($('#app'));dialog.close();render(position);toast('已释放 '+storageSize(result.freed_bytes)+'，阅读成果已保留')}
    catch(e){showError(e)}finally{button.disabled=false;button.textContent='确认释放';$('#close-paper-storage').disabled=false;$('#cancel-release-pdf').disabled=false;dialog.oncancel=null}
   };
  }else{
   if(canDownload)$('#restore-source-pdf').onclick=()=>guard(async()=>{dialog.close();await startJob('/api/paper-storage-restore',{id})});
   $('#restore-source-upload').onchange=async e=>{
    const input=e.target,file=input.files[0];if(!file)return;
    if(file.size>40*1024*1024){showError(new Error('最大支持 40 MB'));return}
    input.disabled=true;
    try{acceptPaperUpdate(await request('/api/upload',file,true,{'X-Paper-Id':id,'X-Restore-Mode':'manual','X-Filename':encodeURIComponent(file.name)}));const position=ViewContinuity.capture($('#app'));dialog.close();render(position);toast('已使用手动上传的 PDF，原有阅读成果已保留')}
    catch(e){showError(e)}finally{input.disabled=false;input.value=''}
   };
  }
 }catch(e){if(revision!==storageDialogRevision||!dialog.open)return;content.innerHTML=`<p class="error" role="alert">${esc(e.message)}</p>`}
}
document.addEventListener('click',event=>{document.querySelectorAll('.paper-more[open]').forEach(el=>{if(!el.contains(event.target))el.open=false})});
