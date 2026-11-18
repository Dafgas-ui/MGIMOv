import test from 'node:test';
import assert from 'node:assert/strict';
import {deadlineRows,createDeadlines,deadlineLifecycle} from '../frontend/js/deadlines-state.js';

const now=Date.parse('2027-02-20T12:00:00+03:00');
test('whole load budget includes a slow source followed by fast time',async()=>{
  let elapsed=0,view;
  const controller=createDeadlines({clock:()=>elapsed,publish:v=>view=v,expired(){},request:async path=>{
    if(path.endsWith('/coursework'))elapsed=5001;
    return path.endsWith('/time')?{server_time:now/1000}:path.endsWith('/gradebook')?data().gradebook:{items:[]};
  }});
  await controller.load({id:'a',role:'student'});assert.equal(view.state,'error');assert.equal(view.items,undefined);
});
test('lifecycle coalesces events and clears before delayed timer or account refresh',async()=>{
  let time=0,callback,timers=0,clears=0,loads=0,release;
  const events=[];
  const lifecycle=deadlineLifecycle({clock:()=>time,clear:()=>{clears++;events.push('clear');},
    load:()=>{loads++;events.push('load');return new Promise(r=>release=r);},
    host:{setInterval(fn){callback=fn;timers++;return 1;},clearInterval(){timers--;}}});
  const first=lifecycle.activate('A');lifecycle.resume();lifecycle.activate('A');
  assert.equal(loads,1);assert.equal(timers,1);release();await first;
  time=10000;callback();assert.equal(loads,2);assert.deepEqual(events.slice(-2),['clear','load']);
  const previous=release;lifecycle.activate('B');assert.equal(loads,3);assert.equal(timers,1);
  previous();release();await Promise.resolve();lifecycle.stop();assert.equal(timers,0);assert.ok(clears>=4);
});
test('server time is authoritative across device clock offsets, refresh and failures',async()=>{
  for(const offset of [-86400000,0,86400000]){
    let view,tick=offset;
    const sources=data();sources.coursework.items=[work('due','2027-02-20T12:00:01+03:00')];
    const controller=createDeadlines({clock:()=>tick++,expired(){},publish:v=>view=v,
      request:async path=>path.endsWith('/time')?{server_time:now/1000}:path.endsWith('/coursework')?sources.coursework:path.endsWith('/attestations')?sources.attestations:sources.gradebook});
    await controller.load({id:'a',role:'student'});assert.equal(view.state,'ready');assert.equal(view.items[0].urgency,'soon');
    controller.clear();assert.equal(view.state,'hidden');
    await controller.load({id:'a',role:'student'});assert.equal(view.state,'ready');
  }
  for(const response of [null,{server_time:NaN},{server_time:0}]){
    let view;const controller=createDeadlines({expired(){},publish:v=>view=v,request:async path=>{
      if(path.endsWith('/time')){if(response===null)throw new Error('offline');return response;}
      return path.endsWith('/gradebook')?data().gradebook:{items:[]};
    }});
    await controller.load({id:'a',role:'student'});assert.equal(view.state,'error');assert.equal(view.items,undefined);
  }
});

test('server midnight and exact deadline boundaries ignore stale gradebook day',()=>{
  const source=data();source.gradebook.exams=[{id:'day',status:'upcoming',scheduled_on:'2027-02-20',deadline_on:'2027-02-20'}];
  source.coursework.items=[work('due','2027-02-20T23:59:59+03:00')];
  const before=Date.parse('2027-02-20T23:59:58+03:00'),after=before+3000;
  assert.equal(deadlineRows(source,before).find(x=>x.id==='work:due').urgency,'soon');
  const rows=deadlineRows(source,after);
  assert.equal(rows.find(x=>x.id==='work:due').urgency,'overdue');
  assert.equal(rows.find(x=>x.id==='due:day').urgency,'overdue');
  assert.ok(!rows.some(x=>x.id==='exam:day'));
  assert.throws(()=>deadlineRows(source),/Server time/);
});

test('slow server-time response is rejected rather than using device time',async()=>{
  let ticks=0,view;
  const controller=createDeadlines({clock:()=>ticks++*6000,publish:v=>view=v,expired(){},request:async path=>
    path.endsWith('/time')?{server_time:now/1000}:path.endsWith('/gradebook')?data().gradebook:{items:[]}});
  await controller.load({id:'a',role:'student'});
  assert.equal(view.state,'error');assert.equal(view.items,undefined);
});
const data=()=>({coursework:{items:[]},attestations:{items:[]},gradebook:{today:'2027-02-20',exams:[]}});
const work=(id,at,extra={})=>({id,status:'published',needs_submission:true,due_at:Date.parse(at)/1000,
  title:'Assignment '+id,subject_name:'Math',latest_attempt_state:null,...extra});

