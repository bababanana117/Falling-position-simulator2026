import {SCHEMA,validatePayload,receipt} from './protocol.js';
import {fitBoundsDistance,MAX_INSPECTION_DISTANCE} from './camera-fit.js';
import * as initialOverlay from './overlays.js';
import * as initialCatalog from './catalog.js';
import {createOverlayStore} from './overlay-store.js';
import {createRouteLayer} from './route-layer.js';
import {readBand,createClickTracker} from './band-readout.js';
import {resolveHover} from './hover-labels.js';
import {createHoverController} from './hover-controller.js';
import {pickSurface,pickedNameBoundaryIndices} from './surface-pick.js';
import {createSurfaceSession} from './surface-session.js';
import {credentialFromInput,publicFailure,googleTiles} from './provider.js';
import {normalizeSceneColor} from './colors.js';
import {fixture} from './fixture.js';
import {createViewMemory} from './view-memory.js';
import {createViewStability,publicViewPose} from './view-stability.js';
const C=window.Cesium,$=id=>document.getElementById(id),map=$('map');
const syntheticProbe=parent===window&&new URLSearchParams(location.search).get('probe')==='synthetic';
const viewMemory=createViewMemory(C);
const viewStability=createViewStability();
const diag=window.SCENE3D_DIAGNOSTICS={schema:SCHEMA,hostRevision:'0.55.0-continuous-route-curtain',engine:'CesiumJS 1.145.0',initialized:false,provider:'none',googleConnected:false,connection:'disconnected',projectionObserved:false,errors:[],cameraMoves:0,rootRequestAttempts:0,rootCounterMeaning:'Explicit application root-load attempts in this iframe; not total HTTP requests or confirmed billable events',paused:false};
let routeLayer,surfaceSession,clickReadAbort=null,clickReadRevision=0;
let viewer,tileset,payload,renderedPayload,readoutMarker,overlayStore,overlayModule=initialOverlay,catalogModule=initialCatalog,renderRevision=0,presentationError=null,previousPresentation=null,intentPending=null,intentSerial=0,intentTimer=null,presentationUpdating=false,epoch=0,receiveError=null,visibleFrame=0,loaded=0,failed=0,pending=0,processing=0,connectedAt=0,lastCamera='',entityItems=[],connecting=false;
const hover=createHoverController({target:map,viewport:window,tooltip:$('surfaceHover'),canRead:()=>{
 if(!viewer||!tileset||!viewer.dataSourceDisplay.ready||!renderedPayload||renderedPayload!==payload||diag.paused||presentationUpdating||presentationError||receiveError)return false;
 const now=performance.now();if(viewStability.observe(publicViewPose(viewer.camera),now)){hover.invalidate();cancelClickRead();}
 return viewStability.ready(now);
},sample:(point,{signal})=>{
 const session=surfaceSession,shown=renderedPayload;
 return session.read(()=>{
  if(session!==surfaceSession||shown!==renderedPayload||shown!==payload)return null;
  const surface=pickSurface(C,viewer.scene,point,[...(overlayStore?.pickExclusions||[]),...(routeLayer?.pickExclusions||[]),...(readoutMarker?[readoutMarker]:[])],session);
  if(!surface)return null;
  const linesVisible=$('showLines').checked;
  const indices=linesVisible?pickedNameBoundaryIndices(viewer.scene,surface.screen,overlayStore?.items||[],session):[];
  return resolveHover(shown,surface.point,{bandsVisible:$('showBands').checked,regionsVisible:$('showRegions').checked,linesVisible,lineFeatureIndices:indices});
 },{signal});
}});

