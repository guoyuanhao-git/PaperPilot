let conferenceCleanup=null,conferenceMountRevision=0;
function disconnectConference(){conferenceMountRevision++;conferenceCleanup?.();conferenceCleanup=null;}
function applyWorkspaceNavigation(){
 const hidden=state.workspace?.hidden_modules||[];
 document.querySelectorAll('nav [data-view]').forEach(b=>b.hidden=hidden.includes(b.dataset.view));
 if(hidden.includes(view))view='library';
}
function workspaceSettings(){
 const hidden=state.workspace?.hidden_modules||[];
 return `<section class="panel workspace-modules"><h3>工作台模块</h3>${[['knowledge','知识库'],['hotspots','热点发现'],['conferences','会议日程']].map(([key,label])=>`<label>${label}<input type="checkbox" data-module="${key}" ${hidden.includes(key)?'':'checked'} aria-label="显示${label}"></label>`).join('')}<p class="workspace-save-status" id="workspace-save-status" role="status"></p></section>`;
}
function conferencesView(){return head('CONFERENCE SCHEDULE','会议日程','')+'<div id="conference-root"></div>'}
function bindWorkspace(){
 document.querySelectorAll('[data-module]').forEach(input=>input.onchange=async()=>{
  const inputs=[...document.querySelectorAll('[data-module]')];inputs.forEach(el=>el.disabled=true);
  try{state.workspace=await request('/api/workspace',{hidden_modules:inputs.filter(el=>!el.checked).map(el=>el.dataset.module)});applyWorkspaceNavigation();$('#workspace-save-status').textContent='已保存';}
  catch(e){input.checked=!input.checked;$('#workspace-save-status').textContent=e.message;}
  finally{inputs.forEach(el=>el.disabled=false);}
 });
 const host=$('#conference-root');if(!host||host.shadowRoot)return;
 const revision=conferenceMountRevision,account=state.accounts?.active,session=state.accounts?.revision;
 const scopedRequest=(...args)=>{if(account!==state.accounts?.active||session!==state.accounts?.revision||revision!==conferenceMountRevision)throw Error('页面已切换，请重新打开');return request(...args)};
 void import('/conferences/app.js').then(async module=>{
  if(revision!==conferenceMountRevision||!host.isConnected)return;
  const cleanup=await module.mount(host.attachShadow({mode:'open'}),{request:scopedRequest});
  if(revision===conferenceMountRevision&&host.isConnected)conferenceCleanup=cleanup;else cleanup?.();
 }).catch(e=>{if(host.isConnected)host.textContent=e.message;});
}
