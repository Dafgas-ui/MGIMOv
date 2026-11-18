import test from 'node:test';
import assert from 'node:assert/strict';
import {mountAttendance} from '../frontend/js/attendance.js';

function fixture(request){
  function element(){return {children:[],events:{},dataset:{},textContent:'',hidden:false,
    append(...nodes){this.children.push(...nodes);},prepend(...nodes){this.children.unshift(...nodes);},
    replaceChildren(...nodes){this.children=nodes;},addEventListener(name,fn){this.events[name]=fn;},
    close(){this.open=false;},showModal(){this.open=true;}};}
  const nodes=new Map();
  const events={};
  const document={getElementById(id){if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);},
    createElement:tag=>({...element(),tag}),addEventListener(name,fn){events[name]=fn;}};
  const read=node=>node.textContent+' '+node.children.map(read).join(' ');
  const find=(predicate,root=document.getElementById('attendance-content'))=>{
    if(predicate(root))return root;
    for(const child of root.children){const found=find(predicate,child);if(found)return found;}
  };
  return {controller:mountAttendance(document,request),nodes,find,
    open:id=>events.click({target:{closest:()=>({dataset:{attendance:id}})}}),
    read:()=>read(document.getElementById('attendance-content'))};
}
const ready=(id,role='student')=>({state:'ready',user:{id,role}});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const own={items:[{date:'2027-03-01',subject:'Math',status:'unmarked',active:true,history:[]}]};

test('attendance renders unmarked without absence and rejects late former-owner data',async()=>{
  let resolve;
  const ui=fixture(()=>new Promise(done=>{resolve=done;}));
  ui.controller.identity(ready('alice'),()=>'',()=>{});
  ui.nodes.get('attendance-open').events.click();
  ui.controller.identity(ready('bobby'),()=>'',()=>{});
  resolve(own);await tick();
  assert.doesNotMatch(ui.read(),/Math|Не отмечено/);
  assert.equal(ui.nodes.get('attendance-dialog').open,false);
});

test('attendance displays own data, clears on role change and reports a real 401 centrally',async()=>{
  let error=null,expired=0;
  const ui=fixture(async()=>{if(error)throw error;return own;});
  const identity=value=>ui.controller.identity(value,()=>'',()=>{expired++;});
  identity(ready('alice'));
  ui.nodes.get('attendance-open').events.click();await tick();
  assert.match(ui.read(),/Не отмечено/);assert.doesNotMatch(ui.read(),/Отсутствовал/);
  identity(ready('alice','staff'));assert.doesNotMatch(ui.read(),/Math/);
  error={status:401};ui.nodes.get('attendance-open').events.click();await tick();
  assert.equal(expired,1);assert.equal(ui.nodes.get('attendance-dialog').open,false);
  assert.doesNotMatch(ui.read(),/Math/);
});

test('attendance 409 removes stale marks and offers an explicit refresh',async()=>{
  const ui=fixture(async()=>{throw {status:409};});
  ui.controller.identity(ready('teacher','staff'),()=>'',()=>{});
  ui.nodes.get('attendance-open').events.click();await tick();
  assert.match(ui.nodes.get('attendance-status').textContent,/Обновите данные/);
  assert.match(ui.read(),/Обновить/);
});

const detail=(id='l',version=1,status='unmarked')=>({lesson:{id,date:'2027-03-01',subject:'Math',version:1},
  version,needs_confirmation:false,can_mark:true,students:[{id:'alice',full_name:'Alice',status}],history:[]});
const submit=ui=>ui.find(n=>n.tag==='form').events.submit({preventDefault(){}});
function typeDraft(ui,reason,status){
  const input=ui.find(n=>n.tag==='input');input.value=reason;
  const select=ui.find(n=>n.tag==='select');select.value=status;select.events.change();
  ui.find(n=>n.tag==='form').events.input();
}

