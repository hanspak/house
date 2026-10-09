(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.TradeComposition=api;})(globalThis,function(){
 'use strict';
 const count=v=>typeof v==='number'&&Number.isInteger(v)&&v>=0;
 function total(values,indices){
  if(!Array.isArray(indices)||indices.length!==3||indices.some((v,i)=>!Number.isInteger(v)||v<0||(i&&v!==indices[i-1]+1)))return null;
  const selected=indices.map(i=>values?.[i]);
  return selected.every(count)?selected.reduce((a,b)=>a+b,0):null;
 }
 function partition(n,groups){
  const valid=count(n)&&groups.length===3&&groups.every(count)&&groups.reduce((a,b)=>a+b,0)<=n;
  const counts=[...groups,valid?n-groups.reduce((a,b)=>a+b,0):null];
  return counts.map(v=>({n:v,share:valid&&n>0?v/n*100:null,status:!valid?'자료 누락 또는 구간 합계 불일치':n===0?'거래 0건으로 비중 보류':''}));
 }
 function compare(current,previous,currentGroups,previousGroups){
  const a=partition(current,currentGroups),b=partition(previous,previousGroups);
  return a.map((r,i)=>({...r,previous:b[i].n,previousShare:b[i].share,
   delta:r.share!==null&&b[i].share!==null?r.share-b[i].share:null,
   status:[r.status?'최근: '+r.status:'',b[i].status?'전년: '+b[i].status:''].filter(Boolean).join(' / ')}));
 }
 function largestChange(rows,current,previous){
  const held=status=>({group:null,delta:null,status});
  if(!count(current)||!count(previous))return held('자료 누락으로 비교 보류');
  if(current<10||previous<10)return held('최근·전년 모두 전체 거래 10건 이상일 때 비교');
  if(!Array.isArray(rows)||rows.length!==4||rows.some(r=>typeof r.delta!=='number'||!Number.isFinite(r.delta)||r.status))return held('자료 누락 또는 구간 합계 불일치');
  const group=rows.reduce((best,r,i)=>Math.abs(r.delta)>Math.abs(rows[best].delta)?i:best,0);
  return rows[group].delta===0?{group:null,delta:0,status:'모든 구간 비중 동일'}:{group,delta:rows[group].delta,status:'비교 가능'};
 }
 function monthly(totals,series){
  return totals.map((n,i)=>{
   const groups=partition(n,Array.from({length:3},(_,j)=>series?.[j]?.[i]??null));
   return {total:n,groups,status:groups[0].status||(n<10?'전체 거래 10건 미만: 비중 변동 주의':'')};
  });
 }
 return Object.freeze({total,partition,compare,largestChange,monthly});
});
