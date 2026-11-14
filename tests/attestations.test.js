import test from 'node:test';
import assert from 'node:assert/strict';
import {mountAttestations} from '../frontend/js/attestations.js';

test('executor applies only the server-listed review without seeing the approval event',async()=>{
  const element=()=>({
    children:[],handlers:{},
    append(...children){this.children.push(...children);},
    replaceChildren(){this.children=[];},
    addEventListener(type,handler){this.handlers[type]=handler;}
  });
  const ids=new Map();
  const document={
    createElement:element,
    addEventListener(){},
    getElementById(id){if(!ids.has(id))ids.set(id,element());return ids.get(id);}
  };
  const content=document.getElementById('attestations-content');
  const find=(node,text)=>node.textContent===text?node:node.children.map(child=>find(child,text)).find(Boolean);
  const commands=[];
  let applicable_review_versions=[];
  let showRequest=true;
  const request=async(path,options)=>{
    if(path.endsWith('/commands')){
      commands.push(options.body);
      applicable_review_versions=[];
      return {};
    }
    if(path.endsWith('/attestations'))return {items:[{id:'course',activated:true,student:'S04',subject:'Law'}]};
    return {version:9,slots:{},state:{},permissions:['examiner'],applicable_review_versions,
      events:showRequest?[{kind:'review_requested',version:8,at:1,data:{executor_id:'t02',grade:4}}]:[]};
  };
  mountAttestations(document,request).setUser({id:'t02',role:'staff'},()=> 'csrf');
  const tick=()=>new Promise(resolve=>setImmediate(resolve));
  await tick();
  find(content,'Открыть').handlers.click();
  await tick();
  assert.equal(find(content,'Внести исправление'),undefined);
  applicable_review_versions=[8];
  document.getElementById('attestations-retry').handlers.click();
  await tick();
  await find(content,'Внести исправление').handlers.click();
  assert.equal(commands.length,1);
  const {request_key,...body}=commands[0];
  assert.ok(request_key);
  assert.deepEqual(body,{action:'corrected',expected_version:9,review_version:8});
  assert.equal(find(content,'Внести исправление'),undefined);
  showRequest=false;
  applicable_review_versions=[8];
  document.getElementById('attestations-retry').handlers.click();
  await tick();
  await find(content,'Внести исправление № 8').handlers.click();
  assert.equal(commands[1].review_version,8);
});
