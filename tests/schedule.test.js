import test from 'node:test';
import assert from 'node:assert/strict';
import {createScheduleState,moscowToday} from '../frontend/js/schedule-state.js';
import {renderSchedule,clock,calendarLayout} from '../frontend/js/schedule.js';
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
function dom(){let focused;const element=()=>({children:[],style:{},dataset:{},events:{},attrs:{},className:'',classList:{add(){}},textContent:'',append(...children){this.children.push(...children);},replaceChildren(...children){this.children=children;},setAttribute(key,value){this.attrs[key]=value;},addEventListener(key,fn){this.events[key]=fn;},focus(){focused=this;}});return {document:{createElement:element},root:element(),get focused(){return focused;},read(node){return [node.textContent,...node.children.map(this.read.bind(this))].flat().join(' ');}};}
test('week calendar separates overlapping markers and extends its hours for early and late lessons',()=>{
 const date='2026-11-04',late={start_minute:1350,end_minute:1400};
 const days=[{date,lessons:[late,{start_minute:420,end_minute:430},{start_minute:425,end_minute:465}]},{date:'2026-11-05',lessons:[]}];
 const layout=calendarLayout(days);
 assert.equal(layout.start,420);assert.equal(layout.end,1440);
 assert.equal(layout.days[0].laneCount,2);
 assert.deepEqual(layout.days[0].events.map(x=>x.lane),[0,1,0]);
 assert.ok(layout.days[0].events.every(x=>x.height>=44&&x.top+x.height<=layout.end-layout.start));
 assert.deepEqual(layout.days[1].events,[]);assert.equal(days[0].lessons[0],late);
});
test('week controls display an empty day and open the same changed lesson without mutations',()=>{
 const d=dom(),date='2026-11-04',lesson={date,start_minute:540,end_minute:630,subject:'Дисциплина',teacher:'Преподаватель',building:'Корпус',room:'405',kind:'lecture',status:'scheduled'};
 lesson.changes=[{reason:'Новая аудитория',fields:['room_id'],before:{...lesson,room:'101'},after:{...lesson}}];
 renderSchedule(d.document,d.root,{view:'week',today:date,selected_date:date,days:[{date,lessons:[lesson]},{date:'2026-11-05',lessons:[]}]});
 const [picker,mobile,details,scroll]=d.root.children;
 assert.match(d.read(mobile),/405/);
 picker.children[1].events.click();assert.match(d.read(mobile),/Занятий нет/);assert.equal(picker.children[1].attrs['aria-pressed'],'true');
 const event=scroll.children[0].children[1].children[1].children[0];event.events.click();
 assert.match(d.read(details),/Было:.*101.*Стало:.*405/);assert.equal(d.focused,details);
 details.children.at(-1).events.click();assert.equal(details.hidden,true);assert.equal(d.focused,event);
});
test('actual renderer shows empty days, cancellation, transfer and before/after details safely',()=>{
 const d=dom();renderSchedule(d.document,d.root,{days:[{date:'2026-11-04',lessons:[]}]});assert.match(d.read(d.root),/Занятий нет/);
 const base={id:'demo',date:'2026-11-04',start_minute:540,end_minute:630,subject:'<img onerror=bad>',teacher:'Демо-преподаватель',building:'Альфа',room:'101',kind:'lecture',status:'scheduled',version:1};
 const after={...base,date:'2026-11-05',room:'202'};
 const change={fields:['date','room_id'],reason:'Перенос',before:base,after};
 renderSchedule(d.document,d.root,{days:[{date:base.date,lessons:[{...base,status:'cancelled',placement:'current',changes:[]},{...base,status:'moved',placement:'moved_from',actual:after,changes:[change]}]}]});
 const text=d.read(d.root);for(const word of ['Занятие отменено','Перенесено на','Было:','Стало:','101','202','Демо-преподаватель'])assert.ok(text.includes(word));
 assert.ok(text.includes('<img onerror=bad>')); // A literal text node, not parsed HTML.
});