function post(type,fields={}){if(parent!==window)parent.postMessage({type,schema:SCHEMA,snapshotId:payload?.snapshotId,...fields},location.protocol==='file:'?'*':location.origin);}
function originAllowed(e){return e.source===parent&&(location.protocol==='file:'?e.origin==='null':e.origin===location.origin);}
function status(text){$('status').textContent=receiveError||presentationError||text;}
function background(state,text){diag.connection=state;$('backgroundStatus').dataset.state=state;$('backgroundStatus').textContent=text;updateConnectionLayout();}
function updateConnectionLayout(){
 $('connection').hidden=syntheticProbe;
 $('keyEntry').hidden=connecting||(!!tileset&&['loading','visible','partial'].includes(diag.connection));
 $('connectionState').textContent=connecting?'接続処理中（解除で中断）':tileset?(['error','unavailable'].includes(diag.connection)?'接続を保持中・再接続は解除後':'接続を保持中'):'未接続';
}
function updateConnectButton(){$('connect').disabled=connecting||!!tileset||!payload||!!receiveError;}
function updateViewMemoryUI(message){const mismatch=!!renderedPayload&&renderedPayload.collectionKey!==payload?.collectionKey;$('rememberView').disabled=!viewer||!tileset||mismatch;$('recallView').disabled=!viewer||!tileset||mismatch||!viewMemory.has();diag.viewRemembered=viewMemory.has();if(message)$('viewMemoryStatus').textContent=message;}
function failure(error){const safe=publicFailure(error);diag.errors.push(safe);background('error',safe.text);status(safe.text);}
function destroyView(){hover.invalidate();routeLayer?.destroy();routeLayer=null;surfaceSession?.destroy();surfaceSession=null;viewStability.clear();diag.cameraEventMoving=false;clearReadout('接続後、地物をクリックして注目候補の輪郭区分を読みます。');++epoch;++renderRevision;connecting=false;tileset=null;entityItems=[];overlayStore?.destroy();overlayStore=null;previousPresentation=null;if(viewer){viewer.destroy();viewer=undefined;}map.replaceChildren();diag.initialized=false;diag.googleConnected=false;diag.provider='none';$('disconnect').hidden=true;updateConnectButton();updateViewMemoryUI();}
$('back').hidden=true;
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&parent!==window)post('bjp-scene3d-close');});
$('disconnect').onclick=()=>{destroyView();background('disconnected','接続を解除しました。キーの再入力で接続できます。');status('Googleには接続していません。受領した同じ結果は保持しています。');};
function resetCamera(){const target=renderedPayload||payload;if(!viewer||!target)return;const distance=fitBoundsDistance(target.camera.bounds,target.camera.center,{width:map.clientWidth,height:map.clientHeight,fov:C.Math.toDegrees(viewer.camera.frustum.fovy),pitch:-48});diag.initialViewport={width:map.clientWidth,height:map.clientHeight,fov:C.Math.toDegrees(viewer.camera.frustum.fovy),distance};viewer.camera.lookAt(C.Cartesian3.fromDegrees(...target.camera.center),new C.HeadingPitchRange(0,C.Math.toRadians(-48),distance));viewer.camera.lookAtTransform(C.Matrix4.IDENTITY);viewer.scene.requestRender();}
$('reset').onclick=resetCamera;
$('fitRoute').onclick=()=>{const points=routeLayer?.extent;if(!viewer||!points?.length)return;const sphere=C.BoundingSphere.fromPoints(points),frustum=viewer.camera.frustum,half=Math.min(frustum.fovy,2*Math.atan(Math.tan(frustum.fovy/2)*map.clientWidth/Math.max(1,map.clientHeight)))/2,range=Math.max(30,1.12*sphere.radius/Math.sin(half));viewer.camera.lookAt(sphere.center,new C.HeadingPitchRange(0,C.Math.toRadians(-40),range));viewer.camera.lookAtTransform(C.Matrix4.IDENTITY);viewer.scene.requestRender();};
$('refreshGround').onclick=()=>routeLayer?.refresh();
function routeState(s){
 diag.routeDisplay=s;$('routeReceipt').textContent=JSON.stringify({...s,camera:diag.camera,rootRequestAttempts:diag.rootRequestAttempts},null,2);
 $('fitRoute').disabled=!routeLayer?.extent?.length;$('refreshGround').hidden=!s.requiresGround;$('refreshGround').disabled=!s.hasRoutes||s.busy||!s.visible;
 $('routeStatus').textContent=!s.hasRoutes?'注目した可視候補の経路を表示します。':s.datumError?'高度基準を読めず、空中軌道を表示できません。ローカルのEGM96データを確認してください。':!s.visible?'軌道と地表投影線は非表示です。':s.requiresGround?(s.nodeLimit?'人工AGLの模式軌道は表示節点の上限を超えたため保留しています。実ASLの全経路表示とは別の制限です。':s.resolved<s.nodes?'人工AGLの模式軌道は、上端の地物高さが揃うまで表示を保留します。実結果のASL軌道にはこの待機はありません。':'人工AGLの模式軌道と地表投影線を表示しています。'):'上昇・下降の軌道と地表線を一組で表示。カーテンは全経路の上下関係を示します。';
}

