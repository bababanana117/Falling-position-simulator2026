import {parseEgm96} from './vertical-datum.js';
import {groundNodes,groundKey,routeDefinitions} from './route-geometry.js';

let datum;
function loadDatum(){
 if(!datum)datum=fetch(new URL('../data/WW15MGH.DAC',import.meta.url)).then(r=>{if(!r.ok)throw new Error('Datum unavailable');return r.arrayBuffer();}).then(parseEgm96).catch(e=>{datum=null;throw e;});
 return datum;
}
// Own elevated display and finite ground queries; never creates a provider/viewer.
export function createRouteLayer(C,viewer,{session,exclusions,canSample,onState}){
 const source=new C.CustomDataSource('flight-routes');
 let routes=[],ground=new Map(),offset=null,extent=[],counts={},signature='',disposed=false,revision=0,abort=null,timer=null,busy=false,dirty=false,visible=true,curtain=true,datumError=false,nodeLimit=false,lastPass=null,cursor=0,retired=[];
 viewer.dataSources.add(source).then(()=>{if(disposed)viewer.dataSources.remove(source,true);});
 function report(){onState({...counts,busy,datumError,nodeLimit,lastPass,hasRoutes:routes.length>0,visible,curtain});}
 function show(){for(const item of source.entities.values)item.show=visible&&(item.properties.kind.getValue()!=='route-curtain'||curtain);viewer.scene.requestRender();}
 function render(){
  if(disposed)return;const next=routeDefinitions(C,routes,offset,ground);counts=next.counts;extent=next.extent;
  retired.push(...source.entities.values);
  source.entities.suspendEvents();try{source.entities.removeAll();for(const item of next.entities)source.entities.add(item);}finally{source.entities.resumeEvents();}show();report();
 }
 function cancel(){abort?.abort();abort=null;clearTimeout(timer);timer=null;}
 function schedule(){
  if(disposed||busy||timer!==null||!dirty||!visible||routes.every(r=>r.properties.altitudeMode==='absolute'))return;
  timer=setTimeout(()=>{timer=null;if(canSample())sample();},500);
 }
 async function sample(){
  if(disposed||busy||!canSample())return;dirty=false;busy=true;const own=revision,controller=new AbortController();abort=controller;
  // An unknown ground height cannot be culled using a fictitious zero-height
  // point (a visible mountain could then be omitted forever). Query a rotating
  // finite window instead; missing leading points cannot starve later nodes.
  const all=[...new Map(routes.filter(r=>r.properties.altitudeMode==='relativeToGround').flatMap(r=>r.nodes).map(p=>[groundKey(p),p])).values()];
  const start=all.length?cursor%all.length:0,points=[...all.slice(start),...all.slice(0,start)];
  const next=new Map(ground),started=performance.now();let queried=0,elapsed=0;
  report();
  try{
   // Revisit resolved nodes too: a closer view may supply a finer mesh LOD.
   // The cursor also reaches unresolved nodes after an all-missing first window.
   for(const p of points){
    if(controller.signal.aborted||own!==revision||!canSample())break;
    const value=await session.read(()=>{
     const start=performance.now();let height;
     try{height=viewer.scene.sampleHeight(C.Cartographic.fromDegrees(p[0],p[1]),[...exclusions(),...retired,...source.entities.values]);}
     finally{elapsed+=performance.now()-start;session.afterScreenPick();}
     return height;
    },{signal:controller.signal});
    queried++;if(Number.isFinite(value))next.set(groundKey(p),value);
    if(queried>=512||elapsed>=1200)break;
    // Yield between GPU readbacks so pointer/hover/click work can run first.
    await new Promise(resolve=>setTimeout(resolve,0));
   }
   if(!controller.signal.aborted&&own===revision&&!disposed){ground=next;cursor=all.length?(start+queried)%all.length:0;lastPass={queried,gpuMs:Math.round(elapsed),wallMs:Math.round(performance.now()-started),budgetReached:queried<points.length};render();}
  }catch(e){if(e?.name!=='AbortError'&&!disposed)lastPass={queried,failed:true};}
  finally{if(abort===controller)abort=null;busy=false;if(!disposed){report();if(dirty)schedule();}}
 }
 return {
  async setPayload(payload){
   const next=payload.geojson.features.map((f,index)=>({...f,index})).filter(f=>f.properties.kind==='flight-route');
   const key=JSON.stringify(next.map(f=>[f.properties,f.geometry]));
   if(key===signature){return;}signature=key;cancel();const own=++revision;routes=[];ground=new Map();offset=null;datumError=false;nodeLimit=false;cursor=0;lastPass=null;
   for(const f of next){let nodes;try{nodes=groundNodes(f.geometry.coordinates);}catch{nodes=[];nodeLimit=true;}const wall=payload.geojson.features.find(w=>w.properties.kind==='route-curtain'&&w.properties.candidateId===f.properties.candidateId&&w.properties.phase===f.properties.phase);routes.push({...f,nodes,fillOpacity:wall?.properties.fillOpacity??.22});}
   render();
   if(routes.some(r=>r.properties.altitudeMode==='absolute'))try{const model=await loadDatum();if(disposed||own!==revision)return;offset=model.heightOffset;render();}catch{if(disposed||own!==revision)return;datumError=true;report();}
   dirty=true;schedule();
  },
  visibility(routesVisible,curtainVisible){visible=routesVisible;curtain=curtainVisible;if(!visible){dirty=true;cancel();}show();report();if(visible)schedule();},
  changed(){if(disposed)return;dirty=true;schedule();},
  moving(){if(disposed)return;dirty=true;cancel();},
  refresh(){dirty=true;schedule();},
  ready(){if(disposed)return;if(viewer.dataSourceDisplay.ready)retired=[];if(canSample())schedule();},
  checkpoint(){return {routes,ground,offset,signature,cursor,datumError,nodeLimit,lastPass};},
  restore(state){
   if(!state||disposed)return;cancel();revision++;dirty=false;
   ({routes,ground,offset,signature,cursor,datumError,nodeLimit,lastPass}=state);render();
  },
  get extent(){return extent;},
  get entities(){return source.entities.values;},
  get pickExclusions(){return [...retired,...source.entities.values];},
  destroy(){disposed=true;revision++;cancel();viewer.dataSources.remove(source,true);},
 };
}
