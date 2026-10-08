/* Comparable regional differences; no DOM, storage or network dependencies. */
(function(root, factory) {
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.OverviewComparison=api;
})(globalThis,function(){
  'use strict';
  const finite=v=>typeof v==='number'&&Number.isFinite(v);
  function exactScope(region,metric,kbNames,key){
    if(key==='rate')return metric.scope==='전국';
    const [province,district]=region.split('|');
    const kb=(kbNames[province]||province)+(district?'|'+district:'');
    return metric.scope===region||metric.scope===kb;
  }
  function difference(region,metric,baseline,reference,key,kbNames={}){
    if(!finite(metric?.value)||!finite(reference?.value))return {delta:null,unit:'',reason:'자료 없음'};
    if(metric.unit!==reference.unit)return {delta:null,unit:'',reason:'단위 다름'};
    if(!metric.period||metric.period!==reference.period)return {delta:null,unit:'',reason:'기준기간 다름'};
    if(!exactScope(region,metric,kbNames,key)||!exactScope(baseline,reference,kbNames,key))
      return {delta:null,unit:'',reason:'상위·통합 권역 자료'};
    const unit=metric.unit==='%'?'%p':key==='hai'?'점':metric.unit;
    return {delta:Math.round((metric.value-reference.value)*100)/100,unit,reason:''};
  }
  return Object.freeze({difference});
});
