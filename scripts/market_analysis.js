/* Pure KB indicator calculations. No DOM, storage, network or mutable page state.
 * Formula changes require tests and docs/indicators.md updates.
 * Non-finite results remain unavailable; UI controls their presentation.
 */
(function(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.MarketAnalysis = api;
})(globalThis, function() {
  "use strict";
  const ok = v => v != null && isFinite(v);
  const changeAt = (a, i, periods) => i-periods>=0 && ok(a[i]) && ok(a[i-periods])
    ? (a[i]/a[i-periods]-1)*100 : NaN;
  function lastOk(a) {
    if (!a) return [null, -1];
    for (let i=a.length-1; i>=0; i--) if (ok(a[i])) return [a[i], i];
    return [null, -1];
  }
  function changeLatest(a, periods) {
    if (!a) return NaN;
    const [, i] = lastOk(a);
    return changeAt(a, i, periods);
  }
  function weeklyStats(dates, price) {
    const N=dates.length, pk0=dates.findIndex(d=>d>="2021-01"), pk1=dates.findIndex(d=>d>="2023-01");
    const result={sale:{},jeonse:{}};
    for (const md of ["sale","jeonse"]) for (const k of Object.keys(price.sale)) {
      const a=price[md][k],seg=a.slice(pk0,pk1),vals=seg.filter(ok),pv=vals.length?Math.max(...vals):NaN;
      result[md][k]={w1:changeAt(a,N-1,1),w4:changeAt(a,N-1,4),w12:changeAt(a,N-1,12),w26:changeAt(a,N-1,26),w52:changeAt(a,N-1,52),idx:a[N-1],peak:pv,
        peakDate:ok(pv)?dates[pk0+seg.indexOf(pv)]:null,pk:ok(pv)?(a[N-1]/pv-1)*100:NaN,first:dates[a.findIndex(ok)]};
    }
    return result;
  }
  function alignNearby(dates, sourceDates, values, toleranceDays=3) {
    const t=sourceDates.map(d=>Date.parse(d)),out=new Array(dates.length).fill(null);let j=0;
    for(let i=0;i<dates.length;i++){const ti=Date.parse(dates[i]);while(j<t.length-1&&t[j+1]<=ti+toleranceDays*864e5)j++;
      if(Math.abs(t[j]-ti)<=toleranceDays*864e5)out[i]=values[j];}
    return out;
  }
  function phase(s, period, reference) {
    const c=s[period];
    if(!ok(s.pk)||!ok(c))return "자료 부족";
    if(s.pk<0)return c>=reference?"고점 아래 · 빠른 회복":c>0?"고점 아래 · 완만한 회복":"고점 아래 · 약세";
    if(c<=0)return "고점 위 · 상승 멈춤";return c>=reference?"고점 위 · 상승 가속":"고점 위 · 상승 둔화";
  }
  function sentimentSummary(values) {
    const all=values.filter(ok),cur=all[all.length-1];
    return {cur,avg:all.reduce((a,b)=>a+b,0)/all.length,rank:all.filter(v=>v<cur).length/all.length*100};
  }
  function forwardPoints(dates, price, sentiment, horizon=12) {
    const pts=[];
    for(let i=0;i<dates.length-horizon;i++)if(ok(sentiment[i])&&ok(price[i])&&ok(price[i+horizon]))
      pts.push([sentiment[i],(price[i+horizon]/price[i]-1)*100,dates[i]]);
    return pts;
  }
  function sentimentBins(pts) {
    const bins=[];for(let lo=0;lo<200;lo+=10){const v=pts.filter(p=>p[0]>=lo&&p[0]<lo+10).map(p=>p[1]).sort((x,y)=>x-y);
      if(v.length>=15)bins.push([lo+5,v[Math.floor(v.length/2)],v.length,lo]);}
    return bins;
  }
  function diffusion(series, keys, length, window=4) {
    const raw=Array.from({length},(_,i)=>{if(!i)return null;let up=0,n=0;for(const k of keys){const s=series[k];
      if(ok(s[i])&&ok(s[i-1])){n++;if(s[i]>s[i-1])up++;}}return n>=2?up/n*100:null;});
    const average=raw.map((_,i)=>{const w=raw.slice(Math.max(0,i-window+1),i+1).filter(ok);return w.length===window?w.reduce((x,y)=>x+y,0)/window:null;});
    return {raw,average};
  }
  function alignExact(targetDates, sourceDates, values, divisor=1) {
    if(!values)return targetDates.map(()=>null);
    const positions=new Map(sourceDates.map((d,i)=>[d,i]));
    return targetDates.map(d=>{const i=positions.get(d);return i!==undefined&&ok(values[i])?values[i]/divisor:null;});
  }
  function rebase(a, start, length=a.length-start) {
    const base=a[start];return Array.from({length},(_,j)=>ok(a[start+j])&&ok(base)?a[start+j]/base*100:null);
  }
function troughs(a){const out=[],W=52;for(let i=0;i<a.length;i++){if(!ok(a[i]))continue;const lo=Math.max(0,i-W),hi=Math.min(a.length-1,i+W);let isMin=true;
  for(let j=lo;j<=hi;j++){if(ok(a[j])&&a[j]<a[i]){isMin=false;break;}}
  if(isMin&&i+8<a.length&&(!out.length||i-out[out.length-1]>W)){const later=a.slice(i,Math.min(a.length,i+104)).filter(ok);if(Math.max(...later)/a[i]>1.03)out.push(i);}}return out;}
  return Object.freeze({ok,changeAt,lastOk,changeLatest,weeklyStats,alignNearby,phase,sentimentSummary,forwardPoints,sentimentBins,troughs,diffusion,alignExact,rebase});
});
