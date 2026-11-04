// Personal records live only in memory and are discarded with the account state.
export function createAcademicsState({request,publish,timeoutMs=10000}) {
  let user=null,generation=0,active=null;
  function clear(){generation++;active?.abort();active=null;user=null;publish({state:'hidden'});}
  async function load(){
    if(!user)return;
    const owner=user.id,id=++generation;active?.abort();const abort=new AbortController();active=abort;
    const timer=setTimeout(()=>abort.abort(),timeoutMs);publish({state:'loading'});
    try {
      const data=await request('/api/v1/me/gradebook',{headers:{'X-Mgimov-User':owner},signal:abort.signal});
      if(id!==generation || user?.id!==owner)return;
      if(!Array.isArray(data.semesters) || !Array.isArray(data.upcoming) || !Array.isArray(data.debts) || !data.progress)throw new Error('Invalid academics');
      publish({state:'ready',data});
    }catch(error){
      if(id===generation)publish({state:'error',message:error.status===401?'Сессия завершилась. Проверьте вход.':error.status===403?'Аккаунт или права изменились. Проверьте вход.':'Не удалось загрузить успеваемость. Повторите запрос.'});
    }finally{clearTimeout(timer);if(id===generation)active=null;}
  }
  return {clear,retry:load,setUser(value){if(!value || value.role!=='student'){clear();return;}user=value;return load();}};
}
