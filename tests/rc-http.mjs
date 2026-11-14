// Isolated HTTP fixture sends temporary session material on stdin, never argv or logs.
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
import {createRequestsState} from '../frontend/js/requests-state.js';
import {createWorkspace} from '../frontend/js/mvp-state.js';
const input=JSON.parse(readFileSync(0,'utf8'));
function requestFor(name){const identity=input.users[name];return async(path,o={})=>{
 const response=await fetch(input.origin+path+(o.query?'?'+new URLSearchParams(o.query):''),{method:o.method||'GET',headers:{Origin:input.origin,Cookie:identity.cookie,...o.headers,...(o.method==='POST'?{'Content-Type':'application/json'}:{})},body:o.method==='POST'?JSON.stringify(o.body):undefined,signal:o.signal});
 if(!response.ok)throw {status:response.status};return response.json();
};}
let view;const staff=input.users.staff_demo;
const controller=createRequestsState({request:requestFor('staff_demo'),readCsrf:()=>staff.csrf,publish:x=>view=x});
await controller.setUser(staff.user);assert.ok(!view.items.some(x=>x.id===input.request_id));
await controller.page(view.next_offset);assert.ok(view.items.some(x=>x.id===input.request_id));
await controller.open(input.request_id);assert.equal(view.detail.document,null);
assert.equal(await controller.certificate('sign'),true);assert.ok(view.detail.document.id);
assert.equal(await controller.certificate('deliver'),true);assert.ok(view.detail.document.delivered_at);
const doc=view.detail.document.id;
assert.equal((await requestFor('student_a')('/api/v1/me/documents/'+doc)).id,doc);
await assert.rejects(requestFor('student_b')('/api/v1/me/documents/'+doc),e=>e.status===404);
let widgets;const student=input.users.student_a;
const workspace=createWorkspace({request:requestFor('student_a'),csrf:()=>student.csrf,publish:x=>{if(x.state==='ready')widgets=x;}});
await workspace.identity(student.user);const seen=widgets.data.notifications.items.map(x=>x.id);
while(widgets.data.notifications.next_cursor){await workspace.nextNotifications();seen.push(...widgets.data.notifications.items.map(x=>x.id));}
assert.ok(seen.length>110);assert.equal(seen.length,new Set(seen).size);
const oldest=widgets.data.notifications.items.at(-1);const before=widgets.data.notifications.unread;
await workspace.action('/api/v1/me/notifications/'+oldest.id+'/read');await workspace.refresh();
assert.equal(widgets.data.notifications.unread,before-1);assert.ok(widgets.data.notifications.items.some(x=>x.id===oldest.id));
await assert.rejects(requestFor('student_b')('/api/v1/me/notifications/'+oldest.id+'/read',{method:'POST',body:{},headers:{'X-CSRF-Token':input.users.student_b.csrf}}),e=>e.status===404);
console.log('RC controllers: paginated certificate delivery, old notifications, unread and isolation passed');
