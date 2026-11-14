import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {currentLessons,resolvePage,pagesFor} from '../frontend/js/ui-state.js';
import {mountShell} from '../frontend/js/ui-shell.js';
import {createRequestsState} from '../frontend/js/requests-state.js';

test('R1 current/next excludes cancelled and moved markers and respects Moscow/date boundaries',()=>{
 const lesson=(id,start,end,extra={})=>({id,start_minute:start,end_minute:end,status:'scheduled',placement:'current',...extra});
 const schedule={today:'2026-11-07',selected_date:'2026-11-07',days:[{date:'2026-11-07',lessons:[lesson('cancel',550,620,{status:'cancelled'}),lesson('moved',550,620,{placement:'moved_from'}),lesson('active',550,620),lesson('next',630,700)]}]};
 const result=currentLessons(schedule,new Date('2026-11-07T07:00:00Z'));assert.deepEqual(result.active.map(x=>x.id),['active']);assert.equal(result.next.id,'next');
 assert.equal(currentLessons(schedule,new Date('2026-11-07T07:20:00Z')).active.length,0);
 assert.equal(currentLessons(schedule,new Date('2026-11-06T20:59:00Z')).live,false);
 schedule.selected_date='2026-11-06';assert.equal(currentLessons(schedule,new Date('2026-11-07T07:00:00Z')).active.length,0);
});
test('presentation roles expose only their sections and retain Student/Staff account features',()=>{
 assert.equal(resolvePage('queue','student'),'home');assert.equal(resolvePage('academics','staff'),'queue');assert.equal(resolvePage('documents',null),'profile');
 assert.ok(pagesFor('staff').some(([id])=>id==='students'));assert.ok(pagesFor('student').some(([id])=>id==='settings'));
});
function fixture(initialHash=''){
 const nodes=new Map(),events={},hostEvents={};let focused=null;
 function element(){const classes=new Set();return {children:[],dataset:{},hidden:false,value:'',attributes:{},handlers:{},textContent:'',classList:{toggle(name,on){if(on)classes.add(name);else classes.delete(name);},contains:name=>classes.has(name)},append(...children){this.children.push(...children);},replaceChildren(...children){this.children=children;},setAttribute(k,v){this.attributes[k]=v;},getAttribute(k){return this.attributes[k]??this[k];},addEventListener(name,fn){this.handlers[name]=fn;},focus(){focused=this.id;}};}
 for(const match of readFileSync('frontend/index.html','utf8').matchAll(/\bid="([^"]+)"/g)){const node=element();node.id=match[1];nodes.set(node.id,node);}
 for(const id of ['dashboard-section','notifications-section','documents-section','staff-section']){const node=element();node.id=id;nodes.set(id,node);}
 const document={documentElement:{dataset:{}},getElementById:id=>nodes.get(id),createElement:element,querySelectorAll:()=>[],addEventListener(name,fn){events[name]=fn;}};
 let hash=initialHash;
 const host={location:{get hash(){return hash;},set hash(value){hash=value&&!value.startsWith('#')?'#'+value:value;}},scrollY:0,scrollTo(){},addEventListener(name,fn){hostEvents[name]=fn;}};
 return {shell:mountShell(document,host),get:id=>nodes.get(id),events,host,
  setHash(hash){host.location.hash=hash;hostEvents.hashchange();},get focused(){return focused;}};
}
const ready=(id='A',role='student')=>({state:'ready',user:{id,role},profile:{full_name:'Synthetic user'},message:'Confirmed'});
test('compact mobile shortcuts retain a complete role-specific menu after a switch',()=>{
 const f=fixture();
 const pages=id=>f.get(id).children.map(node=>node.dataset.page);
 f.shell.identity(ready());
 assert.deepEqual(pages('app-bottom'),['home','schedule','academics']);
 assert.ok(pages('app-mobile-menu').includes('documents'));
 f.setHash('#gradebook');assert.ok(!f.get('academics-section').classList.contains('screen-off'));
 f.shell.identity({state:'anonymous'});assert.equal(f.get('app-mobile-bar').hidden,true);
 f.shell.identity(ready('B','staff'));
 assert.deepEqual(new Set(pages('app-bottom')),new Set(['queue','staff-schedule','certificates']));
 assert.ok(pages('app-mobile-menu').includes('history'));
 assert.ok(!pages('app-mobile-menu').includes('academics'));
});
test('direct settings links wait for identity, while logout discards the previous route',()=>{
 for(const [role,home] of [['student','home'],['staff','queue']]){
  const f=fixture('#settings'),screen=f.get('settings-section');
  const link=(id,page)=>f.get(id).children.find(node=>node.dataset.page===page);
  const expectLogin=()=>{
   assert.ok(screen.classList.contains('screen-off'));
   assert.ok(!f.get('profile-section').classList.contains('screen-off'));
   for(const nav of ['app-sidebar','app-mobile-menu','app-bottom'])assert.equal(link(nav,'settings'),undefined);
  };
  expectLogin();f.setHash('#settings-section');expectLogin();f.setHash('#settings');expectLogin();
  f.shell.identity(ready('A',role));
  assert.equal(link('app-sidebar','settings').getAttribute('aria-current'),'page');
  assert.ok(!screen.classList.contains('screen-off'));
  const menu=f.get('app-menu');
  menu.handlers.click();
  const target=link('app-mobile-menu','settings');assert.ok(target);
  let prevented=false;
  f.events.click({target:{closest:()=>target},preventDefault(){prevented=true;}});
  assert.ok(prevented);assert.equal(menu.getAttribute('aria-expanded'),'false');
  assert.equal(f.focused,'page-title');
  assert.equal(link('app-sidebar','settings').getAttribute('aria-current'),'page');
  assert.ok(!screen.classList.contains('screen-off'));
  f.shell.identity({state:'loading',operation:'refresh'});expectLogin();
  f.shell.identity(ready('A',role));assert.ok(!screen.classList.contains('screen-off'));
  f.shell.identity({state:'logout-pending'});expectLogin();
  f.shell.identity({state:'anonymous'});expectLogin();
  f.shell.identity(ready('A',role));assert.equal(link('app-sidebar',home).getAttribute('aria-current'),'page');
  assert.ok(screen.classList.contains('screen-off'));
 }
});
test('reload restores a permitted hash after session confirmation and rejects a foreign route',()=>{
 const original=fixture();original.shell.identity(ready());original.shell.go('academics');
 original.shell.identity({state:'anonymous',preserveRoute:true});
 assert.equal(original.host.location.hash,'#academics');
 assert.ok(original.get('academics-section').classList.contains('screen-off'));
 const reload=fixture(original.host.location.hash);
 reload.shell.identity({state:'loading',operation:'refresh'});
 assert.ok(reload.get('academics-section').classList.contains('screen-off'));
 reload.shell.identity(ready());
 assert.equal(reload.host.location.hash,'#academics');
 assert.ok(!reload.get('academics-section').classList.contains('screen-off'));
 reload.shell.identity({state:'suspended'});reload.shell.identity(ready('B','staff'));
 assert.ok(reload.get('academics-section').classList.contains('screen-off'));
 assert.equal(reload.get('page-title').textContent,'Очередь');
 const foreign=fixture('#academics');foreign.shell.identity(ready('B','staff'));
 assert.equal(foreign.host.location.hash,'#queue');
 assert.ok(foreign.get('academics-section').classList.contains('screen-off'));
 const loggedOut=fixture('#documents');loggedOut.shell.identity({state:'anonymous'});
 assert.ok(loggedOut.get('mvp-section').classList.contains('screen-off'));
 loggedOut.shell.identity(ready());assert.equal(loggedOut.get('page-title').textContent,'Документы');
});
test('shell changes routes without replacing forms; refresh suspension cannot show protected screens',()=>{
 const f=fixture();f.shell.identity(ready());const form=f.get('request-message');form.value='Student draft';
 f.shell.go('requests');assert.equal(f.get('requests-section').classList.contains('screen-off'),false);
 f.shell.go('schedule');f.shell.go('requests');assert.equal(f.get('request-message'),form);assert.equal(form.value,'Student draft');
 f.shell.identity({state:'loading',operation:'refresh'});assert.equal(f.get('requests-section').classList.contains('screen-off'),true);
 f.shell.identity(ready());assert.equal(f.get('requests-section').classList.contains('screen-off'),false);
 f.shell.identity({state:'anonymous'});assert.equal(f.get('requests-section').classList.contains('screen-off'),true);assert.equal(f.get('app-bottom').hidden,true);
});
test('shell history is selected-request history only and clears before identity confirmation',()=>{
 const f=fixture();f.shell.identity(ready('staff','staff'));
 f.shell.requests({state:'ready',detail:{id:'request-a',history:[{comment:'Sensitive reply',actor_name:'Staff',created_at:1}]}});f.shell.go('history');
 assert.equal(f.get('history-content').children[0].textContent,'Обращение № request-a');
 f.shell.identity({state:'suspended'});assert.ok(!JSON.stringify(f.get('history-content').children).includes('Sensitive reply'));
 f.shell.identity(ready('other','staff'));assert.ok(!JSON.stringify(f.get('history-content').children).includes('Sensitive reply'));
});
test('mobile menu closes with Escape from its trigger or links and restores focus',()=>{
 const f=fixture();f.shell.identity({state:'anonymous'});f.shell.identity(ready());const trigger=f.get('app-menu'),menu=f.get('app-mobile-menu');
 for(const target of [trigger,menu]){
  trigger.handlers.click();assert.equal(trigger.getAttribute('aria-expanded'),'true');
  let prevented=false;target.handlers.keydown({key:'Escape',preventDefault(){prevented=true;}});
  assert.equal(prevented,true);assert.equal(menu.hidden,true);assert.equal(trigger.getAttribute('aria-expanded'),'false');assert.equal(f.focused,'app-menu');
 }
 trigger.handlers.click();f.shell.identity({state:'loading'});assert.equal(trigger.getAttribute('aria-expanded'),'false');
});
test('reply, decision draft and current-page filter remain independent across refresh and conflict',async()=>{
 let state,failure=0;let detail={id:'a',type:'appeal',status:'processing',version:2,history:[],actions:['approved','rejected']};const posts=[];
 const c=createRequestsState({readCsrf:()=>'csrf',publish:x=>state=x,request:async(path,o={})=>{
  if(o.method==='POST'){posts.push(o);if(failure)throw {status:failure};detail={...detail,version:detail.version+1};return detail;}
  return path.endsWith('/requests')?{items:[detail],offset:0,next_offset:null}:detail;
 }});
 await c.setUser({id:'staff',role:'staff'});await c.open('a');c.setDraft('a','Decision draft');c.setReplyDraft('a','Reply draft');c.setFilter('current page');
 c.suspend();await c.setUser({id:'staff',role:'staff'});assert.equal(c.getReplyDraft('a'),'Reply draft');assert.equal(c.getFilter(),'current page');
 failure=409;await c.reply('Reply draft');assert.equal(state.state,'error');assert.equal(c.getReplyDraft('a'),'Reply draft');await c.retry();assert.equal(posts.length,1);
 failure=0;await c.reply('Reply draft');assert.equal(c.getReplyDraft('a'),'');assert.equal(c.getDraft('a'),'Decision draft');assert.equal(posts.at(-1).body.version,2);
 c.clear();assert.equal(c.getReplyDraft('a'),'');assert.equal(c.getFilter(),'');
});
