import test from 'node:test';
import assert from 'node:assert/strict';
import {createScheduleState,moscowToday} from '../frontend/js/schedule-state.js';
import {renderSchedule,clock} from '../frontend/js/schedule.js';
function fixture(){let state,fail=0,held=null;const calls=[];
 const request=async(path,o)=>{calls.push(o);if(held){const p=held;held=null;await p;}if(fail)throw Object.assign(new Error(),{status:fail});return {view:o.query.view,selected_date:o.query.date,group:{name:'ДЕМО'},days:[]};};
 const c=createScheduleState({request,publish:s=>state=s,today:()=> '2026-11-04'});
 return {c,calls,get state(){return state;},fail(n){fail=n;},hold(p){held=p;}};
}
test('today/week date navigation and year boundary use selected student',async()=>{
 const f=fixture();await f.c.setUser({id:'A',role:'student'});assert.equal(f.calls[0].headers['X-Mgimov-User'],'A');
 await f.c.setView('week');await f.c.setDate('2027-01-03');await f.c.move(1);
 assert.equal(f.state.selected,'2027-01-04');assert.equal(f.state.view,'week');
 await f.c.move(-1);assert.equal(f.state.selected,'2026-12-28');
 await f.c.today();assert.equal(f.state.selected,'2026-11-04');
 await f.c.setUser({id:'B',role:'student'});assert.equal(f.state.view,'today');
});
test('Moscow today changes before UTC midnight',()=>{
 assert.equal(moscowToday(new Date('2026-11-04T21:01:00Z')),'2026-11-05');assert.equal(clock(1440),'24:00');
});
test('errors, hidden state and stale response do not expose former schedule',async()=>{
 const f=fixture();await f.c.setUser({id:'A',role:'student'});
 for(const code of [401,403,503]){f.fail(code);await f.c.retry();assert.equal(f.state.state,'error');assert.equal(f.state.data,undefined);}
 f.fail(0);let release;f.hold(new Promise(r=>release=r));const pending=f.c.retry();f.c.clear();release();await pending;assert.equal(f.state.state,'hidden');
 await f.c.setUser({id:'staff',role:'staff'});assert.equal(f.state.state,'hidden');
});
function dom(){const texts=[];const element=()=>({children:[],className:'',classList:{add(){}},textContent:'',append(...children){this.children.push(...children);},replaceChildren(){this.children=[];}});return {document:{createElement:element},root:element(),read(node){return [node.textContent,...node.children.map(this.read.bind(this))].flat().join(' ');}};}
test('actual renderer shows empty days, cancellation, transfer and before/after details safely',()=>{
 const d=dom();renderSchedule(d.document,d.root,{days:[{date:'2026-11-04',lessons:[]}]});assert.match(d.read(d.root),/Занятий нет/);
 const base={id:'demo',date:'2026-11-04',start_minute:540,end_minute:630,subject:'<img onerror=bad>',teacher:'Демо-преподаватель',building:'Альфа',room:'101',kind:'lecture',status:'scheduled',version:1};
 const after={...base,date:'2026-11-05',room:'202'};
 const change={fields:['date','room_id'],reason:'Перенос',before:base,after};
 renderSchedule(d.document,d.root,{days:[{date:base.date,lessons:[{...base,status:'cancelled',placement:'current',changes:[]},{...base,status:'moved',placement:'moved_from',actual:after,changes:[change]}]}]});
 const text=d.read(d.root);for(const word of ['Занятие отменено','Перенесено на','Было:','Стало:','101','202','Демо-преподаватель'])assert.ok(text.includes(word));
 assert.ok(text.includes('<img onerror=bad>')); // A literal text node, not parsed HTML.
});
