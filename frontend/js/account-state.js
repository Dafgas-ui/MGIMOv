// Identity-bound, memory-only state. Late responses never restore a cleared profile.
export function createAccountState({request, readCsrf, publish, signalChange = () => {}, timeoutMs = 10000}) {
  let generation = 0, active = null, busy = false, owner = null, logoutOwner = null, checkingOwner = null;
  const emit = (state, message, extra = {}) => publish({state,message,...extra});
  function clear(message = 'Проверьте вход в систему.') {
    generation++; active?.abort(); active = null; busy = false; owner = null; checkingOwner = null;
    emit('anonymous',message);
  }
  function suspend() {
    const expected=owner || checkingOwner;
    generation++;active?.abort();active=null;busy=false;checkingOwner=null;
    if(logoutOwner){owner=null;emit('logout-pending','Выход не подтверждён. Повторите выход; личные данные скрыты.');return;}
    owner=expected;
    emit('suspended','Вкладка скрыта. При возвращении проверим вход.');
  }
  async function perform(kind, credentials, background = false) {
    // An anonymous login form has no private session to poll; preserve an unfinished draft.
    if (kind === 'refresh' && background && !owner) return false;
    if (busy) return false;
    const expected = owner || logoutOwner;
    checkingOwner=expected;
    if (kind === 'logout') logoutOwner = expected;
    const id = ++generation;
    active?.abort(); const abort = new AbortController(); active = abort; busy = true; owner = null;
    const timer = setTimeout(() => abort.abort(), timeoutMs);
    emit('loading', kind === 'logout' ? 'Завершаем сессию…' : 'Проверяем вход…',{operation:kind});
    const call = (path, options = {}) => request(path, {...options, signal: abort.signal});
    const current = () => id === generation;
    try {
      if (kind === 'login') {
        if (logoutOwner) throw new Error('logout-pending');
        signalChange();
        const bootstrap = await call('/api/v1/auth/csrf');
        if (!current()) return false;
        await call('/api/v1/auth/login', {method:'POST',body:credentials,headers:{'X-CSRF-Token':bootstrap.csrf}});
        if (!current()) return false;
        signalChange();
      } else if (kind === 'logout') {
        if (!expected) throw new Error('identity-unknown');
        signalChange();
        await call('/api/v1/auth/logout', {method:'POST',body:{},headers:{'X-CSRF-Token':readCsrf(),'X-Mgimov-User':expected}});
        if (!current()) return false;
        logoutOwner = null; signalChange(); emit('anonymous','Вы вышли из системы. Можно войти снова.'); return true;
      }
      const identity = await call('/api/v1/auth/me', {headers:expected && !logoutOwner ? {'X-Mgimov-User':expected} : {}});
      if (!current()) return false;
      if (logoutOwner) {
        if (identity.user?.id === logoutOwner) throw new Error('logout-pending');
        logoutOwner = null;
      }
      const user = identity.user;
      if (!user || typeof user.id !== 'string' || !['student','staff'].includes(user.role)) throw new Error('invalid-identity');
      const data = await call('/api/v1/me/profile', {headers:{'X-Mgimov-User':user.id}});
      if (!current()) return false;
      if (data.user?.id !== user.id || data.user?.role !== user.role) throw new Error('identity-changed');
      owner = user.id;
      emit('ready','Вход подтверждён.',data); return true;
    } catch (error) {
      if (!current()) return false;
      if (error.status === 401) {
        logoutOwner = null; emit('anonymous',kind === 'login' ? 'Неверный логин или пароль.' : 'Сессия отсутствует или завершилась. Войдите снова.');
      } else if (logoutOwner) {
        emit('logout-pending','Выход не подтверждён. Повторите выход; личные данные скрыты.');
      } else {
        const message = error.status === 429 ? 'Слишком много попыток. Повторите позже.'
          : error.status === 403 ? 'Проверка безопасности не пройдена. Повторите проверку входа.'
          : error.status === 422 ? 'Проверьте логин и пароль.'
          : 'Сервер недоступен или ответ не получен. Повторите проверку входа.';
        emit('error',message,{identityInvalidated:error.status===403});
      }
      return false;
    } finally {
      clearTimeout(timer);
      if (current()) { busy = false; active = null; checkingOwner = null; }
    }
  }
  return { login:(login,password)=>perform('login',{login,password}), refresh:({background = false} = {})=>perform('refresh',undefined,background),
    logout:()=>perform('logout'), clear, suspend, isBusy:()=>busy };
}

export const appearancePalettes = Object.freeze({
  emerald:{name:'Emerald',color:'#245c45'},
  ocean:{name:'Ocean',color:'#185b87'},
  bordeaux:{name:'Bordeaux',color:'#842f49'},
  indigo:{name:'Indigo',color:'#4c4c91'},
  terracotta:{name:'Terracotta',color:'#9c4b2f'},
  slate:{name:'Slate',color:'#4c5b66'}
});

