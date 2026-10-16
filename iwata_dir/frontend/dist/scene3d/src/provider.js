// No credential is returned by this module or placed on a global object.
export function credentialFromInput(input) {
  const key=String(input.value||'').trim();
  input.value='';
  if(!/^[A-Za-z0-9_-]{15,160}$/.test(key)) throw new Error('Map Tiles API 用キーを入力してください。');
  return key;
}

export function publicFailure(error) {
  const status=Number(error?.statusCode);
  if(status===401||status===403)return {kind:'authorization',status,text:'Googleへの接続が拒否されました。キー・Map Tiles APIの有効化・請求設定・利用元制限を確認してください。'};
  if(status===429)return {kind:'quota',status,text:'Googleの利用上限に達しました。分析へ戻れます。'};
  return {kind:'network-or-provider',status:Number.isInteger(status)&&status>=400&&status<=599?status:null,text:'Google写真3Dを取得できません。通信・キーの設定・利用上限を確認し、分析へ戻れます。'};
}

export async function googleTiles(C,key) {
  if(typeof key!=='string'||!key)throw new Error('missing-key');
  // Explicit key prevents Cesium's undefined-key fallback to ion.
  // No geocoder is installed: this application takes its own snapshot coordinates.
  return C.createGooglePhotorealistic3DTileset({key,onlyUsingWithGoogleGeocoder:true},{enableCollision:true,maximumScreenSpaceError:8,cacheBytes:384*1024*1024,maximumCacheOverflowBytes:128*1024*1024,showCreditsOnScreen:true});
}
