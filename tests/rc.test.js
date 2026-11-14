import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequestsState} from '../frontend/js/requests-state.js';
import {renderRequests} from '../frontend/js/requests.js';
import {createWorkspace} from '../frontend/js/mvp-state.js';

function queue(){
 let state,failure=0,document=null;const calls=[];
 const item=()=>({id:'old-request',type:'study_certificate',status:'approved',version:3,message:'Synthetic',purpose:'RC',actions:[],history:[],document});
 const request=async(path,o={})=>{
  calls.push({path,...o});
  if(o.method==='POST'){
   if(failure)throw {status:failure};
   if(path.endsWith('/sign')){document={id:'doc-id',signed_at:1,delivered_at:null};return document;}
   document={...document,delivered_at:2};return document;
  }
  if(path.endsWith('/requests'))return {items:o.query.offset==='20'?[item()]:[],offset:Number(o.query.offset),next_offset:o.query.offset==='20'?null:20};
  return item();
 };
 const controller=createRequestsState({request,publish:x=>state=x,readCsrf:()=>'csrf'});
 return {controller,calls,get state(){return state;},fail(n){failure=n;}};
}
test('MVP-02 page-two detail issues and delivers without selecting a document as request',async()=>{
 const f=queue();await f.controller.setUser({id:'staff',role:'staff'});await f.controller.page(f.state.next_offset);await f.controller.open(f.state.items[0].id);
 assert.equal(await f.controller.certificate('sign'),true);assert.equal(f.state.detail.id,'old-request');assert.equal(f.state.detail.document.id,'doc-id');
 assert.equal(await f.controller.certificate('deliver'),true);assert.equal(f.state.detail.document.delivered_at,2);
 const posts=f.calls.filter(x=>x.method==='POST');assert.deepEqual(posts.map(x=>x.path),['/api/v1/staff/requests/old-request/sign','/api/v1/staff/documents/doc-id/deliver']);
 assert.deepEqual(posts[0].body,{version:3});assert.equal(posts[0].headers['X-CSRF-Token'],'csrf');
 await f.controller.retry();assert.equal(f.calls.filter(x=>x.method==='POST').length,2);assert.equal(f.controller.certificate('sign'),false);
});
test('MVP-02 conflict/refusal never auto-retries or enables student certificate actions',async()=>{
 const f=queue();await f.controller.setUser({id:'staff',role:'staff'});await f.controller.open('old-request');f.fail(409);
 assert.equal(await f.controller.certificate('sign'),false);assert.equal(f.state.state,'error');await f.controller.retry();assert.equal(f.calls.filter(x=>x.method==='POST').length,1);
 f.fail(403);await f.controller.certificate('sign');assert.equal(f.state.state,'error');assert.equal(f.controller.certificate('deliver'),false);
 f.controller.clear();await f.controller.setUser({id:'student',role:'student'});await f.controller.open('old-request');assert.equal(f.controller.certificate('sign'),false);
});
test('MVP-02 real detail renderer exposes sign/deliver only for an approved staff certificate',()=>{
 const make=()=>({children:[],handlers:{},textContent:'',append(...nodes){this.children.push(...nodes);},replaceChildren(){this.children=[];},setAttribute(){},addEventListener(name,fn){this.handlers[name]=fn;}});
 const document={createElement:make},root=make(),actions=[];const controller={certificate:x=>actions.push(x)};
 const detail={id:'r',type:'study_certificate',status:'approved',version:3,message:'RC',history:[],actions:[],document:null};
 const all=node=>[node,...node.children.flatMap(all)];
 const show=(role='staff')=>renderRequests(document,root,{role,items:[],offset:20,next_offset:null,detail},controller);
 show();all(root).find(x=>x.textContent==='Подписать демонстрационную справку').handlers.click();assert.deepEqual(actions,['sign']);
 detail.document={id:'doc',delivered_at:null};show();all(root).find(x=>x.textContent==='Передать справку студенту').handlers.click();assert.deepEqual(actions,['sign','deliver']);
 show('student');assert.ok(!all(root).some(x=>x.textContent==='Передать справку студенту'));
});
test('MVP-03 cursor navigation preserves the old page after reading and resets on identity change',async()=>{
 let state,read=false;const calls=[];
 const request=async(path,o={})=>{
  calls.push({path,...o});if(o.method==='POST'){read=true;return {};}
  if(path.endsWith('/notifications'))return o.query?.cursor?{items:[{id:'old',read_at:read?1:null}],unread:read?100:101,next_cursor:null}:{items:[{id:'new'}],unread:read?100:101,next_cursor:'page2'};
  return {items:[]};
 };
 const c=createWorkspace({request,csrf:()=>'csrf',publish:x=>state=x});await c.identity({id:'a',role:'student'});await c.nextNotifications();
 assert.equal(state.data.notifications.items[0].id,'old');assert.equal(state.data.notifications.has_previous,true);
 await c.action('/api/v1/me/notifications/old/read');await c.refresh();assert.equal(state.data.notifications.items[0].id,'old');assert.equal(state.data.notifications.unread,100);
 c.identity(null,{suspend:true});await c.identity({id:'a',role:'student'});assert.equal(state.data.notifications.items[0].id,'old');
 await c.previousNotifications();assert.equal(state.data.notifications.items[0].id,'new');await c.nextNotifications();
 await c.identity({id:'b',role:'student'});assert.equal(state.data.notifications.items[0].id,'new');assert.equal(state.data.notifications.has_previous,false);
 assert.equal(calls.filter(x=>x.method==='POST').length,1);
});
