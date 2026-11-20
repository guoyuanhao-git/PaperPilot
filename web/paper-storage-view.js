let storageDialogRevision=0;
function paperMore(p){return `<details class="paper-more"><summary aria-label="论文更多操作" title="更多操作">⋯</summary><div class="paper-more-menu"><button class="textbtn" data-storage="${p.id}">${p.pdf_released?'恢复原文':'释放原文空间'}</button>${p.source_storage&&!p.pdf_released?`<button class="textbtn" data-storage="${p.id}" data-manual-restore="1">上传替换原文</button>`:''}${p.report?`<button class="textbtn" data-delete-report="${p.id}">删除阅读报告</button>`:''}<button class="textbtn danger" data-delete="${p.id}">移除论文</button></div></details>`}
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

function storageDialog(title,html){
 const dialog=$('#paper-storage-dialog');++storageDialogRevision;
 $('#paper-storage-title').textContent=title;
 $('#paper-storage-content').innerHTML=html;
 $('#close-paper-storage').disabled=false;
 $('#close-paper-storage').onclick=()=>dialog.close();
 dialog.oncancel=null;if(!dialog.open)dialog.showModal();return dialog;
}
function storageDialogBusy(dialog,value){
 $('#close-paper-storage').disabled=value;
 dialog.oncancel=value?e=>e.preventDefault():null;
 dialog.querySelectorAll('#paper-storage-content button,#paper-storage-content input').forEach(el=>el.disabled=value);
}
async function openDeleteReport(id){
 document.querySelectorAll('.paper-more[open]').forEach(el=>el.open=false);
 const paper=state.papers.find(p=>p.id===id);if(!paper?.report)return;
 const dialog=storageDialog('删除阅读报告','<p class="muted" role="status">正在检查…</p>');
 const revision=storageDialogRevision;
 try{
  const plan=await request('/api/paper-report-preview',{id});
  if(!dialog.open||revision!==storageDialogRevision)return;
  $('#paper-storage-content').innerHTML=`<p class="storage-paper-title">${esc(paper.title)}</p><p>删除当前阅读报告及其专用图片后，无法撤销。相关知识图谱可能引用了报告内容，因此会标记为“待更新”，现有图谱仍会保留。</p><p class="hint">保留原文、摘要、个人思考、对话、阅读状态和已导出的文件。需要时可重新生成报告。</p><p id="storage-operation-error" class="error" role="alert" hidden></p><div class="row storage-actions"><button id="confirm-delete-report" class="secondary danger">删除报告</button><button id="cancel-storage-operation" class="secondary">取消</button></div>`;
  $('#cancel-storage-operation').onclick=()=>dialog.close();
  $('#confirm-delete-report').onclick=async()=>{
   storageDialogBusy(dialog,true);
   try{
    const result=await request('/api/paper-report-delete',{id,revision:plan.revision});
    acceptPaperUpdate(result.paper);const position=ViewContinuity.capture($('#app'));
    dialog.close();render(position);toast(result.cleanup_pending?'报告已删除，部分图片未能清理':'阅读报告已删除');
   }catch(e){const error=$('#storage-operation-error');error.hidden=false;error.textContent=e.message}
   finally{storageDialogBusy(dialog,false)}
  };
 }catch(e){if(dialog.open&&revision===storageDialogRevision)$('#paper-storage-content').innerHTML=`<p class="error">${esc(e.message)}</p>`}
}
function openBatchStorage(mode='pdf'){
 const reports=mode==='report',previewLabel=reports?'查看待删除报告':'查看可释放空间';
 const papers=LibraryView.rows(state.papers,libraryTab).filter(p=>reports?Boolean(p.report):!p.pdf_released&&!p.metadata_only);
 const chosen=new Set();
 const dialog=storageDialog('批量管理',`<div class="batch-operation-options" role="group" aria-label="批量操作">${[['pdf','释放原文空间'],['report','删除阅读报告']].map(([value,label])=>`<button class="secondary" type="button" data-batch-operation="${value}" aria-pressed="${mode===value}">${label}</button>`).join('')}</div><div class="batch-storage-head"><label><input id="batch-storage-all" type="checkbox"> 全选当前列表</label><span id="batch-storage-count" class="small muted">已选 0 篇</span></div><div class="batch-storage-list">${papers.map(p=>`<label class="batch-storage-paper"><input type="checkbox" data-batch-storage="${p.id}"><span>${esc(LibraryView.title(p))}</span></label>`).join('')||`<p class="muted">${reports?'当前分类没有阅读报告。':'当前分类没有可释放的原文。'}</p>`}</div><p id="storage-operation-error" class="error" role="alert" hidden></p><div class="row storage-actions"><button id="preview-batch-storage" class="secondary" disabled>${previewLabel}</button><button id="cancel-storage-operation" class="secondary">取消</button></div>`);
 dialog.querySelectorAll('[data-batch-operation]').forEach(b=>b.onclick=()=>{if(b.dataset.batchOperation!==mode)openBatchStorage(b.dataset.batchOperation)});
 const update=()=>{$('#batch-storage-count').textContent=`已选 ${chosen.size} 篇`;$('#preview-batch-storage').disabled=!chosen.size;const all=$('#batch-storage-all');all.checked=!!papers.length&&chosen.size===papers.length;all.indeterminate=chosen.size>0&&!all.checked};
 const boxes=[...dialog.querySelectorAll('[data-batch-storage]')];
 boxes.forEach(el=>el.onchange=()=>{if(el.checked&&chosen.size>=100){el.checked=false;toast('每次最多选择 100 篇',true);return}el.checked?chosen.add(el.dataset.batchStorage):chosen.delete(el.dataset.batchStorage);update()});
 $('#batch-storage-all').onchange=e=>{chosen.clear();boxes.forEach((el,i)=>{el.checked=e.target.checked&&i<100;if(el.checked)chosen.add(el.dataset.batchStorage)});update()};
 $('#cancel-storage-operation').onclick=()=>dialog.close();
 $('#preview-batch-storage').onclick=async()=>{
  storageDialogBusy(dialog,true);$('#preview-batch-storage').textContent='正在检查…';
  try{
   const plan=await request(reports?'/api/paper-report-batch-preview':'/api/paper-storage-batch-preview',{ids:[...chosen]});
   const ready=plan.items.filter(p=>!p.error&&(reports||p.bytes>0)),other=plan.items.filter(p=>p.error||(!reports&&!p.bytes));
   const title=id=>papers.find(p=>p.id===id)?.title||id;
   $('#paper-storage-content').innerHTML=`${reports?`<div class="storage-space">将删除 <strong>${ready.length} 份报告</strong></div><p>删除所选阅读报告及其专用图片后，无法撤销。相关知识图谱可能引用了报告内容，因此会标记为“待更新”，现有图谱仍会保留。</p><p class="hint">保留原文、摘要、个人思考、对话、阅读状态和已导出文件。</p>`:`<div class="storage-space">${ready.length} 篇 · 预计释放 <strong>${storageSize(ready.reduce((sum,p)=>sum+p.bytes,0))}</strong></div><p>保留摘要、正文文字、报告及其图表、个人思考和对话。以后可自动下载或手动上传恢复原文。</p>`}<div class="batch-storage-list">${plan.items.map(p=>`<div class="batch-storage-result"><span>${esc(title(p.id))}</span><small class="${p.error?'error':'muted'}">${esc(p.error||(reports?'阅读报告':p.bytes>0?storageSize(p.bytes):'无可释放空间'))}</small></div>`).join('')}</div>${other.length?`<p class="hint">${other.length} 篇将跳过。</p>`:''}<p id="storage-operation-error" class="error" role="alert" hidden></p><div class="row storage-actions"><button id="confirm-batch-storage" class="secondary danger" ${ready.length?'':'disabled'}>${reports?'确认删除报告':'确认释放'}</button><button id="cancel-storage-operation" class="secondary">取消</button></div>`;
   storageDialogBusy(dialog,false);$('#confirm-batch-storage').disabled=!ready.length;
   $('#cancel-storage-operation').onclick=()=>dialog.close();
   $('#confirm-batch-storage').onclick=async()=>{
    storageDialogBusy(dialog,true);$('#confirm-batch-storage').textContent=reports?'正在删除…':'正在释放…';
    try{
     const result=await request(reports?'/api/paper-report-batch-delete':'/api/paper-storage-batch-release',{ids:ready.map(p=>p.id),...(reports?{revisions:Object.fromEntries(ready.map(p=>[p.id,p.revision]))}:{})});
     result.items.filter(p=>p.paper).forEach(p=>acceptPaperUpdate(p.paper));
     const position=ViewContinuity.capture($('#app'));render(position);
     const failed=result.items.filter(p=>p.error),ok=result.items.filter(p=>p.paper&&!p.error);
     $('#paper-storage-content').innerHTML=`${reports?`<div class="storage-space">已删除 <strong>${ok.length} 份报告</strong></div><p>原文、个人思考及阅读状态已保留。</p>${ok.some(p=>p.cleanup_pending)?'<p class="hint">部分专用图片未能清理。</p>':''}`:`<div class="storage-space">已释放 <strong>${storageSize(ok.reduce((sum,p)=>sum+p.freed_bytes,0))}</strong></div><p>${ok.length} 篇已完成，阅读成果已保留。</p>`}${failed.length?`<div class="batch-storage-list">${failed.map(p=>`<div class="batch-storage-result"><span>${esc(title(p.id))}</span><small class="error">${esc(p.error)}</small></div>`).join('')}</div>`:''}<div class="storage-actions"><button id="done-batch-storage" class="secondary">完成</button></div>`;
     $('#done-batch-storage').onclick=()=>dialog.close();
    }catch(e){const error=$('#storage-operation-error');error.hidden=false;error.textContent=e.message}
    finally{storageDialogBusy(dialog,false)}
   };
  }catch(e){storageDialogBusy(dialog,false);$('#preview-batch-storage').textContent=previewLabel;const error=$('#storage-operation-error');error.hidden=false;error.textContent=e.message}
 };
}

