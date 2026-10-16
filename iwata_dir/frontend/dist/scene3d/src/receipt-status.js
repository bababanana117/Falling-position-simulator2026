// An invalid snapshot remains visible as an error while the renderer starts.
// Only a subsequent validated payload clears it; engine readiness is independent.
export function receiptStatus(){let error=null;return {reject(message){error=message;},accept(){error=null;},get error(){return error;},text(normal){return error??normal;}};}
