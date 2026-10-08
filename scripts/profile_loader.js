/* Shared pending requests and validated cache entries for lazy trade profiles. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.ProfileLoader=api;})(globalThis,function(){
 'use strict';
 function validate(stats,base,length){
  const fields=['n','price_n','ppa_n','price','ppa','q1','q3'];
  for(const type of Object.keys(base))for(const region of Object.keys(base[type])){
   const a=stats?.[type]?.[region];
   for(const group of [a,a?.period3])for(const key of fields){
    const values=group?.[key];
    if(!Array.isArray(values)||values.length!==length||values.some(v=>v!==null&&(typeof v!=='number'||!Number.isFinite(v)||v<0)))throw Error('Invalid profile');
   }
   for(const group of [a,a.period3])for(let i=0;i<length;i++){
    const [n,p,q]=[group.n[i],group.price_n[i],group.ppa_n[i]];
    if([n,p,q].some(v=>v!==null&&!Number.isInteger(v))||(p!==null&&n!==null&&p>n)||(q!==null&&p!==null&&q>p))throw Error('Invalid counts');
   }
  }
  return stats;
 }
 function create(cache,fetcher,validator,timeoutMs=15000){
  const pending=new Map();
  function load(key){
   if(cache.has(key))return Promise.resolve(cache.get(key));
   if(pending.has(key))return pending.get(key);
   const controller=new AbortController();let timer;
   const timeout=new Promise((_,reject)=>{timer=setTimeout(()=>{reject(Error('Profile timeout'));controller.abort();},timeoutMs);});
   const request=Promise.race([Promise.resolve().then(()=>fetcher(key,controller.signal)),timeout])
    .then(value=>{const result=validator(value);cache.set(key,result);return result;})
    .finally(()=>{clearTimeout(timer);if(pending.get(key)===request)pending.delete(key);});
   pending.set(key,request);return request;
  }
  return Object.freeze({load});
 }
 return Object.freeze({create,validate});
});
