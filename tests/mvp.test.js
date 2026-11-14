import test from 'node:test';
import assert from 'node:assert/strict';
import {createWorkspace} from '../frontend/js/mvp-state.js';
const user={id:'student-a',role:'student'},other={id:'student-b',role:'student'};
function fixture(request=async path=>({path,items:[]})){
  const views=[];const calls=[];
  const workspace=createWorkspace({csrf:()=>'csrf',publish:value=>views.push(value),request:(path,options)=>{calls.push({path,options});return request(path,options);}});
  return {workspace,views,calls};
}
test('workspace loads owner-bound widgets; suspension hides data and never POSTs',async()=>{
  const {workspace,views,calls}=fixture();await workspace.identity(user);
  assert.equal(views.at(-1).state,'ready');assert.equal(calls.length,5);
  assert.ok(calls.every(c=>c.options.headers['X-MGIMOv-User']===user.id));
  workspace.identity(null,{suspend:true});assert.equal(views.at(-1).state,'suspended');
  await assert.rejects(workspace.action('/api/v1/staff/notifications',{}));
  await workspace.identity(user);assert.equal(views.at(-1).state,'ready');
  assert.ok(calls.every(c=>!c.options.method));
});
test('late reply cannot restore a previous identity',async()=>{
  const pending=[];const {workspace,views}=fixture((path,options)=>new Promise(resolve=>pending.push({resolve,options})));
  const first=workspace.identity(user);workspace.identity(null);const second=workspace.identity(other);
  for(const item of pending)item.resolve({items:[]});await Promise.all([first,second]);
  assert.equal(views.at(-1).user.id,other.id);assert.equal(views.filter(v=>v.state==='ready').length,1);
});
test('network and invalid-session failures hide old data and never retry mutations',async()=>{
  let failure=null;const {workspace,views,calls}=fixture(async()=>{if(failure)throw failure;return {items:[]};});
  await workspace.identity(user);failure=new Error('offline');await workspace.refresh();assert.equal(views.at(-1).state,'error');
  failure={status:401};await workspace.refresh();assert.equal(views.at(-1).state,'anonymous');
  await assert.rejects(workspace.action('/api/v1/me/notifications/x/read'));assert.ok(calls.every(c=>!c.options.method));
});
test('staff widgets, CSRF, explicit one-shot mutation and logout denial',async()=>{
  const {workspace,calls}=fixture();await workspace.identity({id:'staff',role:'staff'});
  assert.ok(calls.some(c=>c.path==='/api/v1/staff/catalogue'));
  await workspace.action('/api/v1/staff/requests/a/sign',{version:3});
  const post=calls.find(c=>c.options.method==='POST');assert.deepEqual(post.options.body,{version:3});assert.equal(post.options.headers['X-CSRF-Token'],'csrf');
  workspace.identity(null);await assert.rejects(workspace.action('/api/v1/staff/requests/a/sign'));
  assert.equal(calls.filter(c=>c.options.method==='POST').length,1);
});
test('document response after hiding the tab is discarded',async()=>{
  let release;const {workspace}=fixture(async path=>path.includes('/documents/')?new Promise(resolve=>release=resolve):{items:[]});
  await workspace.identity(user);const response=workspace.document('a');workspace.identity(null,{suspend:true});release({content:'private'});await assert.rejects(response);
});
test('timeout hides protected widgets and session refusal disables further writes',async()=>{
  const views=[];let mode='hung';
  const workspace=createWorkspace({csrf:()=>'csrf',timeout:5,publish:x=>views.push(x),request:async()=>{if(mode==='hung')return new Promise(()=>{});if(mode==='deny')throw {status:403};return {};}});
  await workspace.identity(user);assert.equal(views.at(-1).state,'error');
  mode='ok';await workspace.refresh();assert.equal(views.at(-1).state,'ready');mode='deny';
  await assert.rejects(workspace.action('/api/v1/staff/notifications'));assert.equal(views.at(-1).state,'anonymous');
  await assert.rejects(workspace.action('/api/v1/staff/notifications'));
});
