import {ringRelation} from './band-readout.js';

const polygons=g=>g.type==='MultiPolygon'?g.coordinates:[g.coordinates];
const finitePoint=p=>Array.isArray(p)&&p.length===2&&p.every(Number.isFinite);
const present=v=>v!==undefined&&v!==null&&String(v).length>0;
const text=(value,fallback)=>typeof value==='string'&&value.trim()?value.trim():fallback;
const order=(a,b)=>b.priority-a.priority||a.key.localeCompare(b.key);
export function containsSurface(point,geometry){
 if(!finitePoint(point)||!['Polygon','MultiPolygon'].includes(geometry?.type))return false;
 return polygons(geometry).some(rings=>{
  const outer=ringRelation(point,rings[0]);
  return outer!=='outside'&&rings.slice(1).every(r=>ringRelation(point,r)!=='inside');
 });
}

// Only identifiers in the actually rendered payload can acquire a label. The host
// supplies screen-picked contour indices, never Google feature metadata.
export function resolveHover(payload,point,{bandsVisible=true,regionsVisible=true,linesVisible=true,lineFeatureIndices=[]}={}){
 if(!payload||!finitePoint(point))return {targets:[],otherCount:0,total:0};
 const candidates=new Map(),regions=new Map(),lineIndices=new Set(lineFeatureIndices);
 for(const [index,f] of payload.geojson.features.entries()){
  const p=f.properties;
  if(p.kind==='region'){
   const fill=regionsVisible&&p.fillOpacity!==0&&containsSurface(point,f.geometry);
   const boundary=linesVisible&&lineIndices.has(index);
   if(p.visible===false||(!fill&&!boundary))continue;
   const identity=present(p.regionId)?p.regionId:present(p.id)?p.id:`feature-${index}`;
   const key=JSON.stringify(['region',identity]),label=text(p.label,`領域 ${identity}`),level=text(p.levelName,'');
   const target={kind:'region',key,label,text:`領域：${label}${level?' · '+level:''}`,priority:Number.isFinite(p.priority)?p.priority:0};
   if(!regions.has(key)||order(target,regions.get(key))<0)regions.set(key,target);
   continue;
  }
  const fill=p.kind==='contour-band'&&bandsVisible&&p.fillOpacity!==0&&containsSurface(point,f.geometry);
  const line=p.kind==='contour'&&linesVisible&&lineIndices.has(index);
  if(payload.context.kind!=='overview'||(!fill&&!line))continue;
  const c=payload.candidates.find(c=>c.candidateId===p.candidateId&&c.resultId===p.resultId);
  if(!c?.available||!c.visible)continue;
  const key=JSON.stringify(['candidate',c.candidateId,c.resultId]),label=text(c.label,`候補 ${c.candidateId}`);
  candidates.set(key,{kind:'candidate',key,label,text:`落下分散：${label}`,priority:c.focused?1:0});
 }
 const cs=[...candidates.values()].sort(order),rs=[...regions.values()].sort(order),chosen=[];
 if(cs.length)chosen.push(cs.shift());
 if(rs.length)chosen.push(rs.shift());
 for(const target of [...cs,...rs])if(chosen.length<2)chosen.push(target);
 const total=candidates.size+regions.size;
 return {targets:chosen,otherCount:total-chosen.length,total};
}

export function tooltipPosition(point,size,bounds,{gap=13,padding=6}={}){
 const width=Math.min(size.width,Math.max(0,bounds.width-2*padding)),height=Math.min(size.height,Math.max(0,bounds.height-2*padding));
 let left=point.x+gap,top=point.y+gap;
 if(left+width>bounds.right-padding)left=point.x-gap-width;
 if(top+height>bounds.bottom-padding)top=point.y-gap-height;
 return {left:Math.max(bounds.left+padding,Math.min(left,bounds.right-padding-width)),top:Math.max(bounds.top+padding,Math.min(top,bounds.bottom-padding-height))};
}

export function shortenHoverText(value,limit){
 const characters=Array.from(value);if(characters.length<=limit)return value;
 const left=Math.ceil((limit-1)/2),right=Math.floor((limit-1)/2);
 return characters.slice(0,left).join('')+'…'+characters.slice(-right).join('');
}
