// Accept the opaque CSS forms actually used by the 2D candidate palette,
// including space-separated CSS4 hsl(). Return one shared sRGB hex value.
export function normalizeSceneColor(value){
 if(typeof value!=='string'||value.length>128)return null;const s=value.trim().toLowerCase();
 if(/^#[0-9a-f]{6}$/.test(s))return s;
 if(/^#[0-9a-f]{3}$/.test(s))return '#'+[...s.slice(1)].map(x=>x+x).join('');
 const m=/^(rgb|hsl)\(([^()]*)\)$/.exec(s);if(!m)return null;
 const parts=m[2].replaceAll(',',' ').trim().split(/\s+/);if(parts.length!==3||!parts.every(v=>Number.isFinite(parseFloat(v))))return null;
 if(m[1]==='rgb'){
  if(!parts.every(v=>/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)%?$/.test(v)))return null;
  const channels=parts.map(v=>Math.max(0,Math.min(255,parseFloat(v)*(v.endsWith('%')?2.55:1))));
  return '#'+channels.map(v=>Math.round(v).toString(16).padStart(2,'0')).join('');
 }
 if(!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:deg)?$/.test(parts[0])||!parts.slice(1).every(v=>/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)%$/.test(v)))return null;
 const h=((parseFloat(parts[0])%360)+360)%360,sat=Math.max(0,Math.min(100,parseFloat(parts[1]))),light=Math.max(0,Math.min(100,parseFloat(parts[2])));
 const l=light/100,a=sat/100*Math.min(l,1-l),channel=n=>{const k=(n+h/30)%12;return Math.round(255*(l-a*Math.max(-1,Math.min(k-3,9-k,1))));};
 return '#'+[channel(0),channel(8),channel(4)].map(v=>v.toString(16).padStart(2,'0')).join('');
}
