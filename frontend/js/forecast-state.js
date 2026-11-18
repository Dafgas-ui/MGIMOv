export function createForecast({request,publish,expired,timeoutMs=10000}){
  let user=null,generation=0,abort;
  const clear=()=>{generation++;abort?.abort();user=null;publish({state:'hidden'});};
  async function load(){
    if(user?.role!=='student')return;
    const owner=user.id,epoch=++generation;
    abort?.abort();abort=new AbortController();const current=abort,signal=current.signal;
    const timer=setTimeout(()=>current.abort(),timeoutMs);publish({state:'loading'});
    try{
      const data=await request('/api/v1/me/brs/forecast',{signal,headers:{'X-Mgimov-User':owner}});
      if(epoch!==generation||owner!==user?.id)return;
      if(!Array.isArray(data.items))throw new Error('Invalid forecast');
      publish({state:'ready',data});
    }catch(error){
      if(epoch!==generation)return;
      if(error.status===401){clear();expired();}
      else publish({state:'error'});
    }finally{clearTimeout(timer);}
  }
  return {clear,load,setUser(value){clear();if(value?.role==='student'){user=value;return load();}}};
}
