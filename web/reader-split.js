/* Resize the discussion workspace without rerendering reports or conversation. */
(function(root){
 let cleanup=()=>{};
 const DEFAULT=.608;
 function connect(workspace,account){
  cleanup();cleanup=()=>{};
  const handle=workspace?.querySelector('.reader-divider');
  if(!handle)return;
  const key='paperpilot-reader-split:'+String(account||'default');
  let ratio=DEFAULT,drag=null;
  try{const saved=Number(localStorage.getItem(key));if(saved>=.2&&saved<=.8)ratio=saved}catch{}
  const column=workspace.querySelector('.reading-column'),chat=workspace.querySelector('.chatmessages');
  function bounds(){
   const width=workspace.clientWidth-16;
   const minimum=Math.min(320,width*.4);
   return {width,min:minimum/width,max:1-minimum/width};
  }
  function apply(value=ratio){
   if(matchMedia('(max-width:700px)').matches)return;
   const {width,min,max}=bounds();if(width<=0)return;
   const actual=Math.max(min,Math.min(max,value));
   workspace.style.setProperty('--reader-left',`${width*actual}px`);
   handle.setAttribute('aria-valuemin',Math.round(min*100));
   handle.setAttribute('aria-valuemax',Math.round(max*100));
   handle.setAttribute('aria-valuenow',Math.round(actual*100));
   handle.setAttribute('aria-valuetext',`报告 ${Math.round(actual*100)}%，交流 ${100-Math.round(actual*100)}%`);
  }
  function save(){try{localStorage.setItem(key,String(ratio))}catch{}}
  function position(value){
   const {min,max}=bounds();ratio=Math.max(min,Math.min(max,value));apply();
  }
  function restore(anchor,bottom){
   ReadingChatEntry.restore(column,anchor,true);
   if(bottom&&chat)chat.scrollTop=chat.scrollHeight;
  }
  function finish(){
   if(!drag)return;
   const old=drag;drag=null;
   if(handle.hasPointerCapture(old.id))handle.releasePointerCapture(old.id);
   workspace.classList.remove('is-resizing');
   restore(old.anchor,old.bottom);save();
  }
  handle.onpointerdown=e=>{
   if(e.button!==0||matchMedia('(max-width:700px)').matches)return;
   e.preventDefault();handle.focus({preventScroll:true});
   drag={id:e.pointerId,anchor:ReadingChatEntry.capture(column,true),bottom:chat&&chat.scrollHeight-chat.scrollTop-chat.clientHeight<40};
   handle.setPointerCapture(e.pointerId);workspace.classList.add('is-resizing');
  };
  handle.onpointermove=e=>{
   if(!drag||e.pointerId!==drag.id)return;
   position((e.clientX-workspace.getBoundingClientRect().left-8)/bounds().width);
   restore(drag.anchor,drag.bottom);
  };
  handle.onpointerup=handle.onpointercancel=handle.onlostpointercapture=finish;
  handle.ondblclick=()=>{const anchor=ReadingChatEntry.capture(column,true);ratio=DEFAULT;apply();restore(anchor,false);save()};
  handle.onkeydown=e=>{
   if(!['ArrowLeft','ArrowRight','Home','End','Enter'].includes(e.key))return;
   e.preventDefault();const anchor=ReadingChatEntry.capture(column,true),b=bounds();
   const current=Number(handle.getAttribute('aria-valuenow'))/100;
   position(e.key==='Home'?b.min:e.key==='End'?b.max:e.key==='Enter'?DEFAULT:current+(e.key==='ArrowLeft'?-1:1)*(e.shiftKey?.1:.02));
   restore(anchor,false);save();
  };
  const observer=new ResizeObserver(()=>apply());observer.observe(workspace);apply();
  cleanup=()=>{finish();observer.disconnect()};
 }
 root.ReaderSplit={connect};
})(globalThis);
