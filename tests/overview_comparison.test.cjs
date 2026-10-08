const {test}=require('node:test'),assert=require('node:assert/strict');
const {difference}=require('../scripts/overview_comparison.js');
const names={'서울':'서울특별시','경기':'경기도'};
const m=(value,scope='서울',period='2026-09',unit='%')=>({value,scope,period,unit});
test('differences in percentages are percentage points, including zero reference',()=>{
 assert.deepEqual(difference('서울',m(5),'경기',m(0,'경기'),'price',names),{delta:5,unit:'%p',reason:''});
 assert.equal(difference('서울',m(1.23),'경기',m(2,'경기'),'price',names).delta,-.77);
});
test('different periods are held instead of comparing unmatched observations',()=>{
 assert.equal(difference('서울',m(5),'경기',m(2,'경기','2026-08'),'price',names).reason,'기준기간 다름');
});
test('unavailable, nonfinite and different units cannot produce differences',()=>{
 for(const v of [null,NaN,Infinity,true])assert.equal(difference('서울',m(v),'경기',m(2,'경기'),'price',names).reason,'자료 없음');
 assert.equal(difference('서울',m(1),'경기',m(2,'경기','2026-09','호'),'price',names).reason,'단위 다름');
});
test('KB province and district aliases denote exact observed scope',()=>{
 assert.equal(difference('서울|강남구',m(2,'서울특별시|강남구'),'경기',m(1,'경기도'),'price',names).delta,1);
});
test('parent and combined fallback values remain visible but differences are held',()=>{
 assert.equal(difference('서울|강남구',m(2,'서울특별시'),'경기',m(1,'경기도'),'price',names).reason,'상위·통합 권역 자료');
 assert.equal(difference('서울',m(2),'광주',m(1,'전남광주'),'permit',names).reason,'상위·통합 권역 자료');
});
test('nationwide interest rates are common to regions; HAI differences use points',()=>{
 assert.equal(difference('서울',m(4,'전국'),'경기',m(4,'전국'),'rate',names).delta,0);
 assert.equal(difference('서울',m(90,'서울','2026-09',''),'경기',m(80,'경기','2026-09',''),'hai',names).unit,'점');
});
