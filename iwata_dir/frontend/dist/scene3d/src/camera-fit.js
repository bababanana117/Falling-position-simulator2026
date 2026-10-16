export const EARTH_RADIUS=6378137;
// Four Earth radii from the target permit a full-Earth overview while avoiding
// numerically valid but unusable billion-metre views during repeated zoom-out.
export const MAX_INSPECTION_DISTANCE=4*EARTH_RADIUS;
const rad=Math.PI/180;
function ecef(lng,lat){const l=lng*rad,p=lat*rad,e2=6.69437999014e-3,n=EARTH_RADIUS/Math.sqrt(1-e2*Math.sin(p)**2);return [n*Math.cos(p)*Math.cos(l),n*Math.cos(p)*Math.sin(l),n*(1-e2)*Math.sin(p)];}
export function fitBoundsDistance(bounds,center,{width=1,height=1,fov=50,pitch=-48}={}){
 const aspect=Math.max(.1,width/Math.max(1,height)),tanV=Math.tan(Math.max(1,Math.min(150,fov))*rad/2),tanH=tanV*aspect,a=-pitch*rad,l=center[0]*rad,p=center[1]*rad,origin=ecef(...center),east=[-Math.sin(l),Math.cos(l),0],north=[-Math.sin(p)*Math.cos(l),-Math.sin(p)*Math.sin(l),Math.cos(p)],up=[Math.cos(p)*Math.cos(l),Math.cos(p)*Math.sin(l),Math.sin(p)],dot=(v,w)=>v.reduce((sum,x,i)=>sum+x*w[i],0);
 let distance=1;const [w,s,e,n]=bounds;
 // Include edge midpoints as well as corners because the ellipsoid is curved.
 for(const lng of [w,(w+e)/2,e])for(const lat of [s,(s+n)/2,n]){const v=ecef(lng,lat).map((x,i)=>x-origin[i]),x=dot(v,east),y=dot(v,north),z=dot(v,up),vertical=y*Math.sin(a)+z*Math.cos(a),along=y*Math.cos(a)-z*Math.sin(a);distance=Math.max(distance,1.06*Math.abs(x)/tanH-along,1.06*Math.abs(vertical)/tanV-along);}
 return Math.min(MAX_INSPECTION_DISTANCE,distance);
}
