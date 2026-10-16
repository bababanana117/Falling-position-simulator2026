// Public, current-rendered-mesh APIs only. No terrain-provider lookup, network
// request, most-detailed sampling, private ray API, or ellipsoid fallback.
export function pickSurface(C,scene,client,excluded=[],session=null){
 if(session&&!session.isClean())return null;
 if(!scene.pickPositionSupported||!scene.sampleHeightSupported)return null;
 const rect=scene.canvas.getBoundingClientRect(),screen=new C.Cartesian2(client.x-rect.left,client.y-rect.top);
 if(screen.x<0||screen.y<0||screen.x>rect.width||screen.y>rect.height)return null;
 const hit=scene.pickPosition(screen);if(!hit)return null;
 const position=C.Cartographic.fromCartesian(hit);if(!position)return null;
 const height=scene.sampleHeight(position,excluded);if(!Number.isFinite(height))return null;
 return {screen,position,height,point:[C.Math.toDegrees(position.longitude),C.Math.toDegrees(position.latitude)]};
}

export function pickedNameBoundaryIndices(scene,screen,items,session=null){
 const known=new Set(items),indices=new Set();
 // No limit: other-count must not silently mean "the first N render primitives".
 try{for(const hit of scene.drillPick(screen,undefined,9,9)){
  const item=hit.id;
  if(!known.has(item)||item.show===false||!item.polyline)continue;
  const value=k=>item.properties?.[k]?.getValue?.()??item.properties?.[k];
  if(['contour','region'].includes(value('kind'))&&Number.isInteger(value('sourceFeatureIndex')))indices.add(value('sourceFeatureIndex'));
 }}finally{if(session)session.afterScreenPick();else scene.requestRender();}
 return [...indices];
}