$('rememberView').onclick=()=>{if(!$('rememberView').disabled&&viewer&&tileset&&viewMemory.remember(viewer.camera))updateViewMemoryUI('この視点を覚えました');};
$('recallView').onclick=()=>{if(!$('recallView').disabled&&viewer&&tileset&&viewMemory.restore(viewer.camera)){viewer.scene.requestRender();updateViewMemoryUI('覚えた視点へ戻りました');}};
function visibilityFor(item){const kind=item.properties?.kind?.getValue?.()??item.properties?.kind;if(kind==='mean-route')return $('showRoutes').checked;if(kind==='contour-band')return $('showBands').checked;if(kind==='region'&&item.polygon)return $('showRegions').checked;return item.point?$('showPoints').checked:$('showLines').checked;}
function applyVisibility(){hover.invalidate();for(const item of overlayStore?.items||[])item.show=visibilityFor(item);routeLayer?.visibility($('showRoutes').checked,$('showCurtain').checked);$('showCurtain').disabled=!$('showRoutes').checked;viewer?.scene.requestRender();}
for(const id of ['showPoints','showLines','showRegions','showBands'])$(id).onchange=applyVisibility;
for(const id of ['showRoutes','showCurtain'])$(id).onchange=()=>{applyVisibility();post('bjp-scene3d-route-display',{baseSnapshotId:payload?.snapshotId,visible:$('showRoutes').checked,curtain:$('showCurtain').checked});};
function updateCatalog(){if(renderedPayload)$('candidates').replaceChildren(catalogModule.catalogView(document,renderedPayload,sendIntent,{busy:!!intentPending||!!presentationError||renderedPayload!==payload,embedded:parent!==window}));}
function sendIntent(action,candidateId,value){
 if(!payload||payload.context.kind==='detail'||parent===window||intentPending||presentationError||renderedPayload!==payload)return;
 const candidate=payload.candidates.find(c=>c.candidateId===candidateId);if(!candidate?.available)return;
 const requestId=`scene-intent-${++intentSerial}`;intentPending={requestId,baseSnapshotId:payload.snapshotId};
 $('intentStatus').textContent='分析画面に反映中…';updateCatalog();
 post('bjp-scene3d-intent',{baseSnapshotId:payload.snapshotId,requestId,action,candidateId,...(action==='visibility'?{value}:{} )});
 intentTimer=setTimeout(()=>{if(intentPending?.requestId===requestId){intentPending=null;updateCatalog();$('intentStatus').textContent='応答を確認できません。再入場で最新の状態を取得できます。自動再送はしません。';}},7000);
}
function acknowledge(message){if(!intentPending||message.requestId!==intentPending.requestId)return;clearTimeout(intentTimer);intentPending=null;updateCatalog();$('intentStatus').textContent=message.accepted?'2Dと同じ状態へ反映しました。':'状態が変わったため反映しませんでした。最新の一覧で操作してください。';diag.lastIntent={requestId:message.requestId,accepted:message.accepted===true,currentSnapshotId:message.currentSnapshotId,reason:typeof message.reason==='string'?message.reason.slice(0,120):null};}
function updateSummary(next){
 $('showRoutes').checked=next.routeDisplay?.visible!==false;$('showCurtain').checked=next.routeDisplay?.curtain!==false;$('showCurtain').disabled=!$('showRoutes').checked;
 $('title').textContent=next.title||'表示中の結果';
 const detail=next.context.kind==='detail',shown=next.candidates.filter(c=>c.visible&&c.available).length;
 $('dataOrigin').textContent=next.artificial?'人工結果の操作模型':'保存GFSの固定実結果';$('showBands').disabled=!next.geojson.features.some(f=>f.properties.kind==='contour-band');
 $('contextSummary').textContent=detail?`選択 ${next.context.selection.count}/${next.context.selection.denominator} ${next.artificial?'着地':'実記録'}・輪郭なし`:`${shown}/${next.candidates.length}候補を表示 · 既存候補の注目・表示は2Dへ継続`;
 $('catalogSummary').textContent=detail?'現在の選択群':'候補と遅延系列';
 $('bandContext').textContent=catalogModule.bandLegend(next);
 $('bandSwatches').hidden=detail||!next.geojson.features.some(f=>f.properties.kind==='contour-band');
 const focus=next.candidates.find(c=>c.focused);$('bandSwatches').style.setProperty('--band-color',normalizeSceneColor(focus?.color)||'#34c9ff');
 for(const [level,id] of [[.5,'band50'],[.9,'band90'],[.95,'band95']]){const band=next.geojson.features.find(f=>f.properties.kind==='contour-band'&&f.properties.level===level);$(id).hidden=!band;if(band)$(id).style.setProperty('--band-alpha',band.properties.fillOpacity);}
 $('definition').textContent=!next.artificial?'固定実結果の着地・停止点と相別の空中軌道・地表投影。実高度ASLは表示時にEGM96で楕円体高へ変換します。集合の輪郭は全着地の経験被覆、経路は同経過時刻の平均です。位置のない試行は母数に残り、地図点を持ちません。経路線は接触を表しません。':detail?`現在選択した ${next.context.selection.count}/${next.context.selection.denominator} 着地と、選択群の平均経路を確認します。全体輪郭は表示せず、空中経路の高度は人工の模式AGLです。` :next.candidates.filter(c=>c.focused).map(c=>`${c.label||c.candidateId}：${typeof c.probabilityDefinition==='string'?c.probabilityDefinition:JSON.stringify(c.probabilityDefinition??'未指定')}`).join(' / ');
 $('notes').textContent=(next.notes||[]).map(n=>typeof n==='string'?n:JSON.stringify(n)).join(' ');
 $('legend').textContent=(!next.artificial?'固定結果の軌道と終了点。集合の50/90/95%は経験被覆、点・線に退化した場合は面積を付けません。':detail?'選択した着地点とその平均経路。': '太線50% · 中線90% · 細線95%。面の濃淡は確率密度ではありません。')+' 禁止領域はレベルの色。屋根上の表示は捕捉・衝突予測ではありません。';
}
async function installPresentation(next,renderer=overlayModule,catalog=catalogModule,css=null,reset=false){
 hover.invalidate();
 const serial=++renderRevision,host=viewer,store=overlayStore;
 let prepared,committed=false;
 try{
  // Prepare complete definitions and detached catalog before modifying current display.
  let dom=catalog.catalogView(document,next,sendIntent,{busy:!!intentPending,embedded:parent!==window});
  $('showRoutes').checked=next.routeDisplay?.visible!==false;$('showCurtain').checked=next.routeDisplay?.curtain!==false;
  const definitions=renderer.overlayEntities(C,next);
  if(store){prepared=await store.prepare(definitions);for(const item of prepared.items)item.show=visibilityFor(item);}
  if(serial!==renderRevision||payload!==next||viewer!==host){if(prepared)store.discard(prepared);css?.remove();return false;}
  dom=catalog.catalogView(document,next,sendIntent,{busy:!!intentPending,embedded:parent!==window});
  const oldCss=document.getElementById('presentationStyle');
  const old={routes:routeLayer?.checkpoint(),renderer:overlayModule,catalog:catalogModule,dom:Array.from($('candidates').childNodes),css:oldCss,newCss:css,payload:renderedPayload,diagnostics:Object.fromEntries(['snapshot','renderedSnapshotId','renderedEntities','overlayKinds','presentation','geometrySha256','overlayReady'].map(k=>[k,structuredClone(diag[k])]))};
  if(prepared)store.commit(prepared);committed=true;
  if(previousPresentation?.newCss&&previousPresentation.css!==oldCss)previousPresentation.css?.remove();
  previousPresentation=old;
  if(css){oldCss.id='previousPresentationStyle';oldCss.media='not all';css.id='presentationStyle';css.media='all';}
  overlayModule=renderer;catalogModule=catalog;$('candidates').replaceChildren(dom);updateSummary(next);
  clearReadout('表示を更新しました。地物をクリックして注目候補の輪郭区分を読みます。');renderedPayload=next;entityItems=store?.items||[];diag.snapshot=receipt(next);$('receipt').textContent=JSON.stringify(diag.snapshot,null,2);diag.renderedEntities=definitions.length;diag.overlayKinds=diag.snapshot.featureCounts;diag.renderedSnapshotId=next.snapshotId;recordRenderedGeometry(next);
  diag.presentation={overlay:renderer.PRESENTATION_REVISION,catalog:catalog.PRESENTATION_REVISION,appliedAt:new Date().toISOString(),updates:diag.presentation?.updates||0};
  presentationError=null;diag.presentationError=null;updateViewMemoryUI();
  await routeLayer?.setPayload(next);if(serial!==renderRevision||payload!==next||renderedPayload!==next||viewer!==host||presentationError)return false;routeLayer?.visibility($('showRoutes').checked,$('showCurtain').checked);
  if(reset&&viewer)resetCamera();viewer?.scene.requestRender();
  status(`同じ結果を表示：${next.geojson.features.length}表示要素。`);return true;
 }catch(error){if(committed)restorePreviousPresentation();else if(prepared)store?.discard(prepared);css?.remove();presentationError='表示更新に失敗しました。旧表示・視点・接続を保持しています。';diag.presentationError='presentation-prepare';updateCatalog();updateViewMemoryUI();status('');return false;}
}
function restorePreviousPresentation(){
 hover.invalidate();
  if(!previousPresentation)return false;if(overlayStore&&!overlayStore.rollback())return false;++renderRevision;
 const old=previousPresentation;overlayModule=old.renderer;catalogModule=old.catalog;$('candidates').replaceChildren(...old.dom);
 if(old.newCss){old.newCss.remove();old.css.id='presentationStyle';old.css.media='all';}
 renderedPayload=old.payload;routeLayer?.restore(old.routes);Object.assign(diag,old.diagnostics);entityItems=overlayStore?.items||[];if(renderedPayload){updateSummary(renderedPayload);applyVisibility();$('receipt').textContent=JSON.stringify(diag.snapshot,null,2);recordRenderedGeometry(renderedPayload);}clearReadout('旧表示へ戻りました。表示中の地物をクリックして読み直してください。');previousPresentation=null;presentationError='新表示の描画に失敗したため旧表示へ戻しました。現在受領した結果の更新は未反映です。接続と視点を保持しています。';diag.presentationError='presentation-render';updateCatalog();updateViewMemoryUI();status('');return true;
}
async function recordRenderedGeometry(next){if(!crypto.subtle)return;const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(next.geojson)));if(renderedPayload===next)diag.geometrySha256=Array.from(new Uint8Array(digest),v=>v.toString(16).padStart(2,'0')).join('');}
function renderSnapshot(reset=false){return payload?installPresentation(payload,overlayModule,catalogModule,null,reset):Promise.resolve(false);}
async function accept(raw){
 hover.invalidate();
 let next;try{next=validatePayload(raw);}catch(error){receiveError='受領した結果を表示できません。'+error.message;diag.payloadError=error.message;updateConnectButton();status('');return;}
 receiveError=null;diag.payloadError=null;clearReadout('対象の表示を更新しました。地物をクリックして読み直してください。');payload=next;updateConnectButton();diag.receivedSnapshot=receipt(next);diag.acceptedSnapshotId=next.snapshotId;
 const invalidated=viewMemory.updateCollection(next);updateViewMemoryUI(invalidated?'結果・選択集合変更のため視点記憶を解除しました':viewMemory.has()?'覚えた視点を保持しています':'視点はまだ覚えていません');
 await renderSnapshot(false);if(!viewer)status('同じ結果を受領しました。キーを入力すると写真3Dへ接続します。');
 if(crypto.subtle){const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(next.geojson)));if(payload===next)diag.receivedGeometrySha256=Array.from(new Uint8Array(digest),v=>v.toString(16).padStart(2,'0')).join('');}
}
function loadPresentationCss(revision){return new Promise((resolve,reject)=>{const link=document.createElement('link');link.rel='stylesheet';link.media='not all';link.href=`./style.css?presentation=${revision}`;const timer=setTimeout(()=>{link.remove();reject(new Error('stylesheet timeout'));},7000);link.onload=()=>{clearTimeout(timer);resolve(link);};link.onerror=()=>{clearTimeout(timer);link.remove();reject(new Error('stylesheet unavailable'));};document.head.append(link);});}
$('refreshPresentation').onclick=async()=>{
 if(presentationUpdating||!payload)return;presentationUpdating=true;$('refreshPresentation').disabled=true;const revision=Date.now();let css;
 try{const modules=await Promise.all([import(`./overlays.js?presentation=${revision}`),import(`./catalog.js?presentation=${revision}`)]);
  if(typeof modules[0].overlayEntities!=='function'||typeof modules[1].catalogView!=='function'||typeof modules[1].bandLegend!=='function')throw new Error('presentation interface mismatch');
  css=await loadPresentationCss(revision);const ok=await installPresentation(payload,modules[0],modules[1],css,false);
  if(ok){diag.presentation.updates++;$('presentationStatus').textContent='表示module・CSSだけを更新しました。接続・視点は保持しています。';}else $('presentationStatus').textContent='更新を適用しませんでした。旧表示を保持しています。';
 }catch(error){css?.remove();$('presentationStatus').textContent='表示更新を取得できません。旧表示・接続を保持しています。';diag.presentationError='presentation-load';}
 finally{presentationUpdating=false;$('refreshPresentation').disabled=false;}
};
function cancelClickRead(){clickReadAbort?.abort();clickReadAbort=null;clickReadRevision++;}
function clearReadout(message){cancelClickRead();if(readoutMarker&&viewer)viewer.entities.remove(readoutMarker);readoutMarker=null;diag.surfaceReadout=null;$('bandReadout').textContent=message;}
async function inspectSurface(e){
 if(!viewer||!tileset||!renderedPayload){clearReadout('背景へ接続した後、地物をクリックして輪郭区分を読みます。');return;}
 const shown=renderedPayload;
 // Context restrictions are checked before any surface query.
 const context=readBand(shown,null,{bandsVisible:$('showBands').checked});
 if(context.kind!=='unavailable'){clearReadout(context.text);return;}
 if(payload!==shown&&!presentationError){clearReadout('表示の更新中です。準備ができてからクリックしてください。');return;}
 cancelClickRead();const own=clickReadRevision,abort=new AbortController(),session=surfaceSession,pointInView={x:e.clientX,y:e.clientY};clickReadAbort=abort;
 try{
  const scene=viewer.scene;
  const values=await session.read(()=>{
   if(abort.signal.aborted||session!==surfaceSession||shown!==renderedPayload||diag.paused||presentationUpdating||receiveError)throw new DOMException('Surface read cancelled','AbortError');
   const excluded=[...(overlayStore?.pickExclusions||[]),...(routeLayer?.pickExclusions||[]),...(readoutMarker?[readoutMarker]:[])];
   const surface=pickSurface(C,scene,pointInView,excluded,session);if(!surface)throw new Error('mesh unavailable');
   return {surface,result:readBand(shown,surface.point,{bandsVisible:$('showBands').checked})};
  },{signal:abort.signal});
  if(abort.signal.aborted||own!==clickReadRevision||session!==surfaceSession||shown!==renderedPayload)return;
  const {position,height,point}=values.surface,result=values.result;
  clearReadout('');const prior=shown!==payload?'旧表示の読取り · ':'';$('bandReadout').textContent=prior+'クリック地点 · '+result.text;
  diag.surfaceReadout={...result,longitude:point[0],latitude:point[1],acceptedSnapshotId:payload?.snapshotId,renderedSnapshotId:shown.snapshotId,positionSource:'rendered depth + overlay-excluded current mesh height'};
  if(['band','boundary','outside95','not-displayed'].includes(result.kind))readoutMarker=viewer.entities.add({id:'inspection-location',position:C.Cartesian3.fromRadians(position.longitude,position.latitude,height),point:{color:C.Color.WHITE,outlineColor:C.Color.BLACK,outlineWidth:2,pixelSize:9,heightReference:C.HeightReference.CLAMP_TO_3D_TILE,disableDepthTestDistance:0}});
  scene.requestRender();
 }catch(error){if(!abort.signal.aborted&&own===clickReadRevision&&error?.name!=='AbortError')clearReadout('地表位置を取得できません。背景を待つか地物をクリックしてください。帯の外とは判定しません。');}
 finally{if(clickReadAbort===abort)clickReadAbort=null;}
}
const clicks=createClickTracker();
map.addEventListener('pointerdown',e=>{cancelClickRead();clicks.start(e,performance.now());});
map.addEventListener('pointermove',e=>clicks.move(e));
map.addEventListener('pointerup',e=>{if(clicks.end(e,performance.now()))inspectSurface(e);});
for(const event of ['pointercancel','lostpointercapture','wheel'])map.addEventListener(event,()=>{clicks.clear();cancelClickRead();},{passive:true});window.addEventListener('blur',()=>{clicks.clear();cancelClickRead();});
$('showBands').addEventListener('change',()=>clearReadout('分位面の表示を切り替えました。地物をクリックすると表示対象の輪郭区分を読めます。'));
function pause(value){hover.invalidate();cancelClickRead();if(value)routeLayer?.moving();else routeLayer?.changed();diag.paused=value;if(viewer){viewer.useDefaultRenderLoop=!value;if(!value){viewer.resize();viewer.scene.requestRender();}}}
window.addEventListener('message',e=>{if(!originAllowed(e)||e.data?.schema!==SCHEMA)return;if(e.data.type==='bjp-scene3d-open')accept(e.data.payload);if(e.data.type==='bjp-scene3d-pause')pause(true);if(e.data.type==='bjp-scene3d-resume')pause(false);if(e.data.type==='bjp-scene3d-intent-ack')acknowledge(e.data);});
function createView(){
 diag.viewerGeneration=(diag.viewerGeneration||0)+1;
 C.Ion.defaultAccessToken='';
 viewer=new C.Viewer(map,{baseLayer:false,baseLayerPicker:false,geocoder:false,globe:false,animation:false,timeline:false,homeButton:false,sceneModePicker:false,navigationHelpButton:false,fullscreenButton:false,vrButton:false,infoBox:false,selectionIndicator:false,scene3DOnly:true,requestRenderMode:true,maximumRenderTimeChange:Infinity,skyBox:false,skyAtmosphere:false});
 overlayStore=createOverlayStore(C,viewer);
 surfaceSession=createSurfaceSession(viewer.scene);
 viewer.scene.pickTranslucentDepth=false;
 routeLayer=createRouteLayer(C,viewer,{session:surfaceSession,exclusions:()=>[...(overlayStore?.pickExclusions||[]),...(readoutMarker?[readoutMarker]:[])],canSample:()=>!!tileset&&viewer.dataSourceDisplay.ready&&!diag.paused&&!presentationUpdating&&!presentationError&&!receiveError&&!diag.cameraEventMoving&&viewStability.ready(performance.now()),onState:routeState});
 viewer.resolutionScale=Math.min(devicePixelRatio,1.5)/devicePixelRatio;
 viewer.scene.screenSpaceCameraController.enableCollisionDetection=true;
 viewer.scene.screenSpaceCameraController.minimumZoomDistance=1;
 viewer.scene.screenSpaceCameraController.maximumZoomDistance=MAX_INSPECTION_DISTANCE;
 viewer.scene.screenSpaceCameraController.zoomEventTypes=[C.CameraEventType.WHEEL,C.CameraEventType.PINCH];
 viewer.scene.screenSpaceCameraController.tiltEventTypes=[C.CameraEventType.RIGHT_DRAG,C.CameraEventType.MIDDLE_DRAG,{eventType:C.CameraEventType.LEFT_DRAG,modifier:C.KeyboardEventModifier.CTRL}];
 viewer.scene.screenSpaceCameraController.rotateEventTypes=C.CameraEventType.LEFT_DRAG;
 // This host owns click inspection. Disable unused Viewer entity-selection picks
 // as well as tracking: those screen picks bypass our surface-session barrier.
 viewer.screenSpaceEventHandler.removeInputAction(C.ScreenSpaceEventType.LEFT_CLICK);
 viewer.screenSpaceEventHandler.removeInputAction(C.ScreenSpaceEventType.LEFT_DOUBLE_CLICK);
 viewer.camera.moveStart.addEventListener(()=>{diag.cameraEventMoving=true;hover.invalidate();cancelClickRead();routeLayer?.moving();});
 viewer.camera.moveEnd.addEventListener(()=>{diag.cameraEventMoving=false;routeLayer?.changed();});
 viewer.scene.renderError.addEventListener(()=>{hover.invalidate();cancelClickRead();diag.errors.push({kind:'render'});if(!restorePreviousPresentation()){presentationError='3D描画に失敗しました。接続は保持しています。2Dへ戻れます。';diag.presentationError='render';status('');}});
 viewer.scene.preRender.addEventListener(()=>{visibleFrame=0;});
 viewer.scene.postRender.addEventListener(()=>{
  const now=performance.now();if(viewStability.observe(publicViewPose(viewer.camera),now)){hover.invalidate();cancelClickRead();}diag.viewStability=viewStability.status(now);hover.ready();routeLayer?.ready();
  const camera=viewer.camera.positionCartographic;const pose={lng:C.Math.toDegrees(camera.longitude),lat:C.Math.toDegrees(camera.latitude),height:camera.height,heading:C.Math.toDegrees(viewer.camera.heading),pitch:C.Math.toDegrees(viewer.camera.pitch)};const key=JSON.stringify(pose);if(lastCamera!==key){diag.camera=pose;diag.cameraMoves++;lastCamera=key;}
  const elementsReady=viewer.dataSourceDisplay.ready;if(diag.overlayReady!==elementsReady){diag.overlayReady=elementsReady;status(elementsReady?'線と面の描画要素が準備できました。':'線と面を準備しています。');}
  if(!tileset)return;
  diag.tiles={loaded,failed,pending,processing,visibleThisFrame:visibleFrame,tilesLoaded:tileset.tilesLoaded};
  if(visibleFrame>0){background(failed?'partial':'visible',diag.provider==='synthetic-fixture'?'人工3D形状を描画中です。Google接続0・写真や実建物ではありません。':failed?'写真meshを描画中ですが一部取得に失敗しています。未取得を地物なしと判断しないでください。':'Googleの写真meshを描画中です。対象地点の詳細・重なりを画面で確認してください。');}
  else if(performance.now()-connectedAt>15000&&pending===0&&processing===0)background('unavailable','現在の視野に3D形状を表示できません。地域・通信・視点を確認し、「受け取った地域へ」で戻れます。');
 });
 diag.initialized=true;diag.cameraControls={left:'move',right:'orbit/tilt',wheel:'zoom',minDistance:1,maxDistance:MAX_INSPECTION_DISTANCE,collision:true};
 if(diag.paused)viewer.useDefaultRenderLoop=false;
}
async function connect(key,synthetic=false){if(!payload||receiveError){key=null;status('有効な分析結果の受領を待っています。Googleへの接続は開始しません。');return;}if(connecting||tileset){key=null;status('現在の接続を保持しています。接続先を替えるときは明示的に解除してください。');return;}destroyView();connecting=true;const ownEpoch=epoch;loaded=failed=pending=processing=0;connectedAt=performance.now();diag.provider=synthetic?'synthetic-fixture':'google-photorealistic-3d';diag.errors=[];$('connect').disabled=true;$('disconnect').hidden=false;background('connecting',synthetic?'人工3D形状を準備しています。':'Google写真3Dへ接続しています。');status('3D背景を準備しています。');
 try{createView();if(!synthetic){diag.rootRequestAttempts++;$('rootCount').textContent=String(diag.rootRequestAttempts);}let candidate=synthetic?await C.Cesium3DTileset.fromUrl('./fixtures/tileset.json',{enableCollision:true,maximumScreenSpaceError:4}):await googleTiles(C,key);key=null;if(ownEpoch!==epoch){candidate.destroy();return;}tileset=candidate;connecting=false;
  // A listener prevents the SDK fallback from logging the tile URL (and key).
  tileset.tileFailed.addEventListener(()=>{failed++;diag.tileFailureCount=failed;});
  tileset.tileLoad.addEventListener(()=>{loaded++;routeLayer?.changed();});tileset.tileUnload.addEventListener(()=>routeLayer?.changed());tileset.tileVisible.addEventListener(()=>{visibleFrame++;});tileset.loadProgress.addEventListener((p,n)=>{pending=p;processing=n;});
  viewer.scene.primitives.add(tileset);diag.googleConnected=!synthetic;background('loading',synthetic?'人工3D形状を読み込んでいます。':'Googleへ接続しました。対象地域の写真meshを読み込んでいます。');await renderSnapshot(true);updateViewMemoryUI();viewer.scene.requestRender();
 }catch(error){key=null;if(ownEpoch===epoch){connecting=false;failure(error);updateConnectButton();}}
}
$('connectForm').addEventListener('submit',e=>{e.preventDefault();if(!payload||receiveError){status('有効な分析結果の受領を待っています。Googleへの接続は開始しません。');return;}let key;try{key=credentialFromInput($('apiKey'));}catch(error){status(error.message);return;}connect(key);key=null;});
new ResizeObserver(()=>{if(viewer&&map.clientWidth&&map.clientHeight){viewer.resize();viewer.scene.requestRender();}}).observe(map);
window.addEventListener('error',e=>{diag.errors.push({kind:'script'});status('表示処理に失敗しました。分析へ戻れます。');e.preventDefault();});
window.addEventListener('unhandledrejection',e=>{diag.errors.push({kind:'async'});status('表示処理に失敗しました。分析へ戻れます。');e.preventDefault();});
window.addEventListener('pagehide',()=>{hover.invalidate();viewMemory.clear();if(viewer)destroyView();});
updateConnectButton();updateViewMemoryUI();updateConnectionLayout();post('bjp-scene3d-ready');
if(syntheticProbe){await accept(fixture());await connect(null,true);}
