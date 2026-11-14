import test from 'node:test';
import assert from 'node:assert/strict';
import {mountLanguage,t,locale} from '../frontend/js/language.js';

test('public language survives reload and is applied to the confirmed account only',async()=>{
  const values=new Map();
  const storage={getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};
  const requests=[];
  function mount(){
    const text={nodeValue:' Логин '};
    const button={addEventListener(_,fn){this.click=fn;},setAttribute(){}};
    const document={documentElement:{},getElementById:()=>button,
      createTreeWalker(){let first=true;return {nextNode(){if(!first)return null;first=false;return text;}};},
      querySelectorAll:()=>[],dispatchEvent(){}};
    const controller=mountLanguage(document,{storage,csrf:()=>'test',
      request:async(path,options)=>{requests.push({path,options});return {language:'ru'};}});
    return {controller,document,button,text};
  }
  const first=mount();
  assert.equal(first.document.documentElement.lang,'ru');
  first.button.click();
  assert.equal(first.text.nodeValue,' Username ');
  assert.equal(locale(),'en-GB');
  assert.deepEqual(requests,[]);
  const restored=mount();
  assert.equal(restored.document.documentElement.lang,'en');
  restored.controller.setUser({id:'first'});
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(requests[0].options.body,{language:'en'});
  assert.equal(requests[0].options.headers['X-Mgimov-User'],'first');
  restored.controller.setUser({id:'second'});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(restored.document.documentElement.lang,'ru');
  assert.equal(t('Логин'),'Логин');
  assert.equal(requests[1].options.method,undefined);
});
