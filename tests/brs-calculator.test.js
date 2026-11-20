import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {existsSync} from 'node:fs';
import {sanitizeSimulationPoints, simulateCourseBrs} from '../frontend/js/brs-calculator-state.js';
import {calculatorExplanation, renderCalculator} from '../frontend/js/brs-calculator.js';
import {mountLanguage} from '../frontend/js/language.js';

const root = fileURLToPath(new URL('../', import.meta.url));
const localPython = fileURLToPath(new URL('../.venv/Scripts/python.exe', import.meta.url));
// Worktrees may share the explicitly selected project interpreter.
const python = process.env.MGIMOV_TEST_PYTHON || (existsSync(localPython) ? localPython : 'python');
const samples = JSON.parse(execFileSync(python, ['-B','-m','tests.brs_calculator_fixture'],
  {cwd:root, encoding:'utf8', timeout:30000, maxBuffer:2*1024*1024}));
const course = (name, control='exam') => samples[name].items.find(row => row.control === control);

test('real backend JSON maps overlapping event prefixes to exact categories', () => {
  const row = course('60'), sim = simulateCourseBrs(row);
  assert.equal(sim.simulatedTotal,60);
  assert.deepEqual(Object.fromEntries(sim.events.map(event => [event.code,event.categoryCode])),
    {EXAM_MAIN:'EXAM',EXAM_ESSAY:'ESSAY',QUIZ_RESULT:'QUIZ',FINAL_RESULT:'FINAL'});
  assert.equal(sim.grade,null);
  assert.equal(sim.publishedTotal,60);
});

test('real 49/50/51 JSON preserves backend totals and outcomes', () => {
  for (const total of [49,50,51]) for (const control of ['exam','credit','graded_credit']) {
    const row=course(String(total),control), sim=simulateCourseBrs(row);
    assert.equal(sim.simulatedTotal,row.published_points);
    if(control==='exam') assert.equal(sim.admitted,row.admission);
    if(control==='credit') assert.equal(sim.outcome,row.predicted_result);
    if(control==='graded_credit') assert.equal(sim.grade,row.predicted_result);
  }
});

test('full requirements remain active after replacing previously sufficient results', () => {
  const row=course('60');
  assert.deepEqual(row.required_shortfalls,[]);
  assert.equal(simulateCourseBrs(row,{EXAM_ESSAY:0,FINAL_RESULT:20}).admitted,false);
  assert.equal(simulateCourseBrs(row,{EXAM_MAIN:0,FINAL_RESULT:20}).admitted,false);
  assert.equal(simulateCourseBrs(course('required_missing')).admitted,false);
  const optional=structuredClone(course('required_missing'));
  optional.events.find(event=>event.code==='EXAM_ESSAY').required=false;
  assert.equal(simulateCourseBrs(optional).admitted,true);
  assert.equal(simulateCourseBrs(course('required_missing'),{EXAM_ESSAY:10}).admitted,true);
  assert.equal(simulateCourseBrs(course('category_missing')).admitted,false);
  assert.equal(simulateCourseBrs(course('category_missing'),{EXAM_MAIN:10}).admitted,true);
});

test('unknown categories and incomplete rules fail closed without mutating the input', () => {
  const row=course('60'), before=JSON.stringify(row);
  for(const change of [r=>delete r.events[0].category_code,r=>r.events[0].category_code='UNKNOWN',
    r=>delete r.events[1].required,r=>delete r.categories[0].admission_min,
    r=>r.events=[],r=>r.categories=[]]) {
    const broken=structuredClone(row); change(broken);
    assert.equal(simulateCourseBrs(broken).available,false);
  }
  simulateCourseBrs(row,{EXAM_MAIN:10});
  assert.equal(JSON.stringify(row),before);
});

test('only bounded integers are accepted, including zero and maxima', () => {
  for(const value of [0,20,'0','20']) assert.equal(sanitizeSimulationPoints(value,20),Number(value));
  for(const value of [-1,21,0.5,'0.5','abc',' ','1e1',true,Infinity,NaN]) {
    assert.throws(()=>sanitizeSimulationPoints(value,20),RangeError);
    assert.equal(simulateCourseBrs(course('60'),{EXAM_MAIN:value}).available,false);
  }
  assert.equal(sanitizeSimulationPoints('',20),null);
});

test('empty published data, published zero and a manual scenario stay distinct', () => {
  for(const control of ['exam','credit','graded_credit']) {
    const empty=simulateCourseBrs(course('empty',control));
    assert.equal(empty.simulatedTotal,null); assert.equal(empty.grade,null); assert.equal(empty.outcome,null);
    const zero=simulateCourseBrs(course('zero',control));
    assert.equal(zero.simulatedTotal,0); assert.equal(zero.hasHypothetical,false);
    const manual=simulateCourseBrs(course('empty',control),{EXAM_MAIN:20});
    assert.equal(manual.simulatedTotal,20); assert.equal(manual.publishedTotal,null);
    assert.equal(manual.hasHypothetical,true);
    if(control!=='exam') assert.equal(manual.outcome,null);
  }
});

function rendererDom() {
  const make=tag=>({tag,children:[],textContent:'',value:'',listeners:{},attributes:{},
    classList:{add(){},remove(){}},setAttribute(k,v){this.attributes[k]=v;},
    append(...nodes){this.children.push(...nodes);},replaceChildren(){this.children=[];},
    addEventListener(name,fn){this.listeners[name]=fn;}});
  const document={createElement:make};
  const root=make('article');
  const all=node=>[node,...node.children.flatMap(all)];
  const text=node=>all(node).map(x=>x.textContent).join(' ');
  return {document,root,all,text};
}

test('renderer RU/EN covers outcomes, maxima, invalid input, empty data and reset', () => {
  const button={addEventListener(_,fn){this.click=fn;},setAttribute(){}};
  const document={documentElement:{},getElementById:()=>button,querySelectorAll:()=>[],
    createTreeWalker:()=>({nextNode:()=>null}),dispatchEvent(){}};
  mountLanguage(document,{request:async()=>({language:'ru'}),csrf:()=>'',
    storage:{getItem:()=>null,setItem(){},removeItem(){}}});
  for(const language of ['ru','en']) {
    if(language==='en') button.click();
    const d=rendererDom(); renderCalculator(d.document,d.root,course('empty','graded_credit'));
    assert.match(d.text(d.root),language==='ru'?/Опубликованных результатов нет/:/No published results/);
    const input=d.all(d.root).find(n=>n.tag==='input');
    assert.equal(input.step,'1');
    assert.match(input.attributes['aria-label'],language==='ru'?/максимум/:/maximum/);
    input.value='0.5'; input.listeners.input();
    assert.match(d.text(d.root),language==='ru'?/Введите целое/:/Enter an integer/);
    d.all(d.root).find(n=>n.tag==='button').listeners.click();
    assert.equal(input.value,'');
    assert.match(d.text(d.root),language==='ru'?/Опубликованных результатов нет/:/No published results/);
    const explanation=calculatorExplanation(simulateCourseBrs(course('60')));
    assert.match(explanation,language==='ru'?/Условия допуска/:/Admission requirements/);
    if(language==='en') assert.doesNotMatch(explanation,/[А-Яа-я]/);
  }
  button.click();
});
