import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {createWorkspace} from '../frontend/js/mvp-state.js';

function fixture(){
  const nodes=new Map();let failure=false;
  function element(){return {children:[],handlers:{},dataset:{},value:'',hidden:false,classList:{add(){}},addEventListener(name,fn){this.handlers[name]=fn;},append(...children){this.children.push(...children);},replaceChildren(...children){this.children=children;}};}
  const find=(node,id)=>node.id===id?node:node.children.map(child=>find(child,id)).find(Boolean);
  const document={cookie:'',visibilityState:'visible',createElement:element,createDocumentFragment:element,addEventListener(){},getElementById(id){return nodes.get(id)||[...nodes.values()].map(node=>find(node,id)).find(Boolean);}};
  for(const match of readFileSync('frontend/index.html','utf8').matchAll(/\bid="([^"]+)"/g)){const node=element();node.id=match[1];nodes.set(node.id,node);}
  const requestJson=async path=>{
    if(failure)throw new Error('offline');
    if(path.endsWith('/catalogue'))return {groups:[{id:'g',name:'Группа'}],subjects:[{id:'s',name:'Дисциплина'}],teachers:[{id:'t',full_name:'Демо'}],rooms:[{id:'r',number:'101',building:'Корпус'}]};
    if(path.endsWith('/notifications'))return {items:[],unread:0};
    return {items:[]};
  };
  const context={document,location:{protocol:'http:'},requestJson,createWorkspace,t:value=>value};
  const source=readFileSync('frontend/js/mvp.js','utf8').replace(/^import .*;$/gm,'').replace('export function mvpIdentity','function mvpIdentity');
  runInNewContext(source,context);
  return {identity:context.mvpIdentity,get:id=>document.getElementById(id),fail(value){failure=value;}};
}
test('real workspace renderer preserves same-staff form on suspend and clears it on logout',async()=>{
  const f=fixture();await f.identity({id:'staff-a',role:'staff'});f.get('mvp-field-reason').value='Sensitive draft';
  f.identity(null,{suspend:true});assert.equal(f.get('mvp-section').hidden,true);
  await f.identity({id:'staff-a',role:'staff'});assert.equal(f.get('mvp-field-reason').value,'Sensitive draft');
  f.identity(null);assert.equal(f.get('mvp-field-reason'),undefined);
});
test('real renderer drops old draft immediately on account change even if new data fails',async()=>{
  const f=fixture();await f.identity({id:'staff-a',role:'staff'});f.get('mvp-field-reason').value='Sensitive draft';
  f.fail(true);await f.identity({id:'staff-b',role:'staff'});assert.equal(f.get('mvp-field-reason'),undefined);
  f.fail(false);await f.identity({id:'staff-a',role:'staff'});assert.equal(f.get('mvp-field-reason').value,'');
});
