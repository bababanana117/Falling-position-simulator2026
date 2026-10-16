// Display geometry only. The ASL/AGL source remains the KML export authority.
import {normalizeSceneColor} from './colors.js';
// 0.999 quantizes to opaque alpha 255 in Cesium's static polyline appearance.
// 0.99 stays translucent (253): pickTranslucentDepth=false can read the ground.
export const FLIGHT_ALPHA=.99;
// A display lower surface, not an estimate or guarantee of the terrain elevation.
// Opaque photo mesh occludes the below-ground part; never fit to this depth.
export const CURTAIN_FLOOR_M=-12000;
export const MAX_GROUND_NODES=4096;
export function groundNodes(coordinates,spacing=1000,limit=MAX_GROUND_NODES){
 const out=[coordinates[0].slice()];
 for(let i=1;i<coordinates.length;i++){
  const a=coordinates[i-1],b=coordinates[i];
  const dl=((b[0]-a[0]+540)%360)-180,dy=b[1]-a[1];
  const distance=111320*Math.hypot(dl*Math.cos((a[1]+b[1])*Math.PI/360),dy);
  const count=Math.max(1,Math.ceil(distance/spacing));
  if(out.length+count>limit)throw new RangeError('Ground display node budget exceeded');
  for(let j=1;j<=count;j++){const t=j/count;out.push([((a[0]+dl*t+540)%360)-180,a[1]+dy*t,a[2]+(b[2]-a[2])*t]);}
 }
 return out;
}
/** @param {number[]} coordinate */
export const groundKey=coordinate=>`${coordinate[0]},${coordinate[1]}`;
export function routeSections(coordinates,mode,offset,ground){
 const line=coordinates.map(p=>[p[0],p[1],mode==='absolute'&&offset?p[2]+offset(p[0],p[1]):mode==='relativeToGround'&&Number.isFinite(ground.get(groundKey(p)))?p[2]+ground.get(groundKey(p)):NaN]);
 if(line.length<2||line.some(p=>!Number.isFinite(p[2])))return {flight:[],walls:[]};
 // The curtain explains vertical correspondence along the whole path. It is
 // not a terrain measurement. Keep the actual upper path even below a roof.
 const low=Math.min(CURTAIN_FLOOR_M,...line.map(p=>p[2]-1000));
 return {flight:[line],walls:[line.map(position=>({position,low}))]};
}
export function routeDefinitions(C,routes,offset,ground){
 const entities=[],extent=[],counts={nodes:0,resolved:0,wallSegments:0,flightSegments:0,requiresGround:routes.some(r=>r.properties.altitudeMode==='relativeToGround')};
 const toyReady=routes.filter(r=>r.properties.altitudeMode==='relativeToGround').every(r=>r.nodes.length&&r.nodes.every(p=>Number.isFinite(ground.get(groundKey(p)))));
 for(const route of routes){
  const {properties:p,geometry:g,index}=route,color=C.Color.fromCssColorString(normalizeSceneColor(p.color)||'#34c9ff');
  const coords=route.nodes.length?route.nodes:g.coordinates;
  const sampled=p.altitudeMode==='relativeToGround'&&!toyReady?{flight:[],walls:[]}:routeSections(coords,p.altitudeMode,offset,ground);
  // Share display vertices between upper edge and line; preserve every original
  // node, and never leave a gap caused by two different interpolation paths.
  const parts=sampled.flight;
  const properties={...p,sourceFeatureIndex:index};
  for(const [j,coords] of parts.entries()){
   const positions=coords.map(c=>C.Cartesian3.fromDegrees(...c));extent.push(...positions);
   entities.push({id:`flight-${index}-${j}`,properties,polyline:{positions,clampToGround:false,arcType:C.ArcType.GEODESIC,granularity:C.Math.RADIANS_PER_DEGREE,width:3,material:color.withAlpha(FLIGHT_ALPHA)}});counts.flightSegments+=coords.length-1;
  }
  for(const [j,rows] of sampled.walls.entries()){
   entities.push({id:`curtain-${index}-${j}`,properties:{...properties,kind:'route-curtain'},wall:{positions:rows.map(r=>C.Cartesian3.fromDegrees(...r.position)),minimumHeights:rows.map(r=>r.low),maximumHeights:rows.map(r=>r.position[2]),material:color.withAlpha(route.fillOpacity),granularity:C.Math.RADIANS_PER_DEGREE,outline:false}});counts.wallSegments+=rows.length-1;
  }
  for(const p of route.nodes){counts.nodes++;if(Number.isFinite(ground.get(groundKey(p))))counts.resolved++;}
  // Include the geographic footprint as well as the elevated path in explicit fit.
  extent.push(...g.coordinates.map(p=>C.Cartesian3.fromDegrees(p[0],p[1],ground.get(groundKey(p))??(offset?.(p[0],p[1])||0))));
 }
 return {entities,extent,counts};
}
