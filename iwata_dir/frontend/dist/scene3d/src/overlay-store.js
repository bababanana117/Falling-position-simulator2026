// Own only overlay data sources, never the Viewer or Google tileset.
export function createOverlayStore(C,viewer){
 let current=null,previous=null,destroyed=false;
 const remove=layer=>{if(layer)viewer.dataSources.remove(layer.source,true);};
 return {
  async prepare(definitions){
   const source=new C.CustomDataSource('analysis-overlay');source.show=false;
   try{const items=definitions.map(item=>source.entities.add(item));await viewer.dataSources.add(source);if(destroyed){remove({source});throw new Error('overlay host changed');}return {source,items};}
   catch(error){if(!viewer.dataSources.contains?.(source)){if(typeof source.destroy==='function')source.destroy();}else remove({source});throw error;}
  },
  commit(layer){if(destroyed)throw new Error('overlay host changed');remove(previous);previous=current;current=layer;if(previous)previous.source.show=false;current.source.show=true;},
  discard(layer){remove(layer);},
  rollback(){if(!previous)return false;remove(current);current=previous;previous=null;current.source.show=true;return true;},
  get items(){return current?.items||[];},
  get pickExclusions(){return [...(current?.items||[]),...(previous?.items||[])];},
  get hasPrevious(){return !!previous;},
  destroy(){destroyed=true;remove(current);remove(previous);current=previous=null;}
 };
}
