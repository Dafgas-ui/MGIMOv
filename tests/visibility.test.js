// Execute the real account visibility handlers with the real requests DOM/state adapters.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {createAccountState} from '../frontend/js/account-state.js';
import {mountRequests} from '../frontend/js/requests.js';
import {requestJson} from '../frontend/js/api.js';
const tick=()=>new Promise(r=>setTimeout(r,0));
async function fixture(t,role='staff'){
 const nodes=new Map(),docEvents={},windowEvents={},timers=[],calls=[],appearanceUsers=[];
 let user={id:'owner-A',role},failure=0,scope=true,hold=null;
 function element(tag='div'){
  return {tagName:tag,children:[],value:'',hidden:false,disabled:false,textContent:'',handlers:{},
   addEventListener(name,fn){this.handlers[name]=fn;},setAttribute(){},focus(){},
   append(...children){this.children.push(...children);},replaceChildren(){this.children=[];},
   reset(){for(const id of ['request-purpose','request-message'])nodes.get(id).value='';nodes.get('request-type').value='study_certificate';}};
 }
 const find=(root,id)=>root.id===id?root:root.children.map(n=>find(n,id)).find(Boolean);
 const document={visibilityState:'visible',cookie:'',createElement:element,
  addEventListener(name,fn){docEvents[name]=fn;},
  getElementById(id){return nodes.get(id) || [...nodes.values()].map(n=>find(n,id)).find(Boolean) || null;}};
 for(const id of [...readFileSync('frontend/index.html','utf8').matchAll(/\bid="([^"]+)"/g)].map(m=>m[1])){const n=element();n.id=id;nodes.set(id,n);}
 nodes.get('request-type').value='study_certificate';
 const item={id:'a'.repeat(32),type:'appeal',purpose:'',message:'Synthetic request',status:'processing',version:2,created_at:1800000000,history:[],actions:['approved','rejected']};
 const previous=globalThis.fetch;t.after(()=>{globalThis.fetch=previous;});
 globalThis.fetch=async(url,o={})=>{
  const path=new URL(url,'http://fixture.invalid').pathname;calls.push({path,...o});
  let status=200,data;
  if(path.endsWith('/auth/me') && hold){const pending=hold;hold=null;await pending;}
  if(failure)status=failure;
  else if(path.endsWith('/auth/logout')){user=null;data={};}
  else if(!user)status=401;
  else if(o.headers?.['X-Mgimov-User'] && o.headers['X-Mgimov-User']!==user.id)status=403;
  else if(path.endsWith('/auth/me'))data={user};
  else if(path.endsWith('/me/profile'))data={user,profile:{full_name:'Synthetic owner'}};
  else if(path.endsWith('/requests'))data={items:scope?[item]:[],offset:0,next_offset:null};
  else if(path.endsWith('/'+item.id)){if(scope)data=item;else status=404;}
  else status=404;
  return new Response(JSON.stringify(data || {detail:'Synthetic error'}),{status});
 };
 const requests=mountRequests(document);
 function requestsIdentity(value,{suspend=false,discardOperation=false}={}){if(value)return requests.setUser(value);if(suspend)requests.suspend();else requests.clear({discardOperation});}
 const source=readFileSync('frontend/js/account.js','utf8').replace(/^import .*;$/gm,'');
 runInNewContext(source,{document,location:{protocol:'http:'},requestJson,createAccountState,requestsIdentity,
  mountLanguage:()=>({setUser(){}}),t:value=>value,attestationIdentity(){},
  createAppearanceState:()=>({setUser(id){appearanceUsers.push(id);},update(){},reset(){},systemThemeChanged(){}}),
  addEventListener(name,fn){windowEvents[name]=fn;},setInterval:fn=>timers.push(fn)});
 await tick();await tick();
 return {document,requests,calls,item,nodes,docEvents,windowEvents,timers,appearanceUsers,
  get:id=>document.getElementById(id),fail:n=>failure=n,user:v=>user=v,scope:v=>scope=v,
  hold(p){hold=p;},async hide(){document.visibilityState='hidden';docEvents.visibilitychange();await tick();},
  async show(){document.visibilityState='visible';docEvents.visibilitychange();await tick();await tick();},
  async open(){await requests.open(item.id);},draft(text){const field=document.getElementById('request-decision-comment');field.value=text;field.handlers.input();}};
}

test('appearance settings bind to the confirmed account and clear on server logout',async t=>{
 const f=await fixture(t,'student');
 assert.ok(f.appearanceUsers.includes('owner-A'));
 f.get('logout').handlers.click();await tick();await tick();
 assert.equal(f.appearanceUsers.at(-1),null);
 assert.ok(f.calls.some(call=>call.path.endsWith('/auth/logout')));
});

test('appearance controls do not resubmit or clear an unfinished staff comment',async t=>{
 const f=await fixture(t);await f.open();f.draft('Unsent staff comment');
 const before=f.calls.length;
 f.get('appearance-theme').value='dark';f.get('appearance-theme').handlers.change();
 f.get('appearance-palette').value='ocean';f.get('appearance-palette').handlers.change();
 f.get('appearance-custom').value='#aabbcc';f.get('appearance-custom').handlers.input();
 assert.equal(f.get('request-decision-comment').value,'Unsent staff comment');
 assert.equal(f.calls.length,before);
});

test('UX-01 real hide/show handlers retain staff text only after identity and scope checks',async t=>{
 const f=await fixture(t);await f.open();f.draft('Keep staff draft');
 await f.hide();assert.equal(f.get('requests-section').hidden,true);assert.equal(f.get('account-panel').hidden,true);assert.equal(f.get('request-decision-comment'),null);
 assert.equal(f.get('request-fields').disabled,true);await f.requests.change('approved','Must not send');await f.requests.retry();
 let release;f.hold(new Promise(r=>release=r));await f.show();assert.equal(f.get('requests-section').hidden,true);
 assert.equal(f.get('request-decision-comment'),null);release();await tick();await tick();
 assert.equal(f.get('request-decision-comment').value,'Keep staff draft');
 assert.ok(f.calls.filter(c=>c.path.endsWith('/auth/me')).at(-1).headers['X-Mgimov-User']==='owner-A');
 await f.hide();await f.show();assert.equal(f.get('request-decision-comment').value,'Keep staff draft');
 assert.equal(f.calls.filter(c=>c.method==='POST').length,0);
});
test('UX-01 expired session clears staff draft and never restores old controls',async t=>{
 const f=await fixture(t);await f.open();f.draft('Private draft');await f.hide();f.user(null);await f.show();
 assert.equal(f.requests.getDraft(f.item.id),'');assert.equal(f.get('requests-section').hidden,true);assert.equal(f.get('request-decision-comment'),null);
});
test('UX-01 changed identity invalidates drafts even when role is still staff',async t=>{
 const f=await fixture(t);await f.open();f.draft('Owner A only');await f.hide();f.user({id:'owner-B',role:'staff'});await f.show();
 assert.equal(f.requests.getDraft(f.item.id),'');assert.equal(f.get('requests-section').hidden,true);
 await f.get('account-check').handlers.click();await tick();await tick();await f.open();assert.equal(f.get('request-decision-comment').value,'');
});
test('UX-01 revoked faculty scope removes its draft after server refusal, no POST',async t=>{
 const f=await fixture(t);await f.open();f.draft('Faculty draft');await f.hide();f.scope(false);await f.show();
 assert.equal(f.requests.getDraft(f.item.id),'');assert.equal(f.get('request-decision-comment'),null);
 assert.equal(f.calls.filter(c=>c.method==='POST').length,0);
});
test('UX-01 transient network error keeps hidden draft until explicit successful refresh',async t=>{
 const f=await fixture(t);await f.open();f.draft('Network safe draft');await f.hide();f.fail(503);await f.show();
 assert.equal(f.get('requests-section').hidden,true);assert.equal(f.requests.getDraft(f.item.id),'Network safe draft');
 f.fail(0);f.get('account-check').handlers.click();await tick();await tick();assert.equal(f.get('request-decision-comment').value,'Network safe draft');
});
test('UX-01 student form survives hide/show but logout and pagehide still clear it',async t=>{
 const f=await fixture(t,'student');f.get('request-new').handlers.click();
 f.get('request-purpose').value='Synthetic purpose';f.get('request-message').value='Synthetic unsent message';
 await f.hide();assert.equal(f.get('requests-section').hidden,true);assert.equal(f.get('request-fields').disabled,true);
 await f.show();assert.equal(f.get('request-message').value,'Synthetic unsent message');assert.equal(f.get('request-purpose').value,'Synthetic purpose');
 f.windowEvents.pagehide();assert.equal(f.get('request-message').value,'');assert.equal(f.get('requests-section').hidden,true);
 f.windowEvents.pageshow({persisted:true});await tick();await tick();f.get('request-message').value='Must clear on logout';
 f.get('logout').handlers.click();await tick();await tick();assert.equal(f.get('request-message').value,'');assert.equal(f.get('requests-section').hidden,true);
});
test('UX-01 online while hidden cannot restore UI; hiding during refresh discards late replies',async t=>{
 const f=await fixture(t);await f.open();f.draft('Keep across overlapping refresh');
 let release;f.hold(new Promise(r=>release=r));f.get('account-check').handlers.click();await tick();
 await f.hide();const count=f.calls.length;f.windowEvents.online();assert.equal(f.calls.length,count);
 release();await tick();assert.equal(f.get('requests-section').hidden,true);
 await f.show();assert.equal(f.get('request-decision-comment').value,'Keep across overlapping refresh');
});
test('UX-01 failed explicit logout cannot resurrect staff drafts on a later tab return',async t=>{
 const f=await fixture(t);await f.open();f.draft('Must not survive logout');f.fail(503);
 f.get('logout').handlers.click();await tick();await tick();assert.equal(f.requests.getDraft(f.item.id),'');
 f.fail(0);await f.hide();await f.show();assert.equal(f.get('account-panel').hidden,true);assert.equal(f.get('requests-section').hidden,true);
 assert.equal(f.get('request-decision-comment'),null);
 assert.equal(f.calls.filter(c=>c.method==='POST' && !c.path.endsWith('/auth/logout')).length,0);
});
test('UX-01 role change for the same identity clears staff drafts',async t=>{
 const f=await fixture(t);await f.open();f.draft('Staff role only');await f.hide();f.user({id:'owner-A',role:'student'});await f.show();
 assert.equal(f.requests.getDraft(f.item.id),'');assert.equal(f.get('request-decision-comment'),null);
});
