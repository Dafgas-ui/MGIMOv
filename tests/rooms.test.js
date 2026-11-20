import test from 'node:test';
import assert from 'node:assert/strict';
import {createRoomSearch} from '../frontend/js/rooms-state.js';
import {renderRooms,announceRoomSearch} from '../frontend/js/rooms.js';

test('room live status announces count, unknown rules, empty results and errors',()=>{
 const status={textContent:''};
 announceRoomSearch(status,{state:'loading'});assert.equal(status.textContent,'Загрузка…');
 announceRoomSearch(status,{state:'ready',data:{items:[{access_rules:'known'},{access_rules:'unknown'}]}});
 assert.equal(status.textContent,'Найдено аудиторий: 2. Режим доступа не подтверждён: 1.');
 announceRoomSearch(status,{state:'ready',data:{items:[{access_rules:'known'}]}});
 assert.equal(status.textContent,'Найдено аудиторий: 1. Режим доступа не подтверждён: 0.');
 announceRoomSearch(status,{state:'ready',data:{items:[]}});assert.equal(status.textContent,'Подходящих аудиторий нет.');
 announceRoomSearch(status,{state:'error',status:503});assert.equal(status.textContent,'Поиск не выполнен. Проверьте дату, интервал и доступ.');
 announceRoomSearch(status,{state:'ready',catalogue:true,data:{buildings:[]}});assert.equal(status.textContent,'');
 announceRoomSearch(status,{state:'hidden'});assert.equal(status.textContent,'');
});

test('room search sends real filters, clears errors and handles only current protected 401',async()=>{
 let state,expired=0;const calls=[];
 const controller=createRoomSearch({publish:s=>state=s,expired:()=>expired++,request:async(path,options)=>{
  calls.push({path,options});if(options.query?.fail)throw {status:401};return path.endsWith('catalogue')?{buildings:[]}:{items:[]};
 }});
 await controller.setUser({id:'A',role:'student'});assert.equal(state.catalogue,true);
 await controller.search({date:'2027-03-01',start:'10:00',end:'11:00'});
 assert.equal(state.state,'ready');assert.equal(calls[1].options.headers['X-Mgimov-User'],'A');
 assert.equal(calls[1].options.query.start,'10:00');
 await controller.search({fail:true});assert.equal(expired,1);assert.equal(state.state,'hidden');
 await controller.setUser({id:'S',role:'staff'});assert.equal(calls.length,3);
});
test('late room data and 401 never cross an account boundary; failed searches remove old results',async()=>{
 for(const failure of [false,true]){
  let finish,state,expired=0;
  const c=createRoomSearch({publish:s=>state=s,expired:()=>expired++,request:(path)=>path.endsWith('catalogue')?Promise.resolve({buildings:[]}):new Promise((resolve,reject)=>finish=()=>failure?reject({status:401}):resolve({items:[{id:'A'}]}))});
  await c.setUser({id:'A',role:'student'});const pending=c.search({});assert.equal(state.state,'loading');
  await c.setUser({id:'B',role:'student'});finish();await pending;
  assert.equal(state.catalogue,true);assert.equal(expired,0);assert.equal(state.data.items,undefined);
 }
 let state;const c=createRoomSearch({publish:s=>state=s,expired(){},request:async path=>{if(path.endsWith('availability'))throw {status:503};return {buildings:[]};}});
 await c.setUser({id:'A',role:'student'});await c.search({});assert.equal(state.state,'error');assert.equal(state.data,undefined);
});
test('room renderer separates unknown access, renders literal names and empty state',()=>{
 const node=()=>({textContent:'',children:[],append(...v){this.children.push(...v);},replaceChildren(){this.children=[];}});
 const document={createElement:node},output=node(),read=n=>n.textContent+n.children.map(read).join(' ');
 renderRooms(document,output,[{number:'<img onerror=alert(1)>',building:'B',capacity:20,access_rules:'known'},{number:'2',building:'C',capacity:30,access_rules:'unknown'}]);
 assert.equal(output.children.length,2);assert.match(read(output),/Режим доступа не подтверждён/);assert.match(read(output),/<img onerror=alert\(1\)>/);
 renderRooms(document,output,[]);assert.match(read(output),/Подходящих аудиторий нет/);
});
