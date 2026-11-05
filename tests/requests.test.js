import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequestsState} from '../frontend/js/requests-state.js';
import {renderRequests} from '../frontend/js/requests.js';
import {createRequestOperations} from '../frontend/js/request-operation.js';
const item=(status='submitted')=>({id:'a'.repeat(32),type:'appeal',purpose:'',message:'Демонстрация',status,version:1,created_at:1800000000,history:[],actions:['cancel']});
function fixture(){let state,fail=0,held=null,created=item(),keys=0;const calls=[];
 const request=async(path,o={})=>{calls.push({path,...o});if(held){const p=held;held=null;await p;}if(fail)throw {status:fail};if(o.method==='POST')return created;if(path.endsWith('/'+created.id))return created;return {items:[created],offset:0,next_offset:null};};
 const c=createRequestsState({request,publish:s=>state=s,readCsrf:()=> 'csrf-memory',newKey:()=>String(++keys).padStart(32,'0')});
 return {c,calls,get state(){return state;},fail(code){fail=code;},hold(p){held=p;},detail(v){created=v;}};
}
test('create, own detail, headers, cancel version and double click lock',async()=>{
 const f=fixture();await f.c.setUser({id:'A',role:'student'});
 let release;f.hold(new Promise(r=>release=r));const pending=f.c.create({type:'appeal',purpose:'ignored',message:' Text '});
 assert.equal(await f.c.create({type:'appeal',purpose:'',message:'Text'}),false);release();await pending;
 const post=f.calls.find(c=>c.method==='POST');assert.equal(post.path,'/api/v1/me/requests');assert.equal(post.body.message,'Text');assert.equal(post.body.purpose,'');assert.equal(post.headers['X-Mgimov-User'],'A');assert.equal(post.headers['X-CSRF-Token'],'csrf-memory');
 await f.c.change('cancel','Отмена');const cancel=f.calls.filter(c=>c.method==='POST').at(-1);assert.equal(cancel.body.version,1);assert.ok(cancel.path.endsWith('/cancel'));
});
test('uncertain send retries same key; changed contents get a new key',async()=>{
 const f=fixture();await f.c.setUser({id:'A',role:'student'});f.fail(503);
 const payload={type:'appeal',purpose:'',message:'Демо'};await f.c.create(payload);assert.equal(f.state.state,'error');
 f.fail(0);await f.c.create(payload);const posts=f.calls.filter(c=>c.method==='POST');assert.equal(posts[0].body.request_key,posts[1].body.request_key);
 await f.c.create({...payload,message:'Другой вопрос'});assert.notEqual(f.calls.filter(c=>c.method==='POST').at(-1).body.request_key,posts[0].body.request_key);
});
test('staff uses separate queue and only server-provided actions',async()=>{
 const f=fixture();f.detail({...item('processing'),version:2,actions:['approved','rejected']});await f.c.setUser({id:'S',role:'staff'});await f.c.open('a'.repeat(32));
 const count=f.calls.length;await f.c.change('processing','invalid');assert.equal(f.calls.length,count);
 await f.c.change('rejected','Причина');const post=f.calls.find(c=>c.method==='POST');assert.ok(post.path.startsWith('/api/v1/staff/requests/'));assert.equal(post.body.version,2);assert.equal(post.body.action,'rejected');
 await f.c.create({type:'appeal',purpose:'',message:'No'});assert.equal(f.calls.filter(c=>c.method==='POST').length,1);
});
test('late results are discarded on logout, account switch and refresh suspension',async()=>{
 const f=fixture();await f.c.setUser({id:'A',role:'student'});let release;f.hold(new Promise(r=>release=r));const old=f.c.open('a'.repeat(32));f.c.clear();await f.c.setUser({id:'B',role:'student'});release();await old;
 assert.equal(f.calls.at(-1).headers['X-Mgimov-User'],'B');f.c.suspend();assert.equal(f.state.state,'suspended');assert.equal(f.state.items,undefined);await f.c.setUser({id:'B',role:'student'});assert.equal(f.state.state,'ready');f.c.clear();assert.equal(f.state.state,'hidden');
});
test('errors and timeout hide prior records; pagination is requested explicitly',async()=>{
 const f=fixture();await f.c.setUser({id:'A',role:'student'});await f.c.page(20);assert.equal(f.calls.at(-1).query.offset,'20');
 for(const code of [401,403,409,422,429,503]){f.fail(code);await f.c.retry();assert.equal(f.state.state,'error');assert.equal(f.state.items,undefined);}
 let state;const c=createRequestsState({request:async(path,{signal})=>new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(new Error('timeout')))),publish:s=>state=s,timeoutMs:5});await c.setUser({id:'A',role:'student'});assert.equal(state.state,'error');
});
function dom(){const element=()=>({children:[],textContent:'',setAttribute(){},addEventListener(){},append(...nodes){this.children.push(...nodes);},replaceChildren(){this.children=[];}});return {document:{createElement:element},root:element(),read(node){return [node.textContent,...node.children.map(this.read.bind(this))].flat().join(' ');}};}
test('renderer shows empty lists, status, author and literal user/staff text',()=>{
 const d=dom();const controller={open(){},page(){},change(){}};renderRequests(d.document,d.root,{role:'student',items:[],offset:0,next_offset:null},controller);assert.match(d.read(d.root),/пока нет/);
 const detail={...item('rejected'),message:'<img src=x onerror=bad>',actions:[],history:[{to_status:'rejected',actor_role:'staff',actor_name:'Демо-сотрудник',comment:'<script>bad</script>',created_at:1800000000}]};
 renderRequests(d.document,d.root,{role:'student',items:[detail],detail,offset:0,next_offset:null},controller);const text=d.read(d.root);
 for(const expected of ['Отклонено','Демо-сотрудник','<img src=x onerror=bad>','<script>bad</script>','История обработки'])assert.ok(text.includes(expected));
});

