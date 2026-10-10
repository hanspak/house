const test=require('node:test'),assert=require('node:assert/strict');
const R=require('../scripts/run_status.js');
const run=(o)=>({id:1,event:'schedule',status:'completed',conclusion:'success',created_at:'2026-10-10T04:51:30Z',run_started_at:'2026-10-10T04:51:30Z',html_url:'u',triggering_actor:{login:'hanspak'},...o});
const job=(name,o,steps=[])=>({name,status:'completed',conclusion:'success',...o,steps});
const step=(name,status='completed',conclusion='success')=>({name,status,conclusion});
test('repo comes from the GitHub Pages address',()=>{
 assert.equal(R.repo({hostname:'someone.github.io',pathname:'/house/trades.html'}),'someone/house');
 assert.equal(R.repo({hostname:'localhost',pathname:'/'}),'hanspak/house');
});
test('running collection names the current step and elapsed minutes',()=>{
 const r=R.summarize([run({status:'in_progress',conclusion:null})],[job('refresh',{status:'in_progress',conclusion:null},[step('전국 실거래 갱신 (최대 35분)','in_progress',null)])],Date.parse('2026-10-10T05:21:30Z'));
 assert.equal(r.state,'running');assert.match(r.text,/30분 경과/);assert.match(r.text,/현재 단계: 실거래/);
});
test('before collection jobs exist the run is still shown as running',()=>{
 const r=R.summarize([run({status:'in_progress',conclusion:null})],[job('build',{status:'in_progress',conclusion:null})],Date.parse('2026-10-10T04:52:30Z'));
 assert.equal(r.state,'running');assert.match(r.text,/수집 시작 예정/);
});
test('push and bot publish-only runs are not collection runs',()=>{
 const runs=[run({id:3,event:'workflow_dispatch',triggering_actor:{login:'github-actions[bot]'},created_at:'2026-10-10T05:40:00Z',updated_at:'2026-10-10T05:43:00Z'}),run({id:2,event:'push'}),run()];
 const r=R.summarize(runs,[job('refresh',{},[step('ECOS rates'),step('완전한 전국 자료를 게시용 집계로 저장')]),job('housing')],0);
 assert.equal(r.state,'done');assert.match(r.text,/수집 단계 끝남/);assert.match(r.text,/화면 반영 2026-10-10 14:43/);
});
test('skipped publish step means trades were not reflected',()=>{
 const r=R.summarize([run()],[job('refresh',{conclusion:'failure'},[step('완전한 전국 자료를 게시용 집계로 저장','completed','skipped')])],0);
 assert.match(r.text,/실거래 수집 실패/);assert.match(r.text,/화면 반영 대기|반영 안 됨/);
});
test('cancelled collection jobs are reported as not run',()=>{
 const r=R.summarize([run({conclusion:'cancelled'})],[job('refresh',{conclusion:'cancelled'}),job('housing',{conclusion:'cancelled'})],0);
 assert.equal(r.state,'idle');assert.match(r.text,/수집 단계 미실행\(cancelled\)/);
});
