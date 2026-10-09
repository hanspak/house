const test=require('node:test'),assert=require('node:assert/strict');
const C=require('../scripts/trade_composition.js');
test('three observed contiguous months are required; zero preserved',()=>{
 assert.equal(C.total([0,2,3],[0,1,2]),5);
 for(const [a,ix] of [[[1,null,3],[0,1,2]],[[1,2,3],[0,2,3]],[[1,2,3],[0,1]],[[1,2,3],[-1,0,1]],[[1,2,3],[1,2,3]]])assert.equal(C.total(a,ix),null);
});
test('unknown transactions are part of the denominator, not redistributed',()=>{
 const rows=C.partition(100,[30,20,10]);assert.deepEqual(rows.map(r=>r.n),[30,20,10,40]);assert.equal(rows[3].share,40);
 assert.equal(rows.reduce((n,r)=>n+r.share,0),100);
});
test('share changes are percentage points, with unchanged zero groups',()=>{
 const rows=C.compare(100,200,[40,30,0],[40,100,0]);assert.equal(rows[0].delta,20);assert.equal(rows[1].delta,-20);assert.equal(rows[2].delta,0);
});
test('missing groups or inconsistent sums hold all shares and unknown counts',()=>{
 for(const groups of [[null,1,2],[10,10,10],[-1,1,2]]){const rows=C.partition(20,groups);assert(rows.every(r=>r.share===null));assert.equal(rows[3].n,null);assert(rows.every(r=>r.status.length));}
});
test('zero total holds shares and comparisons, but retains real counts',()=>{
 const rows=C.compare(10,0,[5,0,0],[0,0,0]);assert(rows.every(r=>r.delta===null&&r.previous===0&&r.previousShare===null));assert.equal(rows[2].share,0);
});