test('attendance retains unsaved reason and status after network failure and reopening, scoped to lesson and owner',async()=>{
  const ui=fixture(async(path,options)=>{if(options.method)throw new Error('offline');return detail(path.endsWith('/other')?'other':'l');});
  ui.controller.identity(ready('teacher','staff'),()=>'',()=>{});
  ui.open('l');await tick();typeDraft(ui,'Original observation','late');submit(ui);await tick();
  assert.equal(ui.find(n=>n.tag==='input').value,'Original observation');
  assert.equal(ui.find(n=>n.tag==='select').value,'late');
  ui.nodes.get('attendance-close').events.click();
  ui.nodes.get('attendance-open').events.click();await tick();
  assert.equal(ui.find(n=>n.tag==='input').value,'Original observation');
  ui.controller.identity({state:'suspended'},()=>'',()=>{});
  ui.controller.identity(ready('teacher','staff'),()=>'',()=>{});
  ui.open('l');await tick();assert.equal(ui.find(n=>n.tag==='input').value,'Original observation');
  ui.open('other');await tick();assert.equal(ui.find(n=>n.tag==='input').value,'');
  ui.open('l');await tick();assert.equal(ui.find(n=>n.tag==='select').value,'late');
  ui.controller.identity(ready('second','staff'),()=>'',()=>{});
  ui.open('l');await tick();assert.equal(ui.find(n=>n.tag==='input').value,'');
});

test('attendance conflict retains draft, refresh never writes and adoption needs an explicit new submit',async()=>{
  const writes=[];let version=1;
  const ui=fixture(async(path,options)=>{
    if(options.method){writes.push(options.body);if(writes.length===1){version=3;throw {status:409};}return detail('l',4,'late');}
    return detail('l',version);
  });
  ui.controller.identity(ready('teacher','staff'),()=>'',()=>{});
  ui.open('l');await tick();typeDraft(ui,'Correct arrival','late');submit(ui);await tick();
  assert.equal(ui.find(n=>n.tag==='input').value,'Correct arrival');
  submit(ui);await tick();assert.equal(writes.length,1);
  ui.find(n=>n.textContent==='Обновить').events.click();await tick();
  assert.equal(writes.length,1);assert.equal(ui.find(n=>n.tag==='select').value,'late');
  submit(ui);await tick();assert.equal(writes.length,1);
  ui.find(n=>n.textContent==='Применить черновик к обновлённой версии').events.click();
  assert.equal(writes.length,1);submit(ui);await tick();
  assert.equal(writes.length,2);assert.equal(writes[1].expected_version,3);
  assert.equal(writes[1].reason,'Correct arrival');assert.equal(writes[1].status,'late');
  assert.equal(ui.find(n=>n.tag==='input').value,'');
});

test('attendance conflict draft can be explicitly discarded without writing',async()=>{
  let writes=0,version=1;
  const ui=fixture(async(path,options)=>{
    if(options.method){writes++;version=2;throw {status:409};}
    return detail('l',version,'present');
  });
  ui.controller.identity(ready('teacher','staff'),()=>'',()=>{});
  ui.open('l');await tick();typeDraft(ui,'Unsent correction','absent');submit(ui);await tick();
  ui.find(n=>n.textContent==='Обновить').events.click();await tick();
  ui.find(n=>n.textContent==='Отменить черновик').events.click();
  assert.equal(writes,1);assert.equal(ui.find(n=>n.tag==='input').value,'');
  assert.equal(ui.find(n=>n.tag==='select').value,'present');
});

test('attendance successful response clears only the acknowledged draft, retaining edits made in flight',async()=>{
  let finish;
  const ui=fixture(async(path,options)=>{
    if(options.method)return new Promise(resolve=>{finish=resolve;});
    return detail();
  });
  ui.controller.identity(ready('teacher','staff'),()=>'',()=>{});
  ui.open('l');await tick();typeDraft(ui,'First observation','present');submit(ui);
  typeDraft(ui,'New unsent correction','late');
  finish(detail('l',2,'present'));await tick();
  assert.equal(ui.find(n=>n.tag==='input').value,'New unsent correction');
  assert.equal(ui.find(n=>n.tag==='select').value,'late');
  assert.equal(ui.find(n=>n.textContent==='Сохранить').disabled,true);
});
