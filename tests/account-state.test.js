import test from 'node:test';
import assert from 'node:assert/strict';
import {createAccountState} from '../frontend/js/account-state.js';
function fixture() {
 let value,user=null,held=null;const calls=[];
 const request=async(path,options={})=>{
  calls.push({path,options});
  if(held && path.endsWith('/profile')){const p=held;held=null;await p;}
  if(path.endsWith('/csrf'))return {csrf:'synthetic'};
  if(path.endsWith('/login')){user=options.body.login;return {};}
  if(path.endsWith('/logout')){user=null;return null;}
  if(!user)throw Object.assign(new Error(),{status:401});
  const result={user:{id:user,role:'student'}};
  return path.endsWith('/profile')?{...result,profile:{full_name:user}}:result;
 };
 const controller=createAccountState({request,readCsrf:()=> 'synthetic',publish:v=>value=v});
 return {controller,calls,get value(){return value;},hold(p){held=p;}};
}
test('login, own profile, logout and re-login',async()=>{
 const f=fixture();await f.controller.refresh();assert.equal(f.value.state,'anonymous');
 await f.controller.login('A','synthetic');assert.equal(f.value.profile.full_name,'A');
 await f.controller.logout();assert.equal(f.value.state,'anonymous');
 await f.controller.login('B','synthetic');assert.equal(f.value.profile.full_name,'B');
 assert.equal(f.calls.filter(c=>c.path.endsWith('/profile')).at(-1).options.headers['X-Mgimov-User'],'B');
});
test('late response after invalidation cannot restore profile',async()=>{
 const f=fixture();let release;f.hold(new Promise(r=>release=r));const pending=f.controller.login('A','synthetic');
 await new Promise(r=>setTimeout(r,0));f.controller.clear();release();await pending;
 assert.equal(f.value.state,'anonymous');assert.equal(f.value.profile,undefined);
});
test('double submit and server failure',async()=>{
 let release,state,calls=0;
 const c=createAccountState({readCsrf:()=>'',publish:v=>state=v,request:async(path)=>{
  if(path.endsWith('/csrf')){calls++;await new Promise(r=>release=r);return {csrf:'x'};}
  throw Object.assign(new Error(),{status:503});
 }});
 const pending=c.login('A','synthetic');assert.equal(await c.login('B','synthetic'),false);assert.equal(calls,1);release();await pending;
 assert.equal(state.state,'error');assert.equal(state.profile,undefined);
});
test('expiry, CSRF failure, offline and timeout hide data',async()=>{
 for(const status of [401,403,503]){
  let state;const c=createAccountState({request:async()=>{throw Object.assign(new Error(),{status});},readCsrf:()=>'',publish:v=>state=v});
  await c.refresh();assert.equal(state.profile,undefined);assert.equal(state.state,status===401?'anonymous':'error');
 }
 let state;const c=createAccountState({timeoutMs:10,request:(p,{signal})=>new Promise((_,reject)=>signal.addEventListener('abort',()=>reject(new Error('abort')))),readCsrf:()=>'',publish:v=>state=v});
 await c.refresh();assert.equal(state.state,'error');assert.equal(c.isBusy(),false);
});

test('failed logout can recover after server-confirmed different account',async()=>{
 let user='A',state,failLogout=true;
 const c=createAccountState({readCsrf:()=> 'synthetic',publish:v=>state=v,request:async(path,options={})=>{
  if(path.endsWith('/logout') && failLogout)throw Object.assign(new Error(),{status:503});
  if(options.headers?.['X-Mgimov-User'] && options.headers['X-Mgimov-User']!==user)throw Object.assign(new Error(),{status:403});
  return path.endsWith('/profile')?{user:{id:user,role:'student'},profile:{full_name:user}}:{user:{id:user,role:'student'}};
 }});
 await c.refresh();await c.logout();assert.equal(state.state,'logout-pending');assert.equal(state.profile,undefined);
 c.clear();user='B';await c.refresh();assert.equal(state.state,'ready');assert.equal(state.profile.full_name,'B');
});
test('wrong login has a readable localized error and no profile',async()=>{
 let state;const c=createAccountState({readCsrf:()=>'',publish:v=>state=v,request:async(path)=>{
  if(path.endsWith('/csrf'))return {csrf:'synthetic'};throw Object.assign(new Error(),{status:401});
 }});
 await c.login('A','synthetic');assert.equal(state.message,'Неверный логин или пароль.');assert.equal(state.profile,undefined);
});

test('anonymous background refresh does not emit loading or consume a login draft',async()=>{
 let publications=0,calls=0;
 const c=createAccountState({readCsrf:()=>'',publish:()=>publications++,request:async()=>{calls++;throw Object.assign(new Error(),{status:401});}});
 await c.refresh();const before=publications;
 await c.refresh({background:true});assert.equal(publications,before);assert.equal(calls,1);
});
test('actual account DOM adapter preserves an unfinished password across poll and manual check',async()=>{
 const {readFileSync}=await import('node:fs');const {runInNewContext}=await import('node:vm');
 const nodes=new Map(),timers=[];let submitted;
 const element=()=>({value:'',hidden:false,disabled:false,textContent:'',handlers:{},addEventListener(name,fn){this.handlers[name]=fn;},replaceChildren(){},append(){}});
 const get=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
 const document={visibilityState:'visible',getElementById:get,createElement:element,addEventListener(){}};
 const requestJson=async(path,options={})=>{
  if(path.endsWith('/csrf'))return {csrf:'synthetic'};
  if(path.endsWith('/login')){submitted=options.body;throw Object.assign(new Error(),{status:401});}
  throw Object.assign(new Error(),{status:401});
 };
 const source=readFileSync('frontend/js/account.js','utf8').replace(/^import .*;$/gm,'');
 runInNewContext(source,{document,requestJson,createAccountState,
   mountLanguage:()=>({setUser(){}}),t:value=>value,attestationIdentity(){},courseworkIdentity(){},attendanceIdentity(){},deadlinesIdentity(){},forecastIdentity(){},roomsIdentity(){},qrAttendanceIdentity(){},
  createAppearanceState:()=>({setUser(){},update(){},reset(){},systemThemeChanged(){}}),
  location:{protocol:'http:'},addEventListener(){},setInterval:fn=>timers.push(fn)});
 await new Promise(r=>setTimeout(r,0));
 get('login').value='student_a';get('password').value='synthetic-draft';
 timers[0]();await new Promise(r=>setTimeout(r,0));assert.equal(get('password').value,'synthetic-draft');assert.equal(get('login-fields').disabled,false);
 get('account-check').handlers.click();await new Promise(r=>setTimeout(r,0));assert.equal(get('password').value,'synthetic-draft');
 get('login-form').handlers.submit({preventDefault(){}});await new Promise(r=>setTimeout(r,0));
 assert.equal(submitted.password,'synthetic-draft');assert.equal(get('password').value,'');
});
