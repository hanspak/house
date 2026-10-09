(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.TradeComposition=api;})(globalThis,function(){
 'use strict';
 const count=v=>typeof v==='number'&&Number.isInteger(v)&&v>=0;
 function total(values,indices){
  if(!Array.isArray(indices)||indices.length!==3||indices.some((v,i)=>!Number.isInteger(v)||v<0||(i&&v!==indices[i-1]+1)))return null;
  const selected=indices.map(i=>values?.[i]);
  return selected.every(count)?selected.reduce((a,b)=>a+b,0):null;
 }
 function partition(n,groups){
  const valid=count(n)&&groups.every(count)&&groups.reduce((a,b)=>a+b,0)<=n;
  const counts=[...groups,valid?n-groups.reduce((a,b)=>a+b,0):null];
  return counts.map(v=>({n:v,share:valid&&n>0?v/n*100:null,status:!valid?'자료 누락 또는 구간 합계 불일치':n===0?'거래 0건으로 비중 보류':''}));
 }
 function compare(current,previous,currentGroups,previousGroups){
  const a=partition(current,currentGroups),b=partition(previous,previousGroups);
  return a.map((r,i)=>({...r,previous:b[i].n,previousShare:b[i].share,
   delta:r.share!==null&&b[i].share!==null?r.share-b[i].share:null,
   status:[r.status?'최근: '+r.status:'',b[i].status?'전년: '+b[i].status:''].filter(Boolean).join(' / ')}));
 }
 return Object.freeze({total,partition,compare});
});
