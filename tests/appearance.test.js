import test from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {appearancePalettes,calculateAppearanceAccent,createAppearanceState,createAccountState,normalizeAppearance} from '../frontend/js/account-state.js';

function memoryStorage() {
  const values=new Map();
  return {values,getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)};
}

test('all standard palettes keep link and button text contrast in light and dark themes',()=>{
  for(const [name,palette] of Object.entries(appearancePalettes))for(const theme of ['light','dark']) {
    const result=calculateAppearanceAccent(palette.color,theme);
    assert.ok(result.linkRatio>=4.5,`${name} ${theme} link contrast ${result.linkRatio}`);
    assert.ok(result.textRatio>=4.5,`${name} ${theme} button text contrast ${result.textRatio}`);
  }
});

test('custom colors are normalized and adjusted to readable contrast',()=>{
  assert.equal(normalizeAppearance({theme:'invalid',palette:'custom',custom:'#AbCdEf'}).custom,'#abcdef');
  assert.equal(normalizeAppearance({palette:'custom',custom:'red'}).custom,appearancePalettes.blue.color);
  for(const seed of ['#000000','#ffffff','#ffff00','#777777'])for(const theme of ['light','dark']) {
    const result=calculateAppearanceAccent(seed,theme);
    assert.ok(result.adjusted||result.linkRatio>=4.5);
    assert.ok(result.linkRatio>=4.5);
    assert.ok(result.textRatio>=4.5);
  }
});

test('first load uses Light and Blue on dark OS, with System available by choice',async()=>{
  const html=readFileSync(new URL('../frontend/index.html',import.meta.url),'utf8');
  const root=html.match(/<html\b[^>]*>/)[0];
  assert.match(root,/\bdata-theme="light"/);
  assert.match(root,/\bdata-theme-mode="light"/);
  assert.match(root,/\bdata-palette="blue"/);
  assert.match(html,/<meta name="color-scheme" content="light">/);
  let dark=true;const applied=[];
  const appearance=createAppearanceState({prefersDark:()=>dark,apply:value=>applied.push(value)});
  await appearance.setUser(null);
  assert.equal(applied.at(-1).resolvedTheme,'light');
  assert.equal(applied.at(-1).settings.palette,'blue');
  appearance.update({theme:'system'});
  assert.equal(applied.at(-1).resolvedTheme,'dark');
  dark=false;appearance.systemThemeChanged();
  assert.equal(applied.at(-1).resolvedTheme,'light');
  appearance.update({theme:'light'});dark=true;appearance.systemThemeChanged();
  assert.equal(applied.at(-1).resolvedTheme,'light');
});

test('a repeated identity refresh does not reset the active account appearance',async()=>{
  const appearance=createAppearanceState({storage:memoryStorage(),cryptoObject:webcrypto});
  await appearance.setUser('student-A');
  appearance.update({theme:'dark',palette:'bordeaux'});
  await appearance.setUser('student-A');
  assert.equal(appearance.getSettings().theme,'dark');
  assert.equal(appearance.getSettings().palette,'bordeaux');
});

test('account preferences survive reload and remain isolated between accounts',async()=>{
  const storage=memoryStorage();
  const first=createAppearanceState({storage,cryptoObject:webcrypto});
  await first.setUser('student-A');
  first.update({theme:'dark',palette:'ocean'});
  first.update({palette:'custom',custom:'#ffff00'});
  const [key]=storage.values.keys();
  assert.match(key,/^mgimov-appearance-v1:[a-f0-9]{64}$/);
  assert.equal(key.includes('student-A'),false);
  assert.equal([...storage.values.values()].some(value=>value.includes('student-A')),false);

  const other=createAppearanceState({storage,cryptoObject:webcrypto});
  await other.setUser('student-B');
  assert.deepEqual(other.getSettings(),{version:2,theme:'light',palette:'blue',custom:'#14588f'});

  const reloaded=createAppearanceState({storage,cryptoObject:webcrypto});
  await reloaded.setUser('student-A');
  assert.deepEqual(reloaded.getSettings(),{version:2,theme:'dark',palette:'custom',custom:'#ffff00'});
  assert.equal(JSON.parse(storage.values.get(key)).theme,'dark');
  const savedSystem={...reloaded.getSettings(),theme:'system'};
  storage.values.set(key,JSON.stringify(savedSystem));
  const legacy=createAppearanceState({storage,cryptoObject:webcrypto,prefersDark:()=>true});
  await legacy.setUser('student-A');
  assert.deepEqual(legacy.getSettings(),savedSystem);
  assert.equal(JSON.parse(storage.values.get(key)).theme,'system');
  reloaded.reset();
  assert.deepEqual(reloaded.getSettings(),{version:2,theme:'light',palette:'blue',custom:'#14588f'});
  assert.equal(storage.values.has(key),false);
});

test('legacy Emerald migrates once, while chosen themes and non-default colors survive',async()=>{
  const storage=memoryStorage();
  const make=()=>createAppearanceState({storage,cryptoObject:webcrypto});
  const first=make();await first.setUser('legacy');first.update({theme:'dark'});
  const [key]=storage.values.keys();
  for(const [palette,custom,expected] of [['emerald','#245c45','blue'],['bordeaux','#245c45','bordeaux'],['custom','#245c45','custom']]){
    storage.values.set(key,JSON.stringify({version:1,theme:'dark',palette,custom}));
    const state=make();await state.setUser('legacy');
    const saved=JSON.parse(storage.values.get(key));
    assert.deepEqual(state.getSettings(),{version:2,theme:'dark',palette:expected,custom:palette==='custom'?custom:'#14588f'});
    assert.deepEqual(saved,state.getSettings());
  }
  first.update({palette:'emerald'});const reload=make();await reload.setUser('legacy');
  assert.equal(reload.getSettings().palette,'emerald');
});

test('changing appearance leaves the authenticated session intact and logout still uses server state',async()=>{
  const calls=[];let authenticated=true,accountValue;
  const account=createAccountState({
    readCsrf:()=> 'csrf-test',publish:value=>accountValue=value,
    request:async(path)=>{
      calls.push(path);
      if(path.endsWith('/logout')){authenticated=false;return null;}
      if(!authenticated)throw Object.assign(new Error(),{status:401});
      if(path.endsWith('/profile'))return {user:{id:'student-A',role:'student'},profile:{full_name:'Synthetic'}};
      return {user:{id:'student-A',role:'student'}};
    }
  });
  await account.refresh();
  assert.equal(accountValue.state,'ready');
  const appearance=createAppearanceState({storage:memoryStorage(),cryptoObject:webcrypto});
  await appearance.setUser('student-A');
  appearance.update({theme:'dark',palette:'bordeaux'});
  assert.equal(accountValue.state,'ready');
  assert.equal(calls.some(path=>path.endsWith('/logout')),false);
  await account.refresh();
  assert.equal(accountValue.state,'ready');
  await account.logout();
  assert.equal(accountValue.state,'anonymous');
  assert.ok(calls.some(path=>path.endsWith('/auth/logout')));
});
