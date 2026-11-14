// Isolated real HTTP + production renderer; disposable session material via stdin.
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
import {createRequestsState} from '../frontend/js/requests-state.js';
import {renderRequests} from '../frontend/js/requests.js';

const {origin,request_id:id,a,b,student}=JSON.parse(readFileSync(0,'utf8'));
const element=tag=>({tag,children:[],handlers:{},append(...nodes){this.children.push(...nodes);},
  replaceChildren(){this.children=[];},setAttribute(){},addEventListener(name,fn){this.handlers[name]=fn;}});
const document={createElement:element},root=element('div');
const all=node=>[node,...node.children.flatMap(all)];
const find=id=>all(root).find(node=>node.id===id);
const comment='Несохранённый ответ\nВторая строка <demo>';
const replyPosts=[];
let current=b,viewA,viewB,denyDetail=false;
function request(identity){
  return async(path,o={})=>{
    if(denyDetail&&path.endsWith('/'+id)&&!o.method)throw {status:404}; // Simulate scope withdrawal at detail reload.
    const post=o.method==='POST';
    const response=await fetch(origin+path+(o.query?'?'+new URLSearchParams(o.query):''),{
      method:o.method||'GET',headers:{Origin:origin,Cookie:identity().cookie,...o.headers,...(post?{'Content-Type':'application/json'}:{})},
      body:post?JSON.stringify(o.body):undefined,signal:o.signal});
    if(path.endsWith('/reply')&&post)replyPosts.push(response.status);
    if(!response.ok)throw {status:response.status};
    return response.status===204?null:response.json();
  };
}
const c1=createRequestsState({request:request(()=>a),readCsrf:()=>a.csrf,publish:v=>viewA=v});
const c2=createRequestsState({request:request(()=>current),readCsrf:()=>current.csrf,publish(v){
  viewB=v;
  if(v.state==='ready')renderRequests(document,root,v,c2);
  else root.replaceChildren();
}});
const refresh=async()=>assert.equal(await c2.retry(),true);
const retained=()=>find('request-retained-reply');
const noSend=()=>assert.ok(!all(root).some(node=>node.textContent==='Отправить ответ'));
await c1.setUser(a.user);await c1.open(id);
await c2.setUser(b.user);await c2.open(id);
assert.equal(viewA.detail.version,viewB.detail.version);
const field=find('request-reply-comment');
field.value=comment;field.handlers.input();
assert.equal(await c1.change('approved','Обращение завершено'),true);
assert.equal(await c2.reply(field.value),false);
assert.equal(viewB.state,'error');
assert.deepEqual(replyPosts,[409]);
await refresh();
assert.equal(viewB.detail.status,'approved');
assert.equal(retained()?.value,comment,'Terminal conflict must expose the exact unsent text');
assert.equal(retained().readOnly,true);assert.notEqual(retained().disabled,true);
assert.ok(!all(root).some(node=>node.tag==='form'));
noSend();
assert.equal(c2.reply(comment),false);await refresh();assert.deepEqual(replyPosts,[409]);
assert.equal(retained().value,comment);
c2.suspend();assert.equal(retained(),undefined);
await c2.setUser(b.user);assert.equal(retained().value,comment);
denyDetail=true;assert.equal(await c2.retry(),false);
assert.equal(c2.getReplyDraft(id),'');assert.equal(retained(),undefined);
denyDetail=false;await refresh();assert.equal(retained(),undefined);noSend();

// On the same confirmed item, exercise cleanup independently of the 404 path.
c2.setReplyDraft(id,comment);await refresh();assert.equal(retained().value,comment);
current=student;await c2.setUser(student.user);
assert.equal(retained(),undefined);
current=b;await c2.setUser(b.user);await c2.open(id);
assert.equal(c2.getReplyDraft(id),'');assert.equal(retained(),undefined);
c2.setReplyDraft(id,comment);await refresh();assert.equal(retained().value,comment);
c2.clear({discardOperation:true});
await request(()=>b)('/api/v1/auth/logout',{method:'POST',headers:{'X-Mgimov-User':b.user.id,'X-CSRF-Token':b.csrf},body:{}});
assert.equal(retained(),undefined);assert.equal(c2.getReplyDraft(id),'');
await assert.rejects(request(()=>b)('/api/v1/staff/requests/'+id),e=>e.status===401);
assert.deepEqual(replyPosts,[409]);
assert.ok(!viewA.detail.history.some(event=>event.comment===comment));
console.log('RC2-01: independent Staff sessions, HTTP 409, selectable draft and no repeat POST');
