const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');

test('reader split: drag bounds, keyboard, per-account persistence and teardown',()=>{
 const data=new Map(),observers=[];
 const context={localStorage:{getItem:k=>data.get(k)??null,setItem:(k,v)=>data.set(k,v)},matchMedia:()=>({matches:false}),ReadingChatEntry:{capture:()=>({index:0}),restore:()=>{}},ResizeObserver:class{constructor(fn){this.fn=fn;observers.push(this)}observe(){}disconnect(){this.stopped=true}}};
 vm.createContext(context);vm.runInContext(fs.readFileSync('web/reader-split.js','utf8'),context);
 function workspace(){
  const attrs={},styles={};let captured;
  const handle={setAttribute:(k,v)=>attrs[k]=v,getAttribute:k=>attrs[k],focus:()=>{},setPointerCapture:id=>captured=id,hasPointerCapture:id=>captured===id,releasePointerCapture:()=>captured=null};
  const chat={scrollHeight:2000,scrollTop:1600,clientHeight:400};
  const el={clientWidth:1016,style:{setProperty:(k,v)=>styles[k]=v},querySelector:s=>s==='.reader-divider'?handle:s==='.chatmessages'?chat:{},getBoundingClientRect:()=>({left:0}),classList:{add(){},remove(){}}};
  return {el,handle,attrs,styles,chat};
 }
 let a=workspace();context.ReaderSplit.connect(a.el,'a');assert.equal(a.attrs['aria-valuenow'],61);
 a.handle.onpointerdown({button:0,pointerId:1,preventDefault(){}});
 a.handle.onpointermove({pointerId:1,clientX:900});assert.equal(a.attrs['aria-valuenow'],68);assert.ok(Math.abs(parseFloat(a.styles['--reader-left'])-680)<.01);
 a.handle.onpointerup();assert.ok(Math.abs(Number(data.get('paperpilot-reader-split:a'))-.68)<.001);
 const b=workspace();context.ReaderSplit.connect(b.el,'b');assert.equal(b.attrs['aria-valuenow'],61);assert.ok(observers[0].stopped);
 a=workspace();context.ReaderSplit.connect(a.el,'a');assert.equal(a.attrs['aria-valuenow'],68);
 a.handle.onkeydown({key:'Home',preventDefault(){}});assert.equal(a.attrs['aria-valuenow'],32);
 a.handle.onkeydown({key:'Enter',preventDefault(){}});assert.equal(a.attrs['aria-valuenow'],61);
 a.el.clientWidth=716;observers.at(-1).fn();assert.ok(parseFloat(a.styles['--reader-left'])<=420);
 context.ReaderSplit.connect(null,'a');assert.ok(observers.at(-1).stopped);
});