function recoveryFixture(){
 const entries=new Map(),storage={getItem:k=>entries.get(k)??null,setItem:(k,v)=>entries.set(k,v),removeItem:k=>entries.delete(k)};
 const operations=createRequestOperations({getStorage:()=>storage});
 const rows=new Map(),calls=[];let drop=false,state;
 const request=async(path,o={})=>{
  calls.push({path,...o});
  if(o.method==='POST'){
   const old=rows.get(o.body.request_key),body=JSON.stringify([o.body.type,o.body.purpose,o.body.message]);
   if(old && old.body!==body)throw {status:409};
   if(!old)rows.set(o.body.request_key,{body,item:{...item(),id:crypto.randomUUID().replaceAll('-','')}});
   if(drop){drop=false;throw new Error('response lost after commit');}
   return rows.get(o.body.request_key).item;
  }
  if(path.split('/').at(-1)!=='requests')return [...rows.values()].find(x=>path.endsWith(x.item.id))?.item;
  return {items:[...rows.values()].map(x=>x.item),offset:0,next_offset:null};
 };
 const controller=()=>createRequestsState({request,operations,readCsrf:()=> 'memory-only',publish:s=>state=s});
 return {entries,operations,rows,calls,controller,get state(){return state;},drop(){drop=true;}};
}
test('AUD-02 response loss, controller reload and repeat keep one server record',async()=>{
 const f=recoveryFixture(),payload={type:'appeal',purpose:'',message:'Synthetic text must not be stored'};
 const a=f.controller();await a.setUser({id:'private-owner-A',role:'student'});f.drop();await a.create(payload);
 assert.equal(f.rows.size,1);assert.equal(f.state.state,'error');
 const stored=[...f.entries.values()].join('');assert.ok(!stored.includes(payload.message));assert.ok(!stored.includes('private-owner-A'));
 const metadata=JSON.parse(stored);assert.deepEqual(Object.keys(metadata).sort(),['expiresAt','key','tag','type','v']);
 a.clear();const reloaded=f.controller();await reloaded.setUser({id:'private-owner-A',role:'student'});assert.ok(f.state.recovery);
 await reloaded.create(payload);assert.equal(f.rows.size,1);assert.equal(f.entries.size,0);
 const posts=f.calls.filter(c=>c.method==='POST');assert.ok(posts[0].body.request_key===posts[1].body.request_key);
 assert.ok(f.calls.every(c=>!c.path.includes(metadata.key)));
 await reloaded.create(payload);assert.equal(f.rows.size,2); // Confirmed previous operation, deliberate new send.
});
test('AUD-02 changed content conflicts; explicit new intention creates a separate request',async()=>{
 const f=recoveryFixture(),payload={type:'appeal',purpose:'',message:'First demo'};let c=f.controller();await c.setUser({id:'A',role:'student'});f.drop();await c.create(payload);
 c=f.controller();await c.setUser({id:'A',role:'student'});await c.create({...payload,message:'Changed demo'});
 assert.equal(f.state.state,'error');assert.equal(f.rows.size,1);assert.ok(f.entries.size);
 const count=f.calls.length;await c.create({type:'study_certificate',purpose:'Demo',message:'Other type'});assert.equal(f.calls.length,count);assert.equal(f.rows.size,1);
 assert.ok(c.newOperation());await c.create({...payload,message:'Changed demo'});assert.equal(f.rows.size,2);
});
test('AUD-02 metadata is account-bound and discarded on explicit logout',async()=>{
 const f=recoveryFixture(),payload={type:'appeal',purpose:'',message:'Demo'};let c=f.controller();await c.setUser({id:'A',role:'student'});f.drop();await c.create(payload);
 c.clear();c=f.controller();await c.setUser({id:'B',role:'student'});assert.equal(f.state.recovery,null);assert.equal(f.entries.size,0);
 f.drop();await c.create(payload);c.clear({discardOperation:true});assert.equal(f.entries.size,0);
});
test('AUD-02 expired, corrupt or denied storage never silently submits a new operation',async()=>{
 const data=new Map(),storage={getItem:k=>data.get(k)??null,setItem:(k,v)=>data.set(k,v),removeItem:k=>data.delete(k)};let now=1000;
 const operations=createRequestOperations({getStorage:()=>storage,now:()=>now});
 await operations.save('A','appeal',crypto.randomUUID().replaceAll('-',''));now+=86400001;
 assert.equal((await operations.restore('A')).state,'lost');
 storage.setItem([...data.keys()][0],'{bad');assert.equal((await operations.restore('A')).state,'unavailable');
 let posts=0,state;const denied=createRequestOperations({getStorage:()=>{throw new Error('denied');}});
 const c=createRequestsState({operations:denied,request:async(p,o)=>{if(o.method==='POST')posts++;return {items:[],offset:0,next_offset:null};},publish:s=>state=s});
 await c.setUser({id:'A',role:'student'});c.newOperation();await c.create({type:'appeal',purpose:'',message:'Demo'});assert.equal(posts,0);assert.equal(state.state,'error');
});
test('AUD-01 staff draft survives manual/background suspend and stays per request/owner',async()=>{
 const f=fixture();f.detail({...item('processing'),actions:['approved','rejected']});await f.c.setUser({id:'S',role:'staff'});await f.c.open('a'.repeat(32));
 f.c.setDraft('a'.repeat(32),'Unfinished staff comment');f.c.suspend();await f.c.setUser({id:'S',role:'staff'});
 assert.equal(f.c.getDraft('a'.repeat(32)),'Unfinished staff comment');
 f.c.suspend();await f.c.setUser({id:'S',role:'staff'});assert.equal(f.c.getDraft('a'.repeat(32)),'Unfinished staff comment');
 await f.c.open('b'.repeat(32));assert.equal(f.c.getDraft('b'.repeat(32)),'');
 await f.c.setUser({id:'other-staff',role:'staff'});assert.equal(f.c.getDraft('a'.repeat(32)),'');
 f.c.clear();assert.equal(f.c.getDraft('a'.repeat(32)),'');
});
test('AUD-01 409/network retain draft without resending, confirmed action clears it',async()=>{
 const f=fixture();f.detail({...item('processing'),actions:['approved','rejected']});await f.c.setUser({id:'S',role:'staff'});await f.c.open('a'.repeat(32));
 for(const code of [409,503]){
  f.fail(code);await f.c.change('approved','Keep decision text');assert.equal(f.c.getDraft('a'.repeat(32)),'Keep decision text');
  const posts=f.calls.filter(x=>x.method==='POST').length;f.fail(0);await f.c.retry();assert.equal(f.calls.filter(x=>x.method==='POST').length,posts);
 }
 await f.c.change('approved','Keep decision text');assert.equal(f.c.getDraft('a'.repeat(32)),'');
});
test('AUD-01 real renderer restores input and exposes retained text after a terminal conflict',()=>{
 const d=dom(),elements=[];const make=d.document.createElement;d.document.createElement=()=>{const node=make();elements.push(node);return node;};
 const detail={...item('processing'),actions:['approved'],history:[]};
 const controller={getDraft:()=> 'Retained staff text',setDraft(){},change(){}};
 renderRequests(d.document,d.root,{role:'staff',items:[],detail,offset:0,next_offset:null},controller);
 assert.equal(elements.find(e=>e.id==='request-decision-comment').value,'Retained staff text');
 elements.length=0;renderRequests(d.document,d.root,{role:'staff',items:[],detail:{...detail,status:'approved',actions:[]},offset:0,next_offset:null},controller);
 const retained=elements.find(e=>e.id==='request-retained-comment');assert.equal(retained.value,'Retained staff text');assert.equal(retained.readOnly,true);
});
