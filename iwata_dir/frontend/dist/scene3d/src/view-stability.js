// Public camera state, measured in world metres and unit direction components.
// Camera moveEnd and exact floating-point identity are not evidence of visual rest.
export function publicViewPose(camera){
 if(!camera)return null;
 const vector=v=>v?[v.x,v.y,v.z]:null;
 return {position:vector(camera.positionWC),direction:vector(camera.directionWC),up:vector(camera.upWC),fov:camera.frustum?.fov,aspect:camera.frustum?.aspectRatio};
}
const vector=v=>Array.isArray(v)&&v.length===3&&v.every(Number.isFinite);
const valid=p=>p&&vector(p.position)&&vector(p.direction)&&vector(p.up)&&Number.isFinite(p.fov)&&p.fov>0&&Number.isFinite(p.aspect)&&p.aspect>0;
const maximumDifference=(a,b)=>Math.max(...a.map((v,i)=>Math.abs(v-b[i])));

export function createViewStability({positionTolerance=1e-5,axisTolerance=1e-10,quietMs=260}={}){
 if(![positionTolerance,axisTolerance,quietMs].every(v=>Number.isFinite(v)&&v>=0))throw new Error('Invalid view stability tolerance');
 let anchor=null,changedAt=null,changes=0;
 return {
  observe(pose,now){
   if(!valid(pose)||!Number.isFinite(now)){const hadPose=!!anchor;anchor=null;changedAt=null;return hadPose;}
   const changed=!anchor||Math.hypot(...pose.position.map((v,i)=>v-anchor.position[i]))>positionTolerance||maximumDifference(pose.direction,anchor.direction)>axisTolerance||maximumDifference(pose.up,anchor.up)>axisTolerance||Math.abs(pose.fov-anchor.fov)>axisTolerance||Math.abs(pose.aspect-anchor.aspect)>axisTolerance;
   // Preserve the last significant anchor, not the previous frame. Slow motion
   // accumulates until it crosses the tolerance instead of vanishing forever.
   if(changed){anchor=structuredClone(pose);changedAt=now;changes++;}
   return changed;
  },
  ready(now){return !!anchor&&Number.isFinite(now)&&now-changedAt>=quietMs;},
  status(now){return {hasPose:!!anchor,quietMs,settledMs:anchor&&Number.isFinite(now)?Math.max(0,now-changedAt):0,changes,ready:this.ready(now)};},
  clear(){anchor=null;changedAt=null;changes=0;}
 };
}
