const { test } = require('node:test');
const assert = require('node:assert/strict');
const { JobPowerGuard } = require('../desktop/job-power.cjs');
function setup() {
  const calls = []; let id = 0;
  const guard = new JobPowerGuard({ start: kind => { calls.push(['start', kind]); return ++id; }, stop: token => calls.push(['stop', token]) });
  return { guard, calls };
}
function deferred() { let resolve, reject; const promise = new Promise((a,b) => {resolve=a;reject=b;}); return {promise,resolve,reject}; }

test('stale watchdog result cannot override a newly admitted background job', async () => {
 const {guard,calls}=setup();guard.observe('media_activity',{active:true,count:1});
 const activity=deferred(), admission=deferred();
 const polling=guard.poll(()=>guard.run('media_activity',()=>activity.promise));
 const enqueue=guard.run('start_video_job',()=>admission.promise);
 activity.resolve({active:false,count:0});admission.resolve({id:'new-job',status:'queued'});
 await Promise.all([polling,enqueue]);
 assert.equal(guard.mediaActive,true);assert.notEqual(guard.token,null);
 assert.equal(calls.filter(c=>c[0]==='stop').length,0);
 guard.observe('media_activity',{active:false,count:0});assert.equal(guard.token,null);
});
test('construction is idle; model RPC holds prevent-app-suspension until finally', async () => {
  const {guard,calls}=setup(); assert.deepEqual(calls,[]);
  const task=deferred();const running=guard.run('tutorial',()=>task.promise);
  assert.deepEqual(calls,[['start','prevent-app-suspension']]);
  task.reject(new Error('failed'));await assert.rejects(running);assert.equal(calls[1][0],'stop');
});
test('overlapping long RPCs cannot release each other', async () => {
 const {guard,calls}=setup(), a=deferred(),b=deferred();
 const first=guard.run('ask',()=>a.promise),second=guard.run('generate_quiz',()=>b.promise);
 a.resolve({});await first;assert.equal(calls.length,1);b.resolve({});await second;assert.equal(calls.length,2);
});
test('activity is authoritative and terminal individual cannot clear another running task', async () => {
 const {guard,calls}=setup();guard.observe('bootstrap',{media_jobs:[{id:'a',status:'running'},{id:'b',status:'queued'}]});
 guard.observe('media_jobs',{id:'a',status:'completed'});guard.observe('cancel_media_job',{id:'a',status:'cancelled'});
 assert.equal(guard.mediaActive,true);assert.equal(calls.length,1);
 guard.observe('media_activity',{active:false,count:0});assert.equal(guard.mediaActive,false);assert.equal(calls.length,2);
});
test('admission and retry transfer RPC protection to background queue', async () => {
 for (const action of ['start_video_job','import_local_media','retry_media_job']) {
 const {guard,calls}=setup();await guard.run(action,async()=>({id:'a',status:'queued'}));
 assert.equal(calls.length,1);guard.observe('media_activity',{active:false,count:0});assert.equal(calls.length,2);
 }
});
test('hidden-window watchdog polls once at a time and releases completed queues', async () => {
 const {guard,calls}=setup();const data=deferred();let queries=0;
 await guard.poll(async()=>{queries++;return {active:false,count:0};});assert.equal(queries,0);
 guard.observe('start_video_job',{id:'a',status:'running'});
 const first=guard.poll(()=>{queries++;return data.promise;});await guard.poll(()=>{queries++;return {active:false,count:0};});assert.equal(queries,1);
 data.resolve({active:false,count:0});await first;assert.equal(guard.mediaActive,false);assert.equal(calls.length,2);
});
test('poll failure retains protection; reset and dispose release and ignore late results', async () => {
 const {guard,calls}=setup();guard.observe('retry_media_job',{status:'running'});
 await guard.poll(async()=>{throw Error('offline');});assert.equal(calls.length,1);
 const data=deferred();const p=guard.poll(()=>data.promise);guard.reset();assert.equal(calls.length,2);
 data.resolve({active:true,count:1});await p;assert.equal(calls.length,2);
 guard.observe('media_jobs',[{status:'running'}]);guard.dispose();assert.equal(calls.length,4);
 guard.observe('media_jobs',[{status:'running'}]);assert.equal(calls.length,4);
});
test('ordinary reads do not block; sync and model connectivity calls do', async () => {
 const {guard,calls}=setup();await guard.run('document',async()=>({}));assert.equal(calls.length,0);
 for(const action of ['sync_mem0','build_index','test_model']) await guard.run(action,async()=>({}));assert.equal(calls.length,6);
});

test('grading, related and semantic search RPCs are protected too', async () => {
 const {guard,calls}=setup();
 for(const action of ['submit_quiz','related','search']) await guard.run(action,async()=>({}));
 assert.equal(calls.length,6);
});
test('background queue retains blocker after model finishes, reset ignores late RPC', async () => {
 const {guard,calls}=setup();const task=deferred();const running=guard.run('ask',()=>task.promise);
 guard.observe('media_jobs',[{status:'running'}]);task.resolve({});await running;assert.equal(calls.length,1);
 guard.observe('media_activity',{active:false,count:0});assert.equal(calls.length,2);
 const late=deferred();const p=guard.run('start_video_job',()=>late.promise);guard.reset();
 late.resolve({status:'running'});await p;assert.equal(guard.mediaActive,false);assert.equal(guard.inflight,0);
 assert.equal(calls.length,4);
});

test('200 terminal history rows cannot release a hidden older running task', () => {
 const {guard,calls}=setup();guard.observe('start_video_job',{status:'running'});
 const history=Array.from({length:200},()=>({status:'cancelled'}));
 guard.observe('media_jobs',history);guard.observe('bootstrap',{media_jobs:history});
 assert.equal(guard.mediaActive,true);assert.equal(calls.length,1);
 guard.observe('media_activity',{active:true,count:1});assert.equal(calls.length,1);
 guard.observe('media_activity',{active:false,count:0});assert.equal(calls.length,2);
});
test('only explicit authoritative booleans can clear activity', () => {
 const {guard,calls}=setup();guard.observe('bootstrap',{media_active:true,media_jobs:[]});
 assert.equal(calls.length,1);
 guard.observe('media_activity',{active:0});guard.observe('bootstrap',{media_active:null,media_jobs:[]});
 assert.equal(calls.length,1);
 guard.observe('bootstrap',{media_active:false,media_jobs:[]});assert.equal(calls.length,2);
});
