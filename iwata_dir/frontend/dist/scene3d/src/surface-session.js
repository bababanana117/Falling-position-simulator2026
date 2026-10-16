// Own the lifetime/order of public surface queries, not the Viewer/provider.
// A screen-pick pass changes Cesium's default-view depth interpretation state.
// Do not start another position query until a normal postRender has completed.
export function createSurfaceSession(scene,{defer=queueMicrotask}={}){
 let dirty=false,disposed=false,scheduled=false,running=false,failed=false,failedFrame=false;
 const pending=[];
 const aborted=()=>new DOMException('Surface read cancelled','AbortError');
 function release(job){job.signal?.removeEventListener('abort',job.onAbort);}
 function settle(job,ok,value){if(job.done)return;job.done=true;release(job);(ok?job.resolve:job.reject)(value);}
 function schedule(){if(disposed||scheduled)return;scheduled=true;defer(()=>{scheduled=false;pump();});}
 function pump(){
  if(disposed||dirty||failed||running)return;
  while(pending.length&&!dirty&&!failed&&!disposed){
   const job=pending.shift();if(job.done)continue;if(job.signal?.aborted){settle(job,false,aborted());continue;}
   running=true;
   try{const value=job.reader();if(value&&typeof value.then==='function')throw new TypeError('Surface transaction must be synchronous');const cancelled=disposed||failed||job.signal?.aborted;settle(job,!cancelled,cancelled?aborted():value);}
   catch(error){settle(job,false,error);}finally{running=false;}
  }
 }
 const rejectPending=()=>{for(const job of pending.splice(0))settle(job,false,aborted());};
 const removeError=scene.renderError.addEventListener(()=>{if(disposed)return;failed=true;failedFrame=true;dirty=true;rejectPending();});
 const removeRender=scene.postRender.addEventListener(()=>{
  if(disposed)return;
  // Cesium can emit postRender even after its renderError. It is not a good frame.
  if(failedFrame){failedFrame=false;return;}
  failed=false;dirty=false;schedule();
 });
 return {
  isClean(){return !disposed&&!dirty&&!failed;},
  read(reader,{signal}={}){
   if(disposed||failed||signal?.aborted)return Promise.reject(aborted());
   return new Promise((resolve,reject)=>{
    const job={reader,signal,resolve,reject,done:false,onAbort:null};
    job.onAbort=()=>{const index=pending.indexOf(job);if(index!==-1)pending.splice(index,1);settle(job,false,aborted());schedule();};
    signal?.addEventListener('abort',job.onAbort,{once:true});pending.push(job);schedule();
   });
  },
  afterScreenPick(){if(disposed)return;dirty=true;scene.requestRender();},
  destroy(){if(disposed)return;disposed=true;removeRender();removeError();rejectPending();},
 };
}
