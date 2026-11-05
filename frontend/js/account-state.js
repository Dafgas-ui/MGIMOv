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
