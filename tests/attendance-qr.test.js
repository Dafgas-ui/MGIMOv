import test from 'node:test';
import assert from 'node:assert/strict';
import {mountQrAttendance,takeQrFragment,qrMatrix} from '../frontend/js/attendance-qr.js';
const token='a'.repeat(43),tick=()=>new Promise(resolve=>setImmediate(resolve));
const ready=(id,role='student')=>({state:'ready',user:{id,role}});
function fixture(request,initial=token){
 const events={},nodes=new Map();let counter=0,expired=0;
 function node(tag){return {tag,children:[],attrs:{},events:{},textContent:'',append(...v){for(const n of v){n.parent=this;this.children.push(n);}},prepend(...v){for(const n of v)n.parent=this;this.children.unshift(...v);},replaceChildren(){this.children=[];},setAttribute(k,v){this.attrs[k]=String(v);},addEventListener(k,v){this.events[k]=v;},querySelector(tag){return this.children.find(c=>c.tag===tag);},remove(){this.parent.children=this.parent.children.filter(n=>n!==this);},showModal(){this.open=true;},close(){this.open=false;}};}
 const document={getElementById(id){if(!nodes.has(id))nodes.set(id,node(id));return nodes.get(id);},createElement:node,createElementNS:(_,tag)=>node(tag),addEventListener(k,v){events[k]=v;}};
 const host={performance,crypto:{randomUUID:()=>String(++counter).padStart(32,'0')},addEventListener(){}};
 const ui=mountQrAttendance(document,request,host,initial);
 const content=document.getElementById('attendance-qr-content');
 const read=n=>n.textContent+n.children.map(read).join(' ');
 const identity=value=>ui.identity(value,()=> 'csrf',()=>expired++);
 return {identity,events,nodes,content,document,read:()=>read(content),expired:()=>expired,
  button:name=>content.children.find(c=>c.tag==='button'&&c.textContent===name),cleanup:()=>identity({state:'anonymous'})};
}
test('QR fragment is consumed without adding a token to path/query/history',()=>{
 let replaced;const host={location:{hash:'#attendance-qr='+token,pathname:'/',search:''},history:{replaceState:(_,__,value)=>replaced=value}};
 assert.equal(takeQrFragment(host),token);assert.equal(replaced,'/#profile');
 host.location.hash='#attendance-qr=invalid';assert.equal(takeQrFragment(host),null);
});
test('QR uses safe SVG geometry and rejects malformed matrices',()=>{
 const ui=fixture(async()=>({}),null),matrix=Array.from({length:21},()=>Array(21).fill(false));matrix[10][10]=true;
 const svg=qrMatrix(ui.document,matrix);assert.equal(svg.attrs.role,'img');assert.equal(svg.children[1].attrs.d,'M10 10h1v1h-1z');
 assert.throws(()=>qrMatrix(ui.document,[['<script>']]));ui.cleanup();
});
test('Student preview never marks automatically; double confirmation posts once and preserves manual result',async()=>{
 let count=0,finish;
 const ui=fixture(async(path,options)=>{
  assert.equal(options.headers['X-MGIMOv-User'],'alice');assert.equal(options.headers['X-CSRF-Token'],'csrf');
  if(path.endsWith('/preview'))return {subject:'Math',date:'2027-03-01'};
  count++;return new Promise(resolve=>finish=resolve);
 });
 ui.identity(ready('alice'));await tick();assert.match(ui.read(),/Math/);assert.equal(count,0);
 const b=ui.button('Подтвердить посещение');b.events.click();b.events.click();assert.equal(count,1);
 finish({outcome:'manual_priority',status:'absent'});await tick();assert.match(ui.nodes.get('attendance-qr-status').textContent,/ручную отметку/);
 assert.equal(ui.button('Подтвердить посещение'),undefined);ui.cleanup();
});
test('historical receipt present never overrides current absent in the Student message',async()=>{
 const ui=fixture(async path=>path.endsWith('/preview')?{subject:'Math'}:{outcome:'present',status:'absent',manual_mark:true});
 ui.identity(ready('alice'));await tick();await ui.button('Подтвердить посещение').events.click();
 const message=ui.nodes.get('attendance-qr-status').textContent;
 assert.match(message,/Текущий статус: Отсутствовал/);assert.match(message,/не изменил ручную отметку/);
 assert.doesNotMatch(message,/подтверждено: Присутствовал/);ui.cleanup();
});
test('late success or 401 and QR token cannot cross account or role changes',async()=>{
 for(const fail of [false,true]){
  let finish,calls=0;const ui=fixture(()=>{calls++;return new Promise((resolve,reject)=>finish=()=>fail?reject({status:401}):resolve({subject:'A private data'}));});
  ui.identity(ready('alice'));ui.identity(ready('bobby'));finish();await tick();
  assert.equal(calls,1);assert.doesNotMatch(ui.read(),/A private data/);assert.equal(ui.expired(),0);ui.cleanup();
 }
 let calls=0;const ui=fixture(async()=>{calls++;return {subject:'Math'};});
 ui.identity(ready('alice'));await tick();ui.identity(ready('alice','staff'));ui.identity(ready('alice'));await tick();
 assert.equal(calls,1);assert.doesNotMatch(ui.read(),/Math/);ui.cleanup();
});
test('current protected 401 centrally expires; logout during HTTP clears the interface',async()=>{
 const expired=fixture(async()=>{throw {status:401};});expired.identity(ready('alice'));await tick();assert.equal(expired.expired(),1);expired.cleanup();
 let finish;const ui=fixture(()=>new Promise(resolve=>finish=resolve));ui.identity(ready('alice'));ui.cleanup();finish({subject:'Old'});await tick();
 assert.equal(ui.nodes.get('attendance-qr-dialog').open,false);assert.doesNotMatch(ui.read(),/Old/);
});
test('temporary preview failure offers explicit retry without creating an attendance mark',async()=>{
 let calls=0;const ui=fixture(async path=>{assert.ok(path.endsWith('/preview'));if(++calls===1)throw {status:503};return {subject:'Math'};});
 ui.identity(ready('alice'));await tick();assert.match(ui.nodes.get('attendance-qr-status').textContent,/QR недоступен/);
 ui.button('Повторить').events.click();await tick();assert.match(ui.read(),/Math/);assert.equal(calls,2);ui.cleanup();
});
test('Staff uncertain retries reuse request key; a new issue gets a new key and a revocable local QR',async()=>{
 const bodies=[];let attempt=0;
 const matrix=Array.from({length:21},()=>Array(21).fill(false));
 const ui=fixture(async(path,options)=>{
  if(options.method!=='POST')return {version:1,lesson:{version:1}};
  if(path.endsWith('/close'))return {closed:true};
  bodies.push(options.body);attempt++;
  if(attempt===1)throw {status:0};
  if(attempt===2)return {id:'qr',code_available:false};
  return {id:'next',code_available:true,expires_in:60,matrix};
 },null);
 ui.identity(ready('teacher','staff'));ui.events['mgimov:attendance-qr-open']({detail:{lesson:{id:'l'}}});
 await ui.button('Выпустить QR').events.click();await ui.button('Выпустить QR').events.click();
 assert.equal(bodies[0].request_key,bodies[1].request_key);assert.match(ui.nodes.get('attendance-qr-status').textContent,/не хранится/);
 await ui.button('Выпустить QR').events.click();assert.notEqual(bodies[1].request_key,bodies[2].request_key);assert.ok(ui.content.querySelector('svg'));
 await ui.button('Отозвать QR').events.click();assert.equal(ui.content.querySelector('svg'),undefined);ui.cleanup();
});