const appearanceDefault = Object.freeze({version:1,theme:'system',palette:'emerald',custom:'#245c45'});
const validAppearanceHex = value => typeof value==='string' && /^#[\da-f]{6}$/i.test(value);
const appearanceRgb = value => [1,3,5].map(index=>parseInt(value.slice(index,index+2),16));
const appearanceHex = values => '#'+values.map(value=>Math.round(value).toString(16).padStart(2,'0')).join('');
function appearanceMix(first,second,amount) {
  const a=appearanceRgb(first),b=appearanceRgb(second);
  return appearanceHex(a.map((value,index)=>value*(1-amount)+b[index]*amount));
}
function appearanceLuminance(value) {
  return appearanceRgb(value).map(channel=>channel/255)
    .map(channel=>channel<=.04045?channel/12.92:((channel+.055)/1.055)**2.4)
    .reduce((sum,channel,index)=>sum+channel*[.2126,.7152,.0722][index],0);
}
export function appearanceContrast(first,second) {
  const a=appearanceLuminance(first),b=appearanceLuminance(second);
  return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
}
export function normalizeAppearance(input={}) {
  if(!input||typeof input!=='object')input={};
  return {
    version:1,
    theme:['system','light','dark'].includes(input.theme)?input.theme:'system',
    palette:Object.hasOwn(appearancePalettes,input.palette)||input.palette==='custom'?input.palette:'emerald',
    custom:validAppearanceHex(input.custom)?input.custom.toLowerCase():appearancePalettes.emerald.color
  };
}
export function calculateAppearanceAccent(seed,theme='light') {
  seed=validAppearanceHex(seed)?seed.toLowerCase():appearancePalettes.emerald.color;
  const dark=theme==='dark';
  const background=dark?'#171e1a':'#f7f7f2';
  const surface=dark?'#1e2721':'#ffffff';
  const soft=dark?'#26332a':'#edf0e9';
  const accentSoft=appearanceMix(background,seed,dark?.12:.07);
  const surfaces=[background,surface,soft,accentSoft];
  let accent=seed;
  for(let step=0;step<=255;step++) {
    const candidate=appearanceMix(seed,dark?'#ffffff':'#000000',step/255);
    if(surfaces.every(value=>appearanceContrast(candidate,value)>=4.5)) {accent=candidate;break;}
  }
  const onAccent=appearanceContrast(accent,'#ffffff')>=appearanceContrast(accent,'#111611')?'#ffffff':'#111611';
  return {seed,accent,onAccent,accentSoft,focus:accent,
    linkRatio:Math.min(...surfaces.map(value=>appearanceContrast(accent,value))),
    textRatio:appearanceContrast(accent,onAccent),adjusted:accent!==seed};
}

async function appearanceStorageKey(accountId,cryptoObject) {
  if(typeof accountId!=='string'||!accountId||!cryptoObject?.subtle?.digest||typeof TextEncoder==='undefined')return null;
  const digest=await cryptoObject.subtle.digest('SHA-256',new TextEncoder().encode(accountId));
  const tag=[...new Uint8Array(digest)].map(value=>value.toString(16).padStart(2,'0')).join('');
  return `mgimov-appearance-v1:${tag}`;
}

// Browser storage contains only appearance settings. The account ID is used in memory
// to derive an opaque key and is never written to storage.
export function createAppearanceState({storage=null,cryptoObject=globalThis.crypto,prefersDark=()=>false,apply=()=>{},publish=()=>{}}={}) {
  let accountId=undefined,key=null,settings={...appearanceDefault},revision=0,generation=0,persistence='anonymous';
  function resolvedTheme() {return settings.theme==='system'?(prefersDark()?'dark':'light'):settings.theme;}
  function emit() {
    const theme=resolvedTheme();
    const seed=settings.palette==='custom'?settings.custom:appearancePalettes[settings.palette].color;
    const colors=calculateAppearanceAccent(seed,theme);
    const value={settings:{...settings},resolvedTheme:theme,colors,persistence};
    apply(value);publish(value);return value;
  }
  function persist() {
    if(!accountId||!key)return;
    try {storage.setItem(key,JSON.stringify(settings));persistence='saved';}
    catch {persistence='unavailable';}
  }
  async function setUser(nextAccountId) {
    const normalizedId=typeof nextAccountId==='string'&&nextAccountId?nextAccountId:null;
    if(normalizedId===accountId)return;
    const request=++generation;
    accountId=normalizedId;
    key=null;revision++;settings={...appearanceDefault};
    persistence=accountId?'loading':'anonymous';emit();
    if(!accountId)return;
    const capturedRevision=revision;
    try {
      const nextKey=await appearanceStorageKey(accountId,cryptoObject);
      if(request!==generation)return;
      if(!nextKey){persistence='unavailable';emit();return;}
      key=nextKey;
      if(!storage){persistence='unavailable';emit();return;}
      if(revision!==capturedRevision){persist();emit();return;}
      const raw=storage.getItem(key);
      if(raw) {
        const saved=JSON.parse(raw);
        if(saved?.version===1)settings=normalizeAppearance(saved);
      }
      persistence='ready';emit();
    } catch {
      if(request!==generation)return;
      key=null;persistence='unavailable';emit();
    }
  }
  function update(patch={}) {
    settings=normalizeAppearance({...settings,...patch});revision++;
    if(accountId) {if(key)persist();else if(persistence!=='unavailable')persistence='loading';}
    emit();
  }
  function reset() {
    settings={...appearanceDefault};revision++;
    if(accountId&&key) {
      try {storage.removeItem(key);persistence='saved';}
      catch {persistence='unavailable';}
    }
    emit();
  }
  return {setUser,update,reset,systemThemeChanged:emit,getSettings:()=>({...settings}),getPersistence:()=>persistence};
}
