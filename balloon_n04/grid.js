(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;root.BalloonGrid=api;})(typeof globalThis!=='undefined'?globalThis:this,function(){
'use strict';
const R=6371.0088, toRad=Math.PI/180;
function validPoint(p){return Array.isArray(p)&&p.length===2&&Number.isFinite(p[0])&&Number.isFinite(p[1])&&Math.abs(p[0])<=90&&Math.abs(p[1])<=180;}
function boundsOf(poly){if(!Array.isArray(poly)||poly.length<3||!poly.every(validPoint))throw Error('有効な探索エリアが必要です');const lats=poly.map(p=>p[0]),lons=poly.map(p=>p[1]);return {south:Math.min(...lats),north:Math.max(...lats),west:Math.min(...lons),east:Math.max(...lons)};}
function inside(p,poly){let inside=false;const x=p[1],y=p[0];for(let i=0,j=poly.length-1;i<poly.length;j=i++){const xi=poly[i][1],yi=poly[i][0],xj=poly[j][1],yj=poly[j][0];if(((yi>y)!==(yj>y))&&(x<(xj-xi)*(y-yi)/(yj-yi)+xi))inside=!inside;}return inside;}
function generate(poly,opts={}){const b=boundsOf(poly),limit=opts.limit??200,target=Math.min(limit,Math.max(1,opts.target??64));if(!Number.isInteger(limit)||limit<1||limit>200||!Number.isInteger(target)||target<1)throw Error('地点数が不正です');const mid=(b.south+b.north)/2;const h=(b.north-b.south)*R*toRad,w=(b.east-b.west)*R*toRad*Math.cos(mid*toRad);if(h<0.005||w<0.005)throw Error('探索エリアが小さすぎます');if(b.east-b.west>180)throw Error('日付変更線を跨ぐエリアは非対応です');
let nx=Math.max(1,Math.round(Math.sqrt(target*w/h))),ny=Math.max(1,Math.round(target/nx));const grid=(x,y)=>{const pts=[];for(let iy=0;iy<y;iy++)for(let ix=0;ix<x;ix++){const lat=b.south+(iy+0.5)/y*(b.north-b.south),lon=b.west+(ix+0.5)/x*(b.east-b.west);if(inside([lat,lon],poly))pts.push({latitude:+lat.toFixed(7),longitude:+lon.toFixed(7),source:'grid'});}return pts;};
let pts=grid(nx,ny);while(pts.length>limit&&(nx>1||ny>1)){if(nx>=ny&&nx>1)nx--;else ny--;pts=grid(nx,ny);}if(!pts.length){const lat=(b.south+b.north)/2,lon=(b.west+b.east)/2;if(inside([lat,lon],poly))pts=[{latitude:+lat.toFixed(7),longitude:+lon.toFixed(7),source:'grid'}];}
return {points:pts,columns:nx,rows:ny,approx_km_x:w/nx,approx_km_y:h/ny,bounds:b};}
function rectangle(a,b){if(!validPoint(a)||!validPoint(b)||a[0]===b[0]||a[1]===b[1])throw Error('異なる２点を指定してください');return [[Math.min(a[0],b[0]),Math.min(a[1],b[1])],[Math.min(a[0],b[0]),Math.max(a[1],b[1])],[Math.max(a[0],b[0]),Math.max(a[1],b[1])],[Math.max(a[0],b[0]),Math.min(a[1],b[1])]];}
return {generate,rectangle,inside,boundsOf};
});
