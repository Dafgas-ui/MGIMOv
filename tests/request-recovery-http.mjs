// Invoked by the isolated Python HTTP test. Credentials arrive on stdin, never argv/logs.
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
import {createRequestsState} from '../frontend/js/requests-state.js';
import {createRequestOperations} from '../frontend/js/request-operation.js';
const input=JSON.parse(readFileSync(0,'utf8')),entries=new Map();
const operations=createRequestOperations({getStorage:()=>({getItem:k=>entries.get(k)??null,setItem:(k,v)=>entries.set(k,v),removeItem:k=>entries.delete(k)})});
let state,drop=true;const statuses=[];
const request=async(path,o={})=>{
 const response=await fetch(input.origin+path+(o.query?'?'+new URLSearchParams(o.query):''),{method:o.method || 'GET',headers:{Origin:input.origin,Cookie:input.cookie,...o.headers,...(o.method==='POST'?{'Content-Type':'application/json'}:{})},body:o.method==='POST'?JSON.stringify(o.body):undefined,signal:o.signal});
 if(o.method==='POST')statuses.push(response.status);
 if(!response.ok)throw {status:response.status};
 const data=await response.json();
 if(o.method==='POST' && drop){drop=false;throw new Error('Synthetic response lost after server commit');}
 return data;
};
const controller=()=>createRequestsState({request,operations,readCsrf:()=>input.csrf,publish:s=>state=s});
const payload={type:'appeal',purpose:'',message:'AUD-02 HTTP '+crypto.randomUUID()};
let c=controller();await c.setUser(input.user);await c.create(payload);assert.equal(state.state,'error');c.clear();
c=controller();await c.setUser(input.user);assert.ok(state.recovery);
await c.create({...payload,message:payload.message+' changed'});assert.equal(state.state,'error');
await c.create(payload);assert.equal(state.state,'ready');assert.deepEqual(statuses,[201,409,200]);
assert.equal(state.items.filter(x=>x.message===payload.message).length,1);
await c.create(payload);assert.equal(statuses.at(-1),201);assert.equal(state.items.filter(x=>x.message===payload.message).length,2);
assert.equal(entries.size,0);
console.log('AUD-02 real HTTP: recovery, changed content conflict and separate intention passed');
