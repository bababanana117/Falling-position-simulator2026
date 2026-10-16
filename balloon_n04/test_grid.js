const assert=require('node:assert/strict'),g=require('./grid.js');
const r=g.rectangle([43.2,142.2],[43.4,142.5]);assert.equal(r.length,4);
const result=g.generate(r);assert(result.points.length>0&&result.points.length<=200);assert(result.points.every(p=>g.inside([p.latitude,p.longitude],r)));
const tri=[[43.2,142.2],[43.2,142.5],[43.4,142.35]];const t=g.generate(tri,{target:200});assert(t.points.length<=200&&t.points.every(p=>g.inside([p.latitude,p.longitude],tri)));
assert.throws(()=>g.generate([[0,0],[0,0],[0,0]]));assert.throws(()=>g.generate(r,{limit:201}));
const a=g.generate(r,{target:25}),b=g.generate(r,{target:150});assert(b.points.length>a.points.length);
console.log('N04 grid tests: OK (rectangle, polygon, count limit, validation, density)');
