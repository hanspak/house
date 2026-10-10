(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.RunStatus=api;})(globalThis,function(){
 'use strict';
 // 게시된 화면에서 GitHub Actions 실행 기록을 읽어, 자료 수집이 지금 진행 중인지·마지막 결과가 무엇인지 보여 준다.
 // 화면에 들어간 자료(수집일)와 별개로 "지금" 상태를 알려 주는 용도다. 인증 없이 공개 API(시간당 60회)를 쓴다.
 const WORKFLOW='dashboard.yml',BOT='github-actions[bot]';
 const STEPS=[['전국 실거래','실거래'],['R-ONE trade','R-ONE 거래량'],['R-ONE unsold','R-ONE 미분양'],['ECOS','ECOS 금리'],['공식 미분양','공식 미분양'],['공급 단계','공급 단계'],['입주예정','입주예정'],['전월세','전월세']];
 const label=name=>(STEPS.find(([k])=>name.includes(k))||[])[1];
 function repo(loc){
  const host=loc?.hostname||'',seg=(loc?.pathname||'').split('/').filter(Boolean)[0];
  return host.endsWith('.github.io')&&seg?host.split('.')[0]+'/'+seg:'hanspak/house';
 }
 const kst=s=>s?new Date(s).toLocaleString('sv-SE',{timeZone:'Asia/Seoul'}).slice(0,16):'';
 // 수집 실행 = 예약 실행 또는 사람이 누른 수동 실행. 수집 후 자동으로 뜨는 게시 전용 실행(봇이 시작)은 제외한다.
 const isCollection=r=>r.event==='schedule'||(r.event==='workflow_dispatch'&&r.triggering_actor?.login!==BOT);
 const isPublish=r=>r.event==='workflow_dispatch'&&r.triggering_actor?.login===BOT;
 function summarize(runs,jobs,now){
  const run=runs.find(isCollection);
  if(!run)return {state:'none',text:'최근 수집 실행 기록이 없습니다.'};
  const collect=(jobs||[]).filter(j=>j.name==='refresh'||j.name==='housing');
  const steps=collect.flatMap(j=>j.steps||[]).filter(s=>label(s.name));
  // 수집 단계는 continue-on-error라 시간 초과·실패도 API에는 success로 남는다. 자료별 성패는 수집 실행 상태 표(collection_runs 기록)를 본다.
  const running=steps.find(s=>s.status==='in_progress');
  const refresh=collect.find(j=>j.name==='refresh');
  const published=refresh?.steps?.find(s=>s.name.includes('게시용 집계'));
  const publish=runs.find(r=>isPublish(r)&&r.created_at>=run.created_at);
  const started=kst(run.run_started_at||run.created_at);
  if(run.status!=='completed'&&(!collect.length||collect.some(j=>j.status!=='completed'))){
   const minutes=Math.max(0,Math.round((now-new Date(run.run_started_at||run.created_at))/60000));
   const current=running?label(running.name):published?.status==='in_progress'?'실거래 게시용 집계 저장':'';
   return {state:'running',url:run.html_url,text:'수집 진행 중 · '+started+' 시작('+minutes+'분 경과)'+(current?' · 현재 단계: '+current:collect.length?'':' · 화면 게시 후 수집 시작 예정')};
  }
  const parts=['마지막 수집 실행 '+started+' 시작'];
  const ran=collect.length&&!collect.every(j=>j.conclusion==='skipped'||j.conclusion==='cancelled');
  parts.push(ran?'수집 단계 끝남':'수집 단계 미실행('+(run.conclusion||run.status)+')');
  if(published?.conclusion==='skipped')parts.push('실거래 수집 실패로 이번 실행에서 반영 안 됨');
  if(publish)parts.push(publish.status==='completed'?(publish.conclusion==='success'?'화면 반영 '+kst(publish.updated_at):'화면 반영 실행 '+publish.conclusion):'화면 반영 중');
  else if(collect.some(j=>j.conclusion==='success'))parts.push('화면 반영 대기');
  return {state:ran?'done':'idle',url:run.html_url,text:parts.join(' · ')};
 }
 async function load(el,opts={}){
  const base='https://api.github.com/repos/'+repo(opts.location||globalThis.location);
  const get=async u=>{const r=await fetch(base+u,{headers:{Accept:'application/vnd.github+json'}});if(!r.ok)throw new Error(String(r.status));return r.json();};
  let result;
  try{
   const runs=(await get('/actions/workflows/'+WORKFLOW+'/runs?per_page=20')).workflow_runs||[];
   const run=runs.find(isCollection);
   const jobs=run?(await get('/actions/runs/'+run.id+'/jobs?per_page=50')).jobs:[];
   result=summarize(runs,jobs,Date.now());
  }catch(e){result={state:'error',text:'수집 실행 상태를 불러오지 못했습니다(GitHub 요청 제한일 수 있음). 잠시 후 새로고침하세요.'};}
  el.textContent='';
  el.append('지금 수집 상태: '+result.text);
  if(result.url){const a=document.createElement('a');a.href=result.url;a.target='_blank';a.rel='noopener';a.textContent='실행 기록';el.append(' · ',a);}
  el.dataset.state=result.state;
  // 진행 중이면 3분마다 다시 읽는다(요청 2회씩, 시간당 40회로 공개 API 제한 이내).
  clearTimeout(el._runStatusTimer);
  if(result.state==='running')el._runStatusTimer=setTimeout(()=>load(el,opts),180000);
  return result;
 }
 return Object.freeze({repo,summarize,load});
});
