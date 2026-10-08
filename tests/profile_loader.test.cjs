const {test}=require('node:test'),assert=require('node:assert/strict');
const {create,validate}=require('../scripts/profile_loader.js');
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}};
test('same pending profile shares a single fetch and then uses validated cache',async()=>{
 let calls=0;const d=deferred(),cache=new Map(),loader=create(cache,()=>{calls++;return d.promise},x=>x);
 const a=loader.load('x'),b=loader.load('x');assert.equal(a,b);await Promise.resolve();assert.equal(calls,1);
 d.resolve({value:1});assert.deepEqual(await a,{value:1});assert.equal(await loader.load('x'),cache.get('x'));assert.equal(calls,1);
});
test('failed and invalid responses are retryable and never enter cache',async()=>{
 let calls=0;const cache=new Map(),loader=create(cache,()=>++calls===1?Promise.reject(Error('HTTP')):Promise.resolve('ok'),x=>x);
 await assert.rejects(loader.load('x'));assert(!cache.has('x'));assert.equal(await loader.load('x'),'ok');
 const bad=create(cache,()=>({wrong:true}),()=>{throw Error('schema')});await assert.rejects(bad.load('bad'));assert(!cache.has('bad'));
});
test('timeout aborts transport; late response cannot overwrite a successful retry',async()=>{
 const d=deferred(),cache=new Map();let calls=0,firstSignal;
 const loader=create(cache,(_,signal)=>{if(++calls===1){firstSignal=signal;return d.promise}return 'new'},x=>x,10);
 await assert.rejects(loader.load('x'),/timeout/);assert(firstSignal.aborted);assert.equal(await loader.load('x'),'new');d.resolve('old');await new Promise(r=>setTimeout(r,0));assert.equal(cache.get('x'),'new');
});
test('schema rejects incomplete arrays, nonfinite and inconsistent counts; preserves missing values',()=>{
 const fields=['n','price_n','ppa_n','price','ppa','q1','q3'];const a=Object.fromEntries(fields.map(k=>[k,[null,1]]));a.period3=Object.fromEntries(fields.map(k=>[k,[null,1]]));
 const data={apt:{r:a}};assert.equal(validate(data,data,2),data);
 for(const change of [x=>x.apt.r.n.pop(),x=>x.apt.r.price[1]=Infinity,x=>x.apt.r.price_n[1]=2,x=>delete x.apt.r.period3]){const x=JSON.parse(JSON.stringify(data));change(x);assert.throws(()=>validate(x,data,2));}
});
