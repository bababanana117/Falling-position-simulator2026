// The parent key covers all result IDs, region revision and detail selection.
// Visible geometry alone is intentionally insufficient: hiding/focusing must
// not erase a remembered place. The v2 parent owns this semantic identity.
export function collectionIdentity(payload){
 if(typeof payload.collectionKey!=='string'||!payload.collectionKey)throw new Error('missing authoritative collectionKey');
 return payload.collectionKey;
}
export function createViewMemory(C){
 let identity=null,pose=null;
 const copy=v=>C.Cartesian3.clone(v);
 const finite=v=>v&&[v.x,v.y,v.z].every(Number.isFinite);
 return {
  updateCollection(payload){const next=collectionIdentity(payload),invalidated=identity!==next&&pose!==null;if(identity!==next)pose=null;identity=next;return invalidated;},
  remember(camera){if(!identity||![camera.positionWC,camera.directionWC,camera.upWC].every(finite))return false;pose={position:copy(camera.positionWC),direction:copy(camera.directionWC),up:copy(camera.upWC)};return true;},
  restore(camera){if(!pose)return false;camera.lookAtTransform(C.Matrix4.IDENTITY);camera.setView({destination:copy(pose.position),orientation:{direction:copy(pose.direction),up:copy(pose.up)}});return true;},
  has(){return pose!==null;},
  clear(){identity=null;pose=null;}
 };
}
