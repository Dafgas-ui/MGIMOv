import test from 'node:test';
import assert from 'node:assert/strict';
import {createAcademicsState} from '../frontend/js/academics-state.js';
import {renderAcademics} from '../frontend/js/academics.js';
const empty=()=>({semesters:[],upcoming:[],debts:[],current_semester:null,progress:{state:'no_data',total:0,completed:0,upcoming:0,debts:0,pending:0,percent:null}});
function dom(){const element=()=>({children:[],textContent:'',setAttribute(){},append(...nodes){this.children.push(...nodes);},replaceChildren(){this.children=[];}});return {document:{createElement:element},root:element(),read(node){return [node.textContent,...node.children.map(this.read.bind(this))].flat().join(' ');}};}
test('gradebook is owner-bound, clears on logout and hides staff',async()=>{
 let state;const calls=[];const c=createAcademicsState({request:async(path,options)=>{calls.push({path,options});return empty();},publish:s=>state=s});
 await c.setUser({id:'A',role:'student'});assert.equal(state.state,'ready');assert.equal(calls[0].options.headers['X-Mgimov-User'],'A');
 assert.equal(calls[0].path,'/api/v1/me/gradebook');c.clear();assert.equal(state.state,'hidden');assert.equal(state.data,undefined);
 await c.setUser({id:'staff',role:'staff'});assert.equal(state.state,'hidden');assert.equal(calls.length,1);
});
test('old response cannot restore grades after account switch',async()=>{
 let state,release;const hold=new Promise(r=>release=r);let count=0;
 const c=createAcademicsState({publish:s=>state=s,request:async()=>{if(++count===1){await hold;return {...empty(),marker:'A'};}return {...empty(),marker:'B'};}});
 const pending=c.setUser({id:'A',role:'student'});c.clear();await c.setUser({id:'B',role:'student'});release();await pending;assert.equal(state.data.marker,'B');
});
test('API failures, invalid data and timeout remove old academic data',async()=>{
 for(const status of [401,403,503]){
  let state;let fail=false;const c=createAcademicsState({publish:s=>state=s,request:async()=>{if(fail)throw {status};return empty();}});
  await c.setUser({id:'A',role:'student'});fail=true;await c.retry();assert.equal(state.state,'error');assert.equal(state.data,undefined);
 }
 let state;const c=createAcademicsState({timeoutMs:5,publish:s=>state=s,request:async(path,{signal})=>new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(new Error('timeout'))))});
 await c.setUser({id:'A',role:'student'});assert.equal(state.state,'error');assert.equal(state.data,undefined);
 const invalid=createAcademicsState({publish:s=>state=s,request:async()=>({})});await invalid.setUser({id:'A',role:'student'});assert.equal(state.state,'error');
});
test('renderer gives no-data state without invented 100 percent',()=>{
 const d=dom();renderAcademics(d.document,d.root,empty());const text=d.read(d.root);
 assert.match(text,/Нет данных о текущей сессии/);assert.match(text,/Нет данных об успеваемости/);assert.doesNotMatch(text,/100%/);
});
test('renderer shows semesters, retakes, future exam and debt using literal text',()=>{
 const d=dom();const failed={id:'B',subject:'<img src=x onerror=bad>',control:'exam',status:'failed',scheduled_on:'2026-11-02',deadline_on:null,required:true,attempts:[{number:1,outcome:'graded',grade:2,performed_on:'2026-11-02',recorded_at:1793793600}]};
 const passed={...failed,id:'A',control:'credit',status:'passed',attempts:[{...failed.attempts[0],outcome:'fail',grade:null},{...failed.attempts[0],number:2,outcome:'pass',grade:null}]};
 const future={...failed,id:'C',control:'graded_credit',status:'upcoming',scheduled_on:'2026-11-14',attempts:[]};
 renderAcademics(d.document,d.root,{...empty(),current_semester:{name:'Осенний'},progress:{state:'ready',total:3,completed:1,upcoming:1,debts:1,pending:0,percent:33},upcoming:[future],debts:[failed],semesters:[{name:'Предыдущий',starts_on:'2026-01-01',ends_on:'2026-06-30',items:[passed]},{name:'Осенний',starts_on:'2026-07-01',ends_on:'2026-12-31',items:[failed,future]}]});
 const text=d.read(d.root);for(const label of ['33%','завершено 1 из 3','Предыдущий','Осенний','Зачёт','Экзамен','Дифференцированный зачёт','Оценка: 2','Не зачтено','Попытка 2','Зачтено','Неудовлетворительный результат','Предстоит','Результат отсутствует','<img src=x onerror=bad>'])assert.ok(text.includes(label),label);
});
