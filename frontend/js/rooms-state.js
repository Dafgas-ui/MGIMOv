export function createRoomSearch({request,publish,expired}){
 let owner=null,epoch=0,abort;
 function clear(){epoch++;abort?.abort();publish({state:'hidden'});}
 async function run(path,query){
  if(!owner)return;const id=owner.id,current=++epoch;abort?.abort();abort=new AbortController();
  const pending=abort,timer=setTimeout(()=>pending.abort(),10000);publish({state:'loading',catalogue:path.endsWith('/catalogue')});
  try{const data=await request(path,{query,signal:pending.signal,headers:{'X-Mgimov-User':id}});
   if(current===epoch)publish({state:'ready',data,catalogue:path.endsWith('/catalogue')});
  }catch(error){if(current!==epoch)return;publish({state:'error',status:error.status});if(error.status===401){clear();owner=null;expired();}}
  finally{clearTimeout(timer);}
 }
 return {clear,setUser(value){clear();owner=value?.role==='student'?value:null;return owner?run('/api/v1/me/rooms/catalogue'):Promise.resolve();},search:query=>run('/api/v1/me/rooms/availability',query)};
}
