import {fitBoundsDistance} from './camera-fit.js';
export const SCHEMA='bjp-scene3d-v2';
export const KINDS=['landing','contour','contour-band','region','mean-route','flight-route','route-curtain','mean-landing','launch','stop','support-boundary','interference-extent'];
const id=v=>(typeof v==='string' && v.length>0) || (typeof v==='number' && Number.isFinite(v));
const coord=c=>Array.isArray(c)&&c.length===2&&Number.isFinite(c[0])&&Number.isFinite(c[1])&&Math.abs(c[0])<=180&&Math.abs(c[1])<=90;
const elevated=k=>k==='flight-route'||k==='route-curtain';
function require(ok,message){if(!ok)throw new Error(message);}
function line(cs,min=2){require(Array.isArray(cs)&&cs.length>=min&&cs.every(coord),'座標列は有限の経度・緯度で指定してください');}
function elevatedLine(cs){require(Array.isArray(cs)&&cs.length>=2&&cs.every(c=>Array.isArray(c)&&c.length===3&&coord(c.slice(0,2))&&Number.isFinite(c[2])),'立体経路は有限の [経度,緯度,高さm] で指定してください');}
function polygon(rs){require(Array.isArray(rs)&&rs.length>0,'輪郭のリングがありません');for(const r of rs){line(r,4);require(r[0][0]===r.at(-1)[0]&&r[0][1]===r.at(-1)[1],'輪郭は閉じている必要があります');}}
// A legacy 2D-only payload is valid. An elevated route is one ground/air pair,
// with its matching curtain retained in the payload even when the viewer hides it.
function routeCorrespondence(features){
 const groups=new Map();
 for(const f of features){const {kind,candidateId,resultId,phase}=f.properties;if(kind!=='mean-route'&&!elevated(kind))continue;
  const key=JSON.stringify([candidateId,resultId,phase]),group=groups.get(key)||{};(group[kind]??=[]).push(f);groups.set(key,group);
 }
 for(const group of groups.values()){
  if(!group['flight-route']&&!group['route-curtain'])continue;
  require(['mean-route','flight-route','route-curtain'].every(k=>group[k]?.length===1),'地表線・空中線・幕は候補・結果・相ごとに一組必要です');
  const ground=group['mean-route'][0],flight=group['flight-route'][0],curtain=group['route-curtain'][0],a=ground.geometry.coordinates,b=flight.geometry.coordinates,c=curtain.geometry.coordinates;
  require(ground.properties.visible!==false&&ground.properties.localVisible!==false,'非表示の地表経路に立体経路は追加できません');
  require(a.length===b.length&&a.every((p,i)=>p[0]===b[i][0]&&p[1]===b[i][1]),'地表線と空中線の座標対応が一致しません');
  require(b.length===c.length&&b.every((p,i)=>p.every((v,j)=>v===c[i][j])),'空中線と幕の座標対応が一致しません');
 }
}
export function validatePayload(raw){
 const p=structuredClone(raw);require(p&&id(p.snapshotId)&&typeof p.artificial==='boolean','結果出所と snapshotId が必要です');
 if(p.routeDisplay===undefined)p.routeDisplay={visible:true,curtain:true};
 require(p.routeDisplay&&typeof p.routeDisplay.visible==='boolean'&&typeof p.routeDisplay.curtain==='boolean','経路と幕の表示状態は boolean で指定してください');
 require(typeof p.collectionKey==='string'&&p.collectionKey.length>0,'結果集合の同一性がありません');
 require(['overview','detail'].includes(p.context?.kind),'概要または詳細の文脈が必要です');
 require(Array.isArray(p.candidates)&&p.candidates.length>0,'候補catalogがありません');
 const keys=new Map(),ids=new Set();for(const c of p.candidates){require(id(c.candidateId),'候補IDがありません');require(!ids.has(c.candidateId),'候補IDが重複しています');ids.add(c.candidateId);require(typeof c.available==='boolean'&&typeof c.visible==='boolean'&&typeof c.focused==='boolean','候補の計算・可視・注目状態がありません');require(c.available?id(c.resultId):c.resultId===null,'計算状態と結果IDが一致しません');require(c.parentId===null||id(c.parentId),'親IDが不正です');require(Number.isFinite(c.delayMinutes)&&c.delayMinutes>=0,'遅延値が不正です');keys.set(JSON.stringify([c.candidateId,c.resultId]),c);}
 require(p.candidates.filter(c=>c.focused).length<=1,'注目候補が複数あります');
 if(p.context.kind==='overview')for(const c of p.candidates){const seen=new Set([c.candidateId]);let parentId=c.parentId;while(parentId!==null){require(ids.has(parentId)&&!seen.has(parentId),'親子関係が不正です');seen.add(parentId);parentId=p.candidates.find(x=>x.candidateId===parentId).parentId;}}
 require(p.geojson?.type==='FeatureCollection'&&Array.isArray(p.geojson.features),'GeoJSON FeatureCollection が必要です');
 for(const f of p.geojson.features){const g=f.geometry,k=f.properties?.kind;require(f.type==='Feature'&&g,'geometry がありません');require(KINDS.includes(k),'未定義の表示種別です');
  const types={landing:['Point'],'mean-landing':['Point'],launch:['Point'],stop:['Point'],contour:['Point','LineString','Polygon','MultiPolygon'],'interference-extent':['Point','LineString','Polygon'],'contour-band':['Polygon','MultiPolygon'],region:['Polygon','MultiPolygon'],'support-boundary':['Polygon','MultiPolygon'],'mean-route':['LineString'],'flight-route':['LineString'],'route-curtain':['LineString']};require(types[k].includes(g.type),'表示種別とgeometryが一致しません');
  if(!['region','support-boundary','launch'].includes(k)){const c=keys.get(JSON.stringify([f.properties.candidateId,f.properties.resultId]));require(c&&c.available&&(p.context.kind==='detail'||c.visible),'表示対象外の候補・結果が含まれています');if(k==='contour-band')require(c.focused&&p.context.kind==='overview','分位帯は概要の注目候補だけです');if(elevated(k))require(c.focused&&f.properties.visible!==false&&f.properties.localVisible!==false,'立体経路は表示中の注目候補だけです');}
  if(g.type==='Point')require(['landing','mean-landing','launch','stop','contour','interference-extent'].includes(k)&&coord(g.coordinates),'点の座標が不正です');
  else if(g.type==='LineString'){if(elevated(k))elevatedLine(g.coordinates);else{require(k==='mean-route'||k==='contour'||k==='interference-extent','線の種別が不正です');line(g.coordinates);}}
  else if(g.type==='Polygon')polygon(g.coordinates);
  else if(g.type==='MultiPolygon'){require(g.coordinates.length>0,'空のMultiPolygonです');g.coordinates.forEach(polygon);}
  else throw new Error('未対応のgeometryです: '+g.type);
  if(k==='contour'||k==='contour-band')require([.5,.9,.95].includes(f.properties.level),'輪郭水準は50/90/95%を指定してください');
  if(k==='contour-band'){const lo={0.5:0,0.9:.5,0.95:.9};require(f.properties.lowerLevel===lo[f.properties.level],'分位帯の下限が一致しません');require(Number.isFinite(f.properties.fillOpacity)&&f.properties.fillOpacity>=0&&f.properties.fillOpacity<=1,'帯の不透明度が不正です');}
  if(elevated(k)){require(typeof f.properties.phase==='string'&&f.properties.phase.length>0,'立体経路の相がありません');require(f.properties.altitudeMode===(p.artificial?'relativeToGround':'absolute'),'結果出所と立体経路の高度基準が一致しません');}
  if(k==='route-curtain')require(Number.isFinite(f.properties.fillOpacity)&&f.properties.fillOpacity>=0&&f.properties.fillOpacity<=.99,'幕の不透明度は有限の 0〜0.99 で指定してください');
 }
 routeCorrespondence(p.geojson.features);
 require(coord(p.camera?.center),'camera.center は [経度,緯度] が必要です');
 const b=p.camera.bounds;require(Array.isArray(b)&&b.length===4&&b.every(Number.isFinite)&&b[0]<b[2]&&b[1]<b[3]&&coord([b[0],b[1]])&&coord([b[2],b[3]]),'camera.bounds が不正です');
 if(p.context?.kind==='detail'){const ctx=p.context,s=ctx.selection;require(p.candidates.length===1&&p.candidates[0].candidateId===ctx.activeCandidateId&&p.candidates[0].available,'詳細の対象候補が一致しません');require(s&&Array.isArray(s.sampleIds)&&Number.isInteger(s.count)&&s.count===s.sampleIds.length&&s.count>=0&&Number.isInteger(s.denominator)&&s.count<=s.denominator,'詳細の選択数とIDが一致しません');const selected=new Set(s.sampleIds);require(selected.size===s.count,'詳細の選択IDが重複しています');const points=p.geojson.features.filter(f=>(f.properties.kind==='landing'||(!p.artificial&&f.properties.kind==='stop')));if(s.spatialSampleIds!==undefined){require(!p.artificial&&Array.isArray(s.spatialSampleIds)&&new Set(s.spatialSampleIds).size===s.spatialSampleIds.length&&s.spatialSampleIds.every(x=>selected.has(x))&&Number.isInteger(s.nonSpatialCount)&&s.nonSpatialCount>=0&&s.nonSpatialCount+s.spatialSampleIds.length===s.count,'位置を持つ選択群と非空間試行の分割が一致しません');require(id(s.binding?.snapshotId)&&id(s.binding?.caseId)&&s.binding.resultId===p.candidates[0].resultId,'選択群の固定結果束縛がありません');const spatial=new Set(s.spatialSampleIds);require(points.length===spatial.size&&new Set(points.map(f=>f.properties.sampleId)).size===spatial.size&&points.every(f=>spatial.has(f.properties.sampleId)),'空間選択群と描画点が一致しません');}else require(points.length===s.count&&points.every(f=>selected.has(f.properties.sampleId)),'詳細の選択集合と落下点が一致しません');require(ctx.contours==='none'&&!p.geojson.features.some(f=>['contour','contour-band'].includes(f.properties.kind)),'2D詳細にない輪郭が含まれています');}
 return p;
}
export function receipt(p){return {schema:SCHEMA,snapshotId:p.snapshotId,collectionKey:p.collectionKey,context:structuredClone(p.context),candidates:p.candidates.map(c=>({candidateId:c.candidateId,resultId:c.resultId,parentId:c.parentId,delayMinutes:c.delayMinutes,available:c.available,visible:c.visible,focused:c.focused,pending:c.pending===true,shownLandingCount:c.shownLandingCount??null})),featureCounts:Object.fromEntries(KINDS.map(k=>[k,p.geojson.features.filter(f=>f.properties.kind===k).length])),camera:structuredClone(p.camera),artificial:p.artificial,recalculated:false,projectionTarget:'3D Tiles surface; actual provider state is separate'};}
export function cameraFor(p,viewport){return {lng:p.camera.center[0],lat:p.camera.center[1],height:0,distance:fitBoundsDistance(p.camera.bounds,p.camera.center,viewport),heading:0,pitch:-48,roll:0};}
