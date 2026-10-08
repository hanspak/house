const {test}=require('node:test');
const assert=require('node:assert/strict');
const A=require('../scripts/market_analysis.js');
const close=(actual,expected)=>assert(Math.abs(actual-expected)<1e-9,`${actual} != ${expected}`);
test('latest monthly observation uses calendar positions and leaves missing comparison unavailable',()=>{
  close(A.changeLatest([100,110,null],1),10);
  assert(Number.isNaN(A.changeLatest([100,null,120],1)));
  close(A.changeLatest([100,null,120],2),20);
  assert.deepEqual(A.lastOk([null,NaN,Infinity]),[null,-1]);
  assert(Number.isNaN(A.changeLatest(null,12)));
});
test('weekly change requires the current observation; no carry forward',()=>{
  assert(Number.isNaN(A.changeAt([100,110,null],2,1)));
  close(A.changeAt([100,110,120],2,2),20);
  assert(Number.isNaN(A.changeAt([100],0,1)));
});
test('weekly peak excludes 2023 onward and preserves first equal peak date',()=>{
  const dates=['2020-12-28','2021-01-04','2022-01-03','2022-12-26','2023-01-02'];
  const prices={sale:{r:[150,120,120,100,130]},jeonse:{r:[null,110,120,115,100]}};
  const snapshot=JSON.stringify(prices),s=A.weeklyStats(dates,prices);
  assert.equal(s.sale.r.peak,120);assert.equal(s.sale.r.peakDate,'2021-01-04');
  close(s.sale.r.pk,130/120*100-100);close(s.jeonse.r.w1,100/115*100-100);
  assert.equal(s.jeonse.r.first,'2021-01-04');assert.equal(JSON.stringify(prices),snapshot);
});
test('all six market phases and unavailable branch preserve thresholds',()=>{
  const cases=[[-1,2,1,'고점 아래 · 빠른 회복'],[-1,1,2,'고점 아래 · 완만한 회복'],[-1,-1,1,'고점 아래 · 약세'],[0,0,1,'고점 위 · 상승 멈춤'],[1,2,2,'고점 위 · 상승 가속'],[1,1,2,'고점 위 · 상승 둔화'],[NaN,1,2,'자료 부족']];
  for(const [pk,w12,ref,label] of cases)assert.equal(A.phase({pk,w12},'w12',ref),label);
});
test('sentiment alignment accepts exactly three days and rejects four',()=>{
  assert.deepEqual(A.alignNearby(['2026-01-05','2026-01-12'],['2026-01-08','2026-01-16'],[100,110]),[100,null]);
  assert.deepEqual(A.alignNearby(['2026-01-05'],[],[]),[null]);
});
test('percentile counts values strictly below latest and ignores missing observations',()=>{
  const s=A.sentimentSummary([10,20,null,20]);assert.equal(s.cur,20);close(s.avg,50/3);close(s.rank,100/3);
});
test('forward return excludes future-incomplete weeks and missing sentiment',()=>{
  const p=A.forwardPoints(['a','b','c','d'],[100,120,140,160],[10,null,30,40],2);
  assert.equal(p.length,1);close(p[0][1],40);assert.equal(p[0][2],'a');
});
test('historical sentiment bins require 15 and retain the existing upper-middle convention',()=>{
  const pts=Array.from({length:16},(_,i)=>[5,i,'d']);
  assert.deepEqual(A.sentimentBins(pts),[[5,8,16,0]]);
  assert.deepEqual(A.sentimentBins(pts.slice(0,14)),[]);
});
test('diffusion requires two observed regions and four complete consecutive weeks',()=>{
  const a={a:[100,101,102,103,104,105],b:[100,99,100,101,102,null]};
  const d=A.diffusion(a,['a','b'],6);
  assert.deepEqual(d.raw,[null,50,100,100,100,null]);
  assert.deepEqual(d.average,[null,null,null,null,87.5,null]);
});
test('exact alignment matches months, preserves gaps, and converts units',()=>{
  assert.deepEqual(A.alignExact(['2026-02','2026-01','2026-03'],['2026-01','2026-02'],[10000,20000],10000),[2,1,null]);
  assert.deepEqual(A.alignExact(['2026-01'],[],null),[null]);
  assert.deepEqual(A.rebase([100,null,120],0),[100,null,120]);
});
test('cycle low requires observed rise and minimum separation, without mutating input',()=>{
  const a=[100,...Array(110).fill(105)];const before=[...a];
  assert.deepEqual(A.troughs(a),[0]);assert.deepEqual(a,before);
  assert.deepEqual(A.troughs(Array(110).fill(100)),[]);
  assert.deepEqual(A.troughs(Array(110).fill(null)),[]);
});