function openRemoveFigure(id,figureId){
 const paper=state.papers.find(p=>p.id===id),figure=paper?.figures.find(f=>f.id===figureId);
 if(!figure)return;
 const expected=JSON.parse(JSON.stringify(figure));
 const dialog=storageDialog('移除图表候选',`<p class="storage-paper-title">第 ${figure.page} 页 · ${esc(ReportView.caption(figure))}</p><p>此图表将从原文图表列表移除，后续生成解读时不再使用。原始 PDF、已有报告及导出文件保持不变。</p><p class="hint">误删后可通过“从原文页面添加图表”重新裁剪。</p><p id="storage-operation-error" class="error" role="alert" hidden></p><div class="row storage-actions"><button id="confirm-remove-figure" class="secondary danger">确认移除</button><button id="cancel-storage-operation" class="secondary">取消</button></div>`);
 $('#cancel-storage-operation').onclick=()=>dialog.close();
 $('#confirm-remove-figure').onclick=async()=>{
  storageDialogBusy(dialog,true);
  try{
   const updated=await request('/api/figure-remove',{id,figure_id:figureId,expected});
   acceptPaperUpdate(updated);const position=ViewContinuity.capture($('#app'));
   dialog.close();render(position);toast('图表候选已移除');
  }catch(e){const error=$('#storage-operation-error');error.hidden=false;error.textContent=e.message}
  finally{storageDialogBusy(dialog,false)}
 };
}
