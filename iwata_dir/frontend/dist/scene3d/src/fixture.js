export const FIXTURE_CENTER=[137.036,35.168];
export function fixture() {
  const center=FIXTURE_CENTER,candidateId='fixture-A',resultId='synthetic-surface-390',features=[];
  const at=(east,north)=>[center[0]+east/(111320*Math.cos(center[1]*Math.PI/180)),center[1]+north/111320];
  const ring=(w,s,e,n)=>[[w,s],[e,s],[e,n],[w,n],[w,s]].map(([x,y])=>at(x,y));
  for(const [level,r] of [[.5,40],[.9,75],[.95,105]])features.push({type:'Feature',properties:{kind:'contour',candidateId,resultId,level},geometry:{type:'Polygon',coordinates:[ring(-r,-r,r,r)]}});
  for(const [level,lowerLevel,r,inner,fillOpacity] of [[.5,0,40,0,.28],[.9,.5,75,40,.17],[.95,.9,105,75,.09]])features.push({type:'Feature',properties:{kind:'contour-band',candidateId,resultId,level,lowerLevel,fillOpacity,focused:true},geometry:{type:'Polygon',coordinates:[ring(-r,-r,r,r),...(inner?[ring(-inner,-inner,inner,inner).reverse()]:[])]}});
  for(const [i,[x,y]] of [[-20,0],[0,0],[20,0],[60,35],[-80,80]].entries())features.push({type:'Feature',properties:{kind:'landing',candidateId,resultId,sampleId:'fixture-'+i},geometry:{type:'Point',coordinates:at(x,y)}});
  features.push({type:'Feature',properties:{kind:'region',level:2,color:'#f28c28',fillOpacity:.18,label:'人工の穴つき領域'},geometry:{type:'Polygon',coordinates:[ring(-110,-55,110,55),ring(-10,-15,10,15).reverse()]}});
  const route=[at(-120,-70),at(0,0),at(120,70)];
  features.push({type:'Feature',properties:{kind:'mean-route',candidateId,resultId,phase:'down',color:'#c35915'},geometry:{type:'LineString',coordinates:route}});
  for(const kind of ['flight-route','route-curtain'])features.push({type:'Feature',properties:{kind,candidateId,resultId,phase:'down',color:'#c35915',altitudeMode:'relativeToGround',fillOpacity:.22},geometry:{type:'LineString',coordinates:route.map((c,i)=>[...c,[100,60,0][i]])}});
  return {snapshotId:'synthetic-surface-fixture390',collectionKey:'synthetic-surface-390:unchanged-results-and-regions',context:{kind:'overview',activeCandidateId:candidateId,contours:'displayed'},createdAt:'2026-09-26T00:00:00Z',artificial:true,title:'人工段差・屋根で投影機構を確認（Googleではありません）',candidates:[{candidateId,resultId,available:true,visible:true,focused:true,parentId:null,delayMinutes:0,label:'人工投影試験 A',color:'hsl(188 100% 55%)',shownLandingCount:5,probabilityDefinition:'機構の試験形状。落下確率を示しません。',counts:{total:5,landed:5,hits:5,stopped:0,unknown:0}}],geojson:{type:'FeatureCollection',features},camera:{center,bounds:[...at(-180,-145),...at(180,145)]},notes:['この背景も点・線・穴つき面も人工です。Google実接続・樹冠再現・写真mesh適合の証明には使いません。']};
}
