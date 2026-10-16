import {tooltipPosition,shortenHoverText} from './hover-labels.js';

// One host-owned listener set. A cancelled pointer/snapshot never publishes a
// delayed surface-query result. The sample may await the next normal render.
export function createHoverController({target,viewport,tooltip,canRead,sample,setTimer=setTimeout,clearTimer=clearTimeout,delay=260}){
 let timer=null,revision=0,destroyed=false,readAbort=null,pendingPoint=null;
 const listeners=[];
 function invalidate(){revision++;if(timer!==null)clearTimer(timer);timer=null;readAbort?.abort();readAbort=null;pendingPoint=null;tooltip.hidden=true;tooltip.replaceChildren();}
 function show(result,point){
  if(!result?.targets.length)return;
  const doc=tooltip.ownerDocument,rows=[];
  for(const target of result.targets){const row=doc.createElement('div');row.textContent=target.text;rows.push(row);tooltip.append(row);}
  tooltip.setAttribute('aria-label',result.targets.map(t=>t.text).join(' / ')+(result.otherCount?` / 他 ${result.otherCount} 件`:''));
  if(result.otherCount){const row=doc.createElement('div');row.className='hover-other';row.textContent=`他 ${result.otherCount} 件`;tooltip.append(row);}
  const rect=target.getBoundingClientRect(),bounds={left:Math.max(0,rect.left),top:Math.max(0,rect.top),right:Math.min(viewport.innerWidth,rect.right),bottom:Math.min(viewport.innerHeight,rect.bottom)};
  bounds.width=bounds.right-bounds.left;bounds.height=bounds.bottom-bounds.top;
  if(bounds.width<24||bounds.height<24)return;
  tooltip.style.maxWidth=`${Math.min(340,bounds.width-12)}px`;tooltip.hidden=false;
  for(const limit of [120,80,48,24]){if(tooltip.getBoundingClientRect().height<=bounds.height-12)break;rows.forEach((row,i)=>{row.textContent=shortenHoverText(result.targets[i].text,limit);});}
  const position=tooltipPosition(point,tooltip.getBoundingClientRect(),bounds);tooltip.style.left=`${position.left}px`;tooltip.style.top=`${position.top}px`;
 }
 function read(point,own){
  timer=null;if(destroyed||own!==revision)return;
  // Keep the stationary point for a later host readiness notification. Never
  // spin a render loop or drop it merely because the preceding pick dirtied depth.
  if(!canRead())return;
  pendingPoint=null;const abort=new AbortController();readAbort=abort;
  const finish=result=>{if(!destroyed&&own===revision&&!abort.signal.aborted&&canRead())show(result,point);};
  const fail=()=>{if(own===revision)invalidate();};
  const done=()=>{if(readAbort===abort)readAbort=null;};
  try{const result=sample(point,{signal:abort.signal});if(result&&typeof result.then==='function')Promise.resolve(result).then(finish).catch(fail).finally(done);else{finish(result);done();}}
  catch{fail();done();}
 }
 function arm(point){if(timer!==null||readAbort||!point)return;const own=revision;timer=setTimer(()=>read(point,own),delay);}
 function move(e){
  invalidate();
  if(destroyed||e.pointerType==='touch'||e.buttons||e.ctrlKey||e.altKey||e.shiftKey||e.metaKey)return;
  // Readiness is evaluated after the dwell, not at the last pointermove.
  pendingPoint={x:e.clientX,y:e.clientY};arm(pendingPoint);
 }
 function ready(){if(!destroyed&&pendingPoint&&canRead())arm(pendingPoint);}
 function listen(object,name,fn,options){object.addEventListener(name,fn,options);listeners.push(()=>object.removeEventListener(name,fn,options));}
 listen(target,'pointermove',move);
 for(const name of ['pointerdown','pointerup','pointerleave','pointercancel','lostpointercapture','wheel'])listen(target,name,invalidate,{passive:true});
 for(const name of ['blur','resize','scroll','keydown'])listen(viewport,name,invalidate,{passive:true});
 return {invalidate,ready,destroy(){if(destroyed)return;destroyed=true;invalidate();for(const remove of listeners)remove();}};
}
