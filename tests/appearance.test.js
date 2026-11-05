import test from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
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
  assert.equal(normalizeAppearance({palette:'custom',custom:'red'}).custom,appearancePalettes.emerald.color);
  for(const seed of ['#000000','#ffffff','#ffff00','#777777'])for(const theme of ['light','dark']) {
    const result=calculateAppearanceAccent(seed,theme);
    assert.ok(result.adjusted||result.linkRatio>=4.5);
    assert.ok(result.linkRatio>=4.5);
    assert.ok(result.textRatio>=4.5);
  }
});

test('system theme follows OS changes while fixed themes remain selected',async()=>{
  let dark=false;const applied=[];
  const appearance=createAppearanceState({prefersDark:()=>dark,apply:value=>applied.push(value)});
  await appearance.setUser(null);
  assert.equal(applied.at(-1).resolvedTheme,'light');
  dark=true;appearance.systemThemeChanged();
  assert.equal(applied.at(-1).resolvedTheme,'dark');
  appearance.update({theme:'light'});dark=false;appearance.systemThemeChanged();
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
  assert.deepEqual(other.getSettings(),{version:1,theme:'system',palette:'emerald',custom:'#245c45'});

  const reloaded=createAppearanceState({storage,cryptoObject:webcrypto});
  await reloaded.setUser('student-A');
  assert.deepEqual(reloaded.getSettings(),{version:1,theme:'dark',palette:'custom',custom:'#ffff00'});
  reloaded.reset();
  assert.deepEqual(reloaded.getSettings(),{version:1,theme:'system',palette:'emerald',custom:'#245c45'});
  assert.equal(storage.values.has(key),false);
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