test('deadline projection distinguishes date-only, exact time, overdue submissions and exam dates',()=>{
  const sources=data();
  sources.coursework.items=[work('late','2027-02-19T23:00:00+03:00'),work('soon','2027-02-21T10:00:00+03:00'),
    work('done','2027-02-21T10:00:00+03:00',{needs_submission:false}),
    work('draft','2027-02-21T10:00:00+03:00',{status:'draft'})];
  sources.gradebook.exams=[{id:'exam',control:'exam',subject:'Law',status:'upcoming',event_status:'scheduled',
    scheduled_on:'2027-02-21',deadline_on:'2027-02-20'},
    {id:'old',subject:'Old',status:'ungraded',scheduled_on:'2027-02-18'},
    {id:'cancelled',status:'cancelled',event_status:'cancelled',scheduled_on:'2027-02-21'},
    {id:'activated',official_result:null,scheduled_on:'2027-02-21'}];
  const rows=deadlineRows(sources,now);
  assert.equal(rows.length,4);
  assert.equal(rows.find(x=>x.id==='work:late').urgency,'overdue');
  assert.equal(rows.find(x=>x.id==='due:exam').urgency,'soon'); // Date alone is valid through the Moscow day.
  assert.equal(rows.find(x=>x.id==='exam:exam').precision,'date');
  assert.equal(rows.find(x=>x.id==='work:soon').precision,'time');
  assert.ok(rows.every(x=>x.kind!=='assessment'||x.urgency!=='overdue'));
});

test('public attestation history cancels old slots, uses rescheduled time and never needs Staff drafts',()=>{
  const sources=data();
  const slot={kind:'scheduled',slot_id:'old',starts_at:now/1000+1000,ends_at:now/1000+2000};
  sources.attestations.items=[{id:'course',control:'exam',subject:'Law',history:[slot,
    {kind:'cancelled',slot_id:'old'},{...slot,slot_id:'new',starts_at:now/1000+3000,ends_at:now/1000+4000}]}];
  const first=deadlineRows(sources,now);
  assert.deepEqual(first.map(x=>x.id),['slot:new']);
  sources.attestations.items[0].history.push({kind:'draft',slot_id:'new',grade:2});
  assert.deepEqual(deadlineRows(sources,now),first);
  sources.attestations.items[0].history.push({kind:'published',slot_id:'new',grade:5});
  assert.deepEqual(deadlineRows(sources,now),[]);
});

test('Moscow day boundaries preserve date-only meaning and ongoing assessments',()=>{
  const sources=data(),instant=Date.parse('2027-02-20T22:30:00Z');
  sources.gradebook.today='2027-02-21';
  sources.coursework.items=[work('night','2027-02-21T02:00:00+03:00')];
  sources.gradebook.exams=[{id:'date',subject:'Law',deadline_on:'2027-02-20',status:'ungraded'}];
  sources.attestations.items=[{id:'active',subject:'Math',history:[{kind:'scheduled',slot_id:'running',
    starts_at:instant/1000-60,ends_at:instant/1000+60}]}];
  const rows=deadlineRows(sources,instant);
  assert.equal(rows.find(x=>x.id==='work:night').date,'2027-02-21');
  assert.equal(rows.find(x=>x.id==='work:night').urgency,'soon');
  assert.equal(rows.find(x=>x.id==='due:date').urgency,'overdue');
  assert.equal(rows.find(x=>x.id==='slot:running').urgency,'soon');
});

test('deadlines refreshes real owner-scoped API projections and clears late responses and 401',async()=>{
  const pending=[],views=[];let expired=0;
  const controller=createDeadlines({request:(path,options)=>new Promise(resolve=>pending.push({path,options,resolve})),
    publish:value=>views.push(value),expired:()=>expired++,clock:()=>now});
  const first=controller.load({id:'alice',role:'student'});
  controller.clear();
  for(const row of pending)row.resolve({items:[],exams:[],today:'2027-02-20'});
  await first;assert.equal(views.at(-1).state,'hidden');
  assert.ok(pending.every(x=>x.options.headers['X-Mgimov-User']==='alice'));
  const denied=createDeadlines({request:async()=>{throw {status:401};},publish:value=>views.push(value),expired:()=>expired++});
  await denied.load({id:'bobby',role:'student'});assert.equal(expired,1);assert.equal(views.at(-1).state,'hidden');
  await denied.load({id:'teacher',role:'staff'});assert.equal(expired,1);
});
