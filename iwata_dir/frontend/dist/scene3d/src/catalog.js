import {normalizeSceneColor} from './colors.js';
export const PRESENTATION_REVISION='0.39.0-r8-detail-card';

// Detached DOM first: applying or rejecting presentation cannot touch a provider.
export function catalogView(document,payload,onIntent,{busy=false,embedded=true}={}){
 const root=document.createElement('div');root.className='catalog-tree';
 const detail=payload.context.kind==='detail';
 const make=(tag,text,className)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(className)el.className=className;return el;};
 const row=c=>{
  const el=make('div',undefined,'candidate-row'+(c.focused?' focused':'')+(!c.visible?' not-visible':''));
  el.dataset.candidateId=String(c.candidateId);el.style.setProperty('--c',normalizeSceneColor(c.color)||'#34c9ff');
  const checkbox=make('input');checkbox.type='checkbox';checkbox.checked=c.visible;checkbox.disabled=busy||detail||!c.available||!embedded;checkbox.setAttribute('aria-label',`${c.label||c.candidateId}を表示`);checkbox.onchange=()=>{const value=checkbox.checked;checkbox.checked=c.visible;onIntent('visibility',c.candidateId,value);};
  const button=make('button',detail?(c.label||String(c.candidateId)):c.parentId===null?(c.label||String(c.candidateId)):`+${c.delayMinutes}分`,'candidate-focus');button.title=`${c.label||c.candidateId} · ${c.candidateId} · 結果 ${c.resultId??'未計算'}`;button.type='button';button.disabled=busy||detail||!c.available||!embedded;button.setAttribute('aria-pressed',String(c.focused));button.onclick=()=>onIntent('focus',c.candidateId);
  const note=make('small',`${c.focused?'注目 · ':''}${c.available?(c.visible?'表示':'非表示'):'未計算'}${c.pending&&c.available?' · 入力未反映（表示は前回結果）':''}`,'candidate-state');
  el.append(checkbox,button,note);return el;
 };
 if(detail){
  // Overview visibility is not the display state of this detail selection.
  const c=payload.candidates[0],selection=payload.context.selection,card=make('div',undefined,'candidate-row detail-candidate');
  card.dataset.candidateId=String(c.candidateId);card.style.setProperty('--c',normalizeSceneColor(c.color)||'#34c9ff');
  const label=make('span',c.label||String(c.candidateId),'candidate-focus');label.style.gridColumn='1 / -1';
  const note=make('small',`選択 ${selection.count}/${selection.denominator} ${payload.artificial?'着地点':'予定試行（位置のない試行を含む）'}${c.pending&&c.available?' · 入力未反映（表示は前回結果）':''}`,'candidate-state');note.style.gridColumn='1 / -1';
  card.append(label,note);root.append(card,make('p','選択群の変更は分析画面で行います。','catalog-help'));return root;
 }
 const appendFamily=(candidate,container)=>{container.append(row(candidate));const children=payload.candidates.filter(c=>c.parentId===candidate.candidateId).sort((a,b)=>a.delayMinutes-b.delayMinutes);if(children.length){const childrenEl=make('div',undefined,'candidate-children');for(const child of children)appendFamily(child,childrenEl);container.append(childrenEl);}};
 for(const c of payload.candidates.filter(c=>c.parentId===null)){const family=make('section',undefined,'candidate-family');appendFamily(c,family);root.append(family);}
 if(!payload.candidates.some(c=>c.visible&&c.available))root.append(make('p','すべて非表示です。表示チェックから戻せます。','catalog-help'));
 if(!embedded)root.append(make('p','独立人工試験：候補の編集は分析画面から接続したときに使えます。','catalog-help'));
 return root;
}

export function bandLegend(payload){
 if(!payload.artificial){const candidate=payload.candidates.find(c=>c.focused);return candidate?.resultKind==='ensemble'?'固定集合の全着地標本の経験50/90/95%域。点・線の退化は面積を付けません。面の濃淡は確率密度ではありません。':'実計算 n=1 の終了点と実軌道の地表投影。分位域はありません。';}
 if(payload.context.kind==='detail')return '選択群の着地点・平均経路。全体輪郭は表示していません。';
 const c=payload.candidates.find(c=>c.focused);
 if(!c)return '塗りなし：注目候補を選んでください。';
 if(!c.available)return `塗りなし：注目 ${c.label||c.candidateId} は未計算です。`;
 if(!c.visible)return `塗りなし：注目 ${c.label||c.candidateId} は非表示です。`;
 const bands=payload.geojson.features.filter(f=>f.properties.kind==='contour-band');
 return bands.length?`塗り：${c.label||c.candidateId} の経験輪郭内・輪郭間（他候補は線）。`:`塗りなし：${c.label||c.candidateId} の表示できる帯がありません。`;
}
