// Geographic reading of the parent's rendered polygons, not a probability model.
const EPS=1e-8;
function onSegment(p,a,b){const dx=b[0]-a[0],dy=b[1]-a[1],length=Math.hypot(dx,dy);if(length===0)return Math.hypot(p[0]-a[0],p[1]-a[1])<=EPS;const distance=Math.abs(dx*(p[1]-a[1])-dy*(p[0]-a[0]))/length;const t=((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(length*length);return distance<=EPS&&t>=-EPS/length&&t<=1+EPS/length;}
export function ringRelation(point,ring){let inside=false;for(let i=0,j=ring.length-1;i<ring.length;j=i++){const a=ring[j],b=ring[i];if(onSegment(point,a,b))return 'boundary';if((a[1]>point[1])!==(b[1]>point[1])&&point[0]<(b[0]-a[0])*(point[1]-a[1])/(b[1]-a[1])+a[0])inside=!inside;}return inside?'inside':'outside';}
const parts=f=>f.geometry.type==='MultiPolygon'?f.geometry.coordinates:[f.geometry.coordinates];
export function readBand(payload,point,{bandsVisible=true}={}){
 const base={snapshotId:payload?.snapshotId,bandsVisible};
 if(!payload||payload.context.kind!=='overview')return {...base,kind:'detail',text:'詳細は選択群の確認です。全体分位帯は読み取りません。'};
 const candidate=payload.candidates.find(c=>c.focused);
 if(!candidate)return {...base,kind:'no-focus',text:'注目候補がありません。'};
 Object.assign(base,{candidateId:candidate.candidateId,resultId:candidate.resultId,label:candidate.label||String(candidate.candidateId)});
 if(!candidate.available)return {...base,kind:'no-result',text:`注目 ${base.label} は未計算です。`};
 if(!candidate.visible)return {...base,kind:'hidden-focus',text:`注目 ${base.label} は非表示です。帯は読み取りません。`};
 if(!Array.isArray(point)||point.length!==2||!point.every(Number.isFinite))return {...base,kind:'unavailable',text:'地表位置を取得できません。帯の外とは判定しません。'};
 const features=payload.geojson.features.filter(f=>f.properties.kind==='contour-band'&&f.properties.candidateId===candidate.candidateId&&f.properties.resultId===candidate.resultId);
 if(!features.length&&payload.geojson.features.some(f=>f.properties.kind==='contour'&&f.properties.candidateId===candidate.candidateId&&['Point','LineString'].includes(f.geometry.type)))return {...base,kind:'degenerate',text:'経験域は点または線です。面積・帯の内外を定義しません。'};
 if(!features.length)return {...base,kind:'no-bands',text:`注目 ${base.label} の描画対象に輪郭帯がありません。`};
 const boundary=new Set(),inside=[];
 for(const f of features){let hit=false;for(const rings of parts(f)){const relation=rings.map(r=>ringRelation(point,r));relation.forEach((r,i)=>{if(r==='boundary')boundary.add(i===0?f.properties.level:f.properties.lowerLevel);});if(relation[0]==='inside'&&relation.slice(1).every(r=>r==='outside'))hit=true;}if(hit)inside.push(f.properties);}
 const prefix=`注目 ${base.label} · 経験輪郭`,suffix=bandsVisible?'':'（面の表示はOFF）';
 if(boundary.size){const levels=[...boundary].sort((a,b)=>a-b);return {...base,kind:'boundary',levels,text:`${prefix} ${levels.map(v=>Math.round(v*100)+'%').join('/')}境界上 ${suffix}`};}
 if(inside.length===1){const b=inside[0],range=b.lowerLevel===0?'50%内':`${Math.round(b.lowerLevel*100)}–${Math.round(b.level*100)}%間`;return {...base,kind:'band',lowerLevel:b.lowerLevel,level:b.level,text:`${prefix} ${range} ${suffix}`};}
 if(inside.length>1)return {...base,kind:'ambiguous',text:'帯の形状が重なるため区分を確定できません。'};
 const outer=features.filter(f=>f.properties.level===.95);if(outer.length&&!outer.some(f=>parts(f).some(rs=>ringRelation(point,rs[0])!=='outside')))return {...base,kind:'outside95',text:`${prefix} 95%外 ${suffix}`};
 return {...base,kind:'not-displayed',text:`${prefix} 表示中の帯に含まれません。非表示の帯は判定しません。${suffix}`};
}

// A short primary-pointer click only. A drag returning to its start is still a drag.
export function createClickTracker({distance=5,duration=650}={}){
 let down=null;
 const plain=e=>!e.ctrlKey&&!e.shiftKey&&!e.altKey&&!e.metaKey;
 return {
  start(e,now){down=e.button===0&&plain(e)?{id:e.pointerId,x:e.clientX,y:e.clientY,at:now,max:0}:null;},
  move(e){if(!plain(e)){down=null;return;}if(down&&down.id===e.pointerId)down.max=Math.max(down.max,Math.hypot(e.clientX-down.x,e.clientY-down.y));},
  end(e,now){this.move(e);const click=down&&down.id===e.pointerId&&e.button===0&&plain(e)&&down.max<=distance&&now-down.at<=duration;down=null;return !!click;},
  clear(){down=null;}
 };
}
