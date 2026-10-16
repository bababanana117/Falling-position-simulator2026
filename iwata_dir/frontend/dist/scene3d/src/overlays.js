import {normalizeSceneColor} from './colors.js';
export const PRESENTATION_REVISION='0.55.0-route-pair';

// Conversion produces renderer objects only. Source coordinates/IDs remain unchanged.
export function overlayEntities(C, payload) {
  const result=[];
  const xyz=coordinates=>coordinates.map(([lng,lat])=>C.Cartesian3.fromDegrees(lng,lat));
  const rgba=(value,alpha=1)=>C.Color.fromCssColorString(normalizeSceneColor(value)||'#34c9ff').withAlpha(alpha);
  const type=C.ClassificationType.CESIUM_3D_TILE;
  for(const [index,f] of payload.geojson.features.entries()) {
    const p=f.properties,g=f.geometry,candidate=payload.candidates.find(c=>c.candidateId===p.candidateId);
    // Elevated objects have a separate lifetime for finite mesh-height queries.
    if(p.kind==='flight-route'||p.kind==='route-curtain')continue;
    const color=p.kind==='support-boundary'?'#b0bac2':p.color||candidate?.color||(p.kind==='region'?'#ff595e':'#34c9ff');
    const base={id:`snapshot-feature-${index}`,properties:{...p,sourceFeatureIndex:index}};
    const line=(coords,suffix)=>({id:base.id+suffix,properties:base.properties,polyline:{positions:xyz(coords),clampToGround:true,classificationType:type,material:p.kind==='contour'?new C.PolylineOutlineMaterialProperty({color:rgba(color),outlineColor:rgba('#101820'),outlineWidth:2}):rgba(color),width:p.kind==='contour'?(p.level===.5?6:p.level===.9?4.5:3.2):p.kind==='mean-route'?3:2}});
    if(g.type==='Point') {
      const fixed={launch:'#ffffff',stop:'#f472b6','mean-landing':'#202124'};
      result.push({...base,position:C.Cartesian3.fromDegrees(...g.coordinates),point:{color:rgba(fixed[p.kind]||(p.kind==='landing'&&payload.context.kind==='detail'?(p.candidateColor||candidate?.color||color):color)),pixelSize:p.kind==='landing'?9:p.kind==='mean-landing'?14:11,outlineColor:p.kind==='landing'&&p.interference?rgba(color):C.Color.WHITE,outlineWidth:p.kind==='landing'&&p.interference?2:1,heightReference:C.HeightReference.CLAMP_TO_3D_TILE,disableDepthTestDistance:0}});
    } else if(g.type==='LineString') result.push(line(g.coordinates,'-line'));
    else {
      const polygons=g.type==='MultiPolygon'?g.coordinates:[g.coordinates];
      polygons.forEach((rings,part)=>{
        if(p.kind==='region'||p.kind==='contour-band') result.push({...base,id:base.id+`-fill-${part}`,polygon:{hierarchy:new C.PolygonHierarchy(xyz(rings[0]),rings.slice(1).map(ring=>new C.PolygonHierarchy(xyz(ring)))),material:rgba(color,Number.isFinite(p.fillOpacity)?p.fillOpacity:.22),classificationType:type,perPositionHeight:false,outline:false}});
        // A band's hole is a fill boundary only. Never resurrect a disabled contour.
        if(p.kind!=='contour-band')rings.forEach((ring,i)=>result.push(line(ring,`-ring-${part}-${i}`)));
      });
    }
  }
  return result;
}
