import test from 'node:test';
import assert from 'node:assert/strict';
import {createCourseworkClient, courseworkError, filterWorks, submissionBodyFits, unicodeLength} from '../frontend/js/coursework-client.js';
import {resolvePage} from '../frontend/js/ui-state.js';

const student={id:'student',role:'student'};
const staff={id:'teacher',role:'staff'};
const failure=status=>Object.assign(new Error('internal SQL text'),{status});

test('coursework navigation and filters remain scoped to server list rows',async()=>{
  assert.equal(resolvePage('coursework','student'),'coursework');
  assert.equal(resolvePage('coursework','staff'),'coursework');
  assert.equal(resolvePage('coursework',null),'profile');
  const items=[{semester_id:'s',subject_name:'Math'},{semester_id:'old',subject_name:'Math'},{semester_id:'s',subject_name:'Law'}];
  assert.deepEqual(filterWorks(items,{semester:'s',subject:'Math'}),[items[0]]);
  const requested=[];
  const client=createCourseworkClient(student,()=>null,async path=>{requested.push(path);return {items};});
  await client.read();await client.read('/task');
  assert.deepEqual(requested,['/api/v1/me/coursework','/api/v1/me/coursework/task']);
});

test('Unicode length and body limits count code points and UTF-8 bytes separately',()=>{
  for(const char of ['a','я','😀']){
    const response=char.repeat(4000);
    assert.equal(unicodeLength(response),4000);
    assert.equal(unicodeLength(response+char),4001);
    assert.equal(submissionBodyFits({response,expected_version:1,request_key:'a'.repeat(36)}),true);
  }
  const overhead=new TextEncoder().encode(JSON.stringify({response:''})).length;
  assert.equal(submissionBodyFits({response:'a'.repeat(32768-overhead)}),true);
  assert.equal(submissionBodyFits({response:'a'.repeat(32769-overhead)}),false);
});

test('same submission preserves request key after uncertainty and never double-sends in flight',async()=>{
  const requests=[];
  let complete;
  let keys=0;
  const client=createCourseworkClient(student,()=> 'csrf',async (path,options)=>{
    requests.push({path,...options});
    if(requests.length===1)return new Promise((_,reject)=>{complete=()=>reject(failure(503));});
    return {attempt_no:1,version:2};
  },()=>String(++keys).repeat(16));
  const fields={response:'Привет 😀',expected_version:1};
  const first=client.write('/task/submissions','POST',fields);
  assert.equal(await client.write('/task/submissions','POST',fields),null);
  complete();
  await assert.rejects(first,{status:503});
  await assert.rejects(client.write('/task/submissions','POST',{...fields,response:'Different'}),/retry-original/);
  assert.deepEqual(await client.write('/task/submissions','POST',fields),{attempt_no:1,version:2});
  assert.equal(keys,1);
  assert.deepEqual(requests[0],requests[1]);
  assert.deepEqual(requests[0].headers,{'X-Mgimov-User':'student','X-CSRF-Token':'csrf'});
});

test('409 blocks review or return until refresh and an explicit command with the new version',async()=>{
  const writes=[];
  const client=createCourseworkClient(staff,()=> 'csrf',async (path,options)=>{
    writes.push({path,...options});
    if(writes.length===1)throw failure(409);
    return {review_revision:2};
  },()=>String(writes.length+1).repeat(16));
  const review={expected_version:4,action:'review',data:{course_id:'course',attempt_no:1,decision:'returned',comment:'Revise'}};
  await assert.rejects(client.write('/task/commands','POST',review),{status:409});
  assert.equal(await client.write('/task/commands','POST',review),null);
  client.refreshed();
  assert.equal(writes.length,1);
  await client.write('/task/commands','POST',{...review,expected_version:5});
  assert.equal(writes[1].body.expected_version,5);
  assert.notEqual(writes[0].body.request_key,writes[1].body.request_key);
});

test('coursework errors use safe messages and distinguish BRS publication conflicts',()=>{
  const messages=[401,403,404,409,413,415,422,503].map(status=>courseworkError(failure(status)));
  assert.equal(new Set(messages).size,8);
  assert.match(courseworkError(failure(415)),/JSON/);
  assert.doesNotMatch(courseworkError(failure(415)),/Повторите|Ответ не получен/);
  for(const message of messages)assert.doesNotMatch(message,/SQL|internal/);
  assert.match(courseworkError({status:409,code:'coursework_brs_result_already_published'}),/БРС/);
});
