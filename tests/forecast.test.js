import test from 'node:test';
import assert from 'node:assert/strict';
import {createForecast} from '../frontend/js/forecast-state.js';
import {renderForecast} from '../frontend/js/forecast.js';
import {emphasizeProgress} from '../frontend/js/progress.js';

function dom(){
  const node=()=>({children:[],dataset:{},textContent:'',setAttribute(){},append(...values){this.children.push(...values);},replaceChildren(){this.children=[];}});
  return {document:{createElement:node},root:node(),read(e){return e.textContent+' '+e.children.map(x=>this.read(x)).join(' ');}};
}
const sample={id:'A',subject:'Math',semester:'Spring',control:'exam',available:true,
  published_points:51,plan_maximum:100,admission:true,admission_minimum:50,predicted_result:null,
  result_reason:'examiner_decides',events:[{title:'Lab',points:20,maximum:20},{title:'Test',points:null,maximum:20}]};
test('forecast renders server values and distinguishes published, missing and official grades',()=>{
  const d=dom();renderForecast(d.document,d.root,[sample]);const text=d.read(d.root);
  assert.match(text,/Опубликовано: 51 из 100/);assert.match(text,/выставляет преподаватель/);
  assert.match(text,/Test: не опубликовано/);assert.match(text,/не официальная оценка/);
  const meter=d.root.children[0].children.find(x=>x.max===100);assert.equal(meter.value,51);
  renderForecast(d.document,d.root,[{...sample,control:'credit',published_points:null,predicted_result:null,result_reason:'no_published_results'}]);
  assert.match(d.read(d.root),/Прогноз не рассчитан/);assert.doesNotMatch(d.read(d.root),/Опубликовано: 0/);
});
test('forecast shows unavailable enrollment and transfer reasons without invented numbers',()=>{
  const d=dom();renderForecast(d.document,d.root,[{id:'x',subject:'Old',available:false,reason:'transfer_reconciliation'}]);
  assert.match(d.read(d.root),/требуется сверка/);assert.doesNotMatch(d.read(d.root),/из 100/);
  renderForecast(d.document,d.root,[]);assert.match(d.read(d.root),/Нет дисциплин/);
});
test('progress emphasis preserves real values and respects reduced motion',()=>{
  const calls=[],meter={value:51,max:100,animate:(...args)=>calls.push(args)};
  emphasizeProgress(meter,{matchMedia:()=>({matches:true})});assert.equal(calls.length,0);
  emphasizeProgress(meter,{matchMedia:()=>({matches:false})});assert.equal(calls.length,1);
  assert.equal(meter.value,51);assert.equal(meter.max,100);assert.equal(calls[0][1].duration,220);
});
test('forecast clears old data and ignores both success and 401 from a previous identity',async()=>{
  for(const failed of [false,true]){
    let resolve,reject,state,expired=0,count=0;
    const controller=createForecast({request:async(path,options)=>{
      assert.equal(path,'/api/v1/me/brs/forecast');
      if(++count===1)return new Promise((yes,no)=>{resolve=yes;reject=no;});
      assert.equal(options.headers['X-Mgimov-User'],'B');return {items:[{id:'B'}]};
    },publish:v=>state=v,expired:()=>expired++});
    const old=controller.setUser({id:'A',role:'student'});
    await controller.setUser({id:'B',role:'student'});
    if(failed)reject({status:401});else resolve({items:[{id:'A'}]});
    await old;assert.equal(expired,0);assert.equal(state.data.items[0].id,'B');
    controller.clear();assert.equal(state.state,'hidden');
    await controller.setUser({id:'T',role:'staff'});assert.equal(count,2);
  }
});
test('current protected 401 expires session; other failures show no stale scores',async()=>{
  for(const status of [401,403,503]){
    let state,expired=0;
    const controller=createForecast({request:async()=>{throw {status};},publish:v=>state=v,expired:()=>expired++});
    await controller.setUser({id:'A',role:'student'});
    assert.equal(expired,status===401?1:0);assert.equal(state.state,status===401?'hidden':'error');assert.equal(state.data,undefined);
  }
});
