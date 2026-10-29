/* Preserve reading position across an in-place render, never across navigation. */
(function(root){
 let stopSettling=()=>{};
 const scrollEntries=app=>[...app.querySelectorAll('[data-scroll-key]')];
 function scrollSnapshot(el){
  const box=el.getBoundingClientRect();
  const anchor=[...el.querySelectorAll('[data-view-anchor]')].find(child=>{
   const r=child.getBoundingClientRect();return r.bottom>box.top&&r.top<box.bottom;
  });
  return {x:el.scrollLeft,y:el.scrollTop,followEnd:el.dataset.scrollFollow==='end'&&el.scrollHeight-el.scrollTop-el.clientHeight<80,anchor:anchor?{key:anchor.dataset.viewAnchor,top:anchor.getBoundingClientRect().top-box.top}:null};
 }
 function detailEntries(app){
  const counts=new Map();
  return [...app.querySelectorAll('details:not([data-fold-key]):not([data-abstract-key]):not(.historical-import)')].map(el=>{
   const label=el.id||`${el.closest('[data-view-anchor]')?.dataset.viewAnchor||''}:${el.querySelector('summary')?.textContent}`;
   const n=counts.get(label)||0;counts.set(label,n+1);
   return [label+':'+n,el];
  });
 }
 function capture(app){
  stopSettling();
  const anchor=[...app.querySelectorAll('[data-view-anchor]')].find(el=>{
   if(el.closest('[data-scroll-key]'))return false;
   const r=el.getBoundingClientRect();return r.top<=120&&r.bottom>120;
  });
  const focused=app.contains(document.activeElement)?document.activeElement:null;
  return {
   x:window.scrollX,y:window.scrollY,
   anchor:anchor?{key:anchor.dataset.viewAnchor,top:anchor.getBoundingClientRect().top}:null,
   details:new Map(detailEntries(app).map(([key,el])=>[key,el.open])),
   images:new Map([...app.querySelectorAll('img')].filter(img=>img.naturalWidth&&img.naturalHeight).map(img=>[img.getAttribute('src'),img.naturalWidth+'/'+img.naturalHeight])),
   focus:focused?.id?{id:focused.id,start:focused.selectionStart,end:focused.selectionEnd}:null,
   scrolls:new Map(scrollEntries(app).map(el=>[el.dataset.scrollKey,scrollSnapshot(el)])),
  };
 }
 function restoreContent(app,snapshot){
  if(!snapshot)return;
  detailEntries(app).forEach(([key,el])=>{if(snapshot.details.has(key))el.open=snapshot.details.get(key)});
  // Reserve the same image proportions while the replacement DOM loads images.
  app.querySelectorAll('img').forEach(img=>{
   const ratio=snapshot.images.get(img.getAttribute('src'));
   if(ratio&&!img.style.aspectRatio)img.style.aspectRatio=ratio;
  });
 }
 function restorePosition(app,snapshot){
  if(!snapshot)return;
  const focus=snapshot.focus,el=focus&&document.getElementById(focus.id);
  if(el&&app.contains(el)&&!el.disabled){
   el.focus({preventScroll:true});
   if(typeof focus.start==='number'&&typeof el.setSelectionRange==='function')el.setSelectionRange(focus.start,focus.end);
  }
  scrollEntries(app).forEach(el=>{
   const saved=snapshot.scrolls?.get(el.dataset.scrollKey);if(!saved)return;
   const anchor=saved.anchor&&[...el.querySelectorAll('[data-view-anchor]')].find(child=>child.dataset.viewAnchor===saved.anchor.key);
   const y=anchor?el.scrollTop+anchor.getBoundingClientRect().top-el.getBoundingClientRect().top-saved.anchor.top:saved.y;
   el.scrollLeft=saved.x;el.scrollTop=saved.followEnd?el.scrollHeight:y;
  });
  const anchor=snapshot.anchor&&[...app.querySelectorAll('[data-view-anchor]')].find(el=>el.dataset.viewAnchor===snapshot.anchor.key);
  const y=anchor?window.scrollY+anchor.getBoundingClientRect().top-snapshot.anchor.top:snapshot.y;
  window.scrollTo({left:snapshot.x,top:y,behavior:'instant'});
 }
 function settleImages(app,snapshot){
  stopSettling();if(!snapshot)return;
  const images=[...app.querySelectorAll('img')].filter(img=>!img.complete);
  if(!images.length)return;
  let stopped=false,frame,timer;
  const first=app.firstElementChild;
  const stop=()=>{stopped=true;clearTimeout(timer);cancelAnimationFrame(frame);images.forEach(img=>{img.removeEventListener('load',loaded);img.removeEventListener('error',loaded)});['wheel','touchstart','pointerdown','keydown'].forEach(type=>window.removeEventListener(type,stop,true))};
  const loaded=()=>{
   if(stopped||app.firstElementChild!==first)return stop();
   cancelAnimationFrame(frame);
   frame=requestAnimationFrame(()=>{if(!stopped){restorePosition(app,{...snapshot,focus:null});if(images.every(img=>img.complete))stop()}});
  };
  images.forEach(img=>{img.addEventListener('load',loaded);img.addEventListener('error',loaded)});
  // New user input always takes precedence over a delayed image correction.
  ['wheel','touchstart','pointerdown','keydown'].forEach(type=>window.addEventListener(type,stop,{capture:true,passive:true}));
  timer=setTimeout(stop,5000);stopSettling=stop;
 }
 root.ViewContinuity={capture,restoreContent,restorePosition,settleImages};
})(globalThis);
