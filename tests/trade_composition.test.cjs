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
test('largest absolute change includes unknown and uses first group for ties',()=>{
 const rows=C.compare(100,100,[10,10,10],[30,20,20]);
 assert.deepEqual(C.largestChange(rows,100,100),{group:3,delta:40,status:'비교 가능'});
 const tied=C.compare(100,100,[40,20,20],[20,40,20]);
 assert.equal(C.largestChange(tied,100,100).group,0);
 const negative=C.compare(100,100,[10,30,30],[70,10,10]);
 assert.equal(C.largestChange(negative,100,100).delta,-60);
});
test('both regional totals must reach ten; threshold is not a group sample',()=>{
 const rows=C.compare(10,10,[1,3,3],[0,4,3]);
 assert.equal(C.largestChange(rows,10,10).group,0);
 for(const totals of [[9,10],[10,9],[0,10]]){
  const r=C.largestChange(rows,...totals);assert.equal(r.delta,null);assert.equal(r.group,null);assert.match(r.status,/10건/);
 }
});
test('missing, invalid sums or nonfinite changes hold the regional comparison',()=>{
 for(const rows of [C.compare(20,20,[null,1,2],[1,1,2]),C.compare(20,20,[10,10,10],[1,1,2]),[{delta:NaN},{delta:0},{delta:0},{delta:0}],[]]){
  assert.equal(C.largestChange(rows,20,20).delta,null);
 }
 assert.match(C.largestChange(C.compare(20,20,[1,1,2],[1,1,2]),null,20).status,/누락/);
});
test('unchanged shares do not invent a dominant group',()=>{
 assert.deepEqual(C.largestChange(C.compare(100,200,[30,20,10],[60,40,20]),100,200),{group:null,delta:0,status:'모든 구간 비중 동일'});
});
test('monthly composition retains calendar positions and unknown denominator',()=>{
 const rows=C.monthly([100,200],[[30,60],[20,20],[10,40]]);
 assert.deepEqual(rows.map(r=>r.groups[3].n),[40,80]);
 assert.equal(rows[1].groups[1].share,10);
 assert(rows.every(r=>r.groups.reduce((n,g)=>n+g.share,0)===100));
});
test('monthly zero and missing observations leave gaps without inventing counts',()=>{
 const rows=C.monthly([0,null,10],[[0,null,2],[0,null,3],[0,null,1]]);
 assert(rows[0].groups.every(g=>g.n===0&&g.share===null));
 assert(rows[1].groups.every(g=>g.n===null&&g.share===null));
 assert.equal(rows[2].groups[3].share,40);assert.equal(rows.length,3);
 assert.match(rows[0].status,/0건/);assert.match(rows[1].status,/누락/);
});
test('small monthly totals retain shares and explicitly flag volatility',()=>{
 const rows=C.monthly([9,10],[[1,1],[3,3],[3,3]]);
 assert.equal(rows[0].groups[0].share,100/9);assert.match(rows[0].status,/10건 미만/);
 assert.equal(rows[1].status,'');
});
test('monthly missing groups, short arrays and inconsistent sums are held',()=>{
 for(const groups of [[[1],[2]],[[1,2],[2],[3,4]],[[10,10],[10,10],[10,10]],undefined]){
  const rows=C.monthly([20,20],groups);assert(rows.some(r=>r.groups.every(g=>g.share===null)));
 }
 assert(C.partition(10,[1,2]).every(r=>r.share===null));
});
