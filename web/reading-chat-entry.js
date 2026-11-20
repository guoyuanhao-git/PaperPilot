/* A quiet entry into discussion, with a reading anchor across layout changes. */
(function(root){
 let observer,figuresObserver;
 const blocks=column=>[...column.querySelectorAll('h1,h2,h3,h4,p,li,figure,table,textarea')].filter(el=>!el.closest('figure,table,li')||el.matches('figure,table,li'));
 function capture(column,split){
  if(!column)return null;
  const top=split?column.getBoundingClientRect().top+16:24;
  const elements=blocks(column),index=elements.findIndex(el=>el.getBoundingClientRect().bottom>top);
  if(index<0)return null;
  const rect=elements[index].getBoundingClientRect();
  return {index,fraction:Math.max(0,(top-rect.top)/Math.max(1,rect.height)),offset:Math.max(0,rect.top-top),atStart:!split&&column.getBoundingClientRect().top>top};
 }
 function restore(column,snapshot,split){
  if(!column||!snapshot)return;
  const el=blocks(column)[snapshot.index];if(!el)return;
  if(split)window.scrollTo({top:0,behavior:'instant'});
  if(split&&snapshot.atStart){column.scrollTop=0;return;}
  const rect=el.getBoundingClientRect(),top=split?column.getBoundingClientRect().top+16:24;
  const delta=rect.top+rect.height*snapshot.fraction-top-snapshot.offset;
  if(split)column.scrollTop+=delta;
  else window.scrollTo({top:window.scrollY+delta,behavior:'instant'});
 }
 function disconnect(){observer?.disconnect();observer=null;figuresObserver?.disconnect();figuresObserver=null;for(const id of ['floating-paper-chat','floating-paper-figures']){const button=document.getElementById(id);if(button)button.hidden=true;}}
 function connectFigures(top,button,open){
  if(!top||!button)return;
  button.onclick=open;
  const update=()=>{button.hidden=!(top.isConnected&&top.getBoundingClientRect().bottom<=0)};
  figuresObserver=new IntersectionObserver(update,{threshold:0});figuresObserver.observe(top);update();
 }
 function connect(top,button,open){
  disconnect();if(!top||!button||top.getAttribute('aria-expanded')==='true')return;
  button.onclick=open;
  const update=()=>{button.hidden=!(top.isConnected&&top.getBoundingClientRect().bottom<=0)};
  observer=new IntersectionObserver(update,{threshold:0});observer.observe(top);update();
 }
 root.ReadingChatEntry={capture,restore,connect,connectFigures,disconnect};
})(globalThis);
