// Personal data and staff drafts stay in memory; retry metadata is an injected adapter.
export function createRequestsState({request,publish,readCsrf,operations=null,onMutation=()=>{},newKey=()=>crypto.randomUUID().replaceAll('-',''),timeoutMs=10000}){
  let user=null,generation=0,active=null,busy=false,offset=0,selected=null,view=null,pending=null,recovery=null,restored=false,identityReady=false;
  const drafts=new Map();
  const replyDrafts=new Map();let pageFilter='';
  const path=()=>user?.role==='staff'?'/api/v1/staff/requests':'/api/v1/me/requests';
  function clear({discardOperation=false}={}){generation++;active?.abort();active=null;busy=false;user=null;offset=0;selected=null;view=null;pending=null;recovery=null;restored=false;identityReady=false;drafts.clear();replyDrafts.clear();pageFilter='';if(discardOperation)operations?.remove();publish({state:'hidden'});}
  function suspend(){generation++;active?.abort();active=null;busy=false;view=null;identityReady=false;publish({state:'suspended'});}
  async function run(operation,onConfirmed){
    if(!user || !identityReady || busy)return false;
    const owner=user.id,role=user.role,base=path(),id=++generation;
    const abort=new AbortController();active=abort;busy=true;view=null;
    const timer=setTimeout(()=>abort.abort(),timeoutMs);
    publish({state:'loading',role,recovery});
    const current=()=>id===generation && user?.id===owner;
    const get=(url,options={})=>request(url,{...options,headers:{'X-Mgimov-User':owner,...(options.method==='POST'?{'X-CSRF-Token':readCsrf()}:{}),...options.headers},signal:abort.signal});
    try{
      if(role==='student' && !restored){
        const result=operations?await operations.restore(owner):{state:'none'};
        if(!current())return false;
        if(result.state==='pending'){pending=result.entry;recovery={type:pending.type};}
        else if(result.state==='mismatch')operations?.remove();
        else if(['lost','unavailable'].includes(result.state))recovery={lost:true};
        restored=true;
      }
      if(operation){const item=await operation(get,base,current);if(!current())return false;selected=item.id;onConfirmed?.();onMutation();}
      const [list,detail]=await Promise.all([get(base,{query:{offset:String(offset)}}),selected?get(base+'/'+selected):Promise.resolve(null)]);
      if(id!==generation || user?.id!==owner)return false;
      if(!Array.isArray(list.items) || (detail && (!Array.isArray(detail.history) || !Array.isArray(detail.actions))))throw new Error('Invalid requests');
      view={state:'ready',role,...list,detail,recovery};publish(view);return true;
    }catch(error){
      if(current()){
        if(error.status===401 || error.status===403){drafts.clear();replyDrafts.clear();identityReady=false;}
        else if(role==='staff' && error.status===404 && selected){drafts.delete(selected);replyDrafts.delete(selected);}
      }
      if(id===generation)publish({state:'error',role,recovery,message:error.code==='retry-storage'?'Не удалось сохранить технический ключ. Отправка не выполнена. Проверьте доступность хранилища вкладки.':error.code==='retry-type'?'Осталась неподтверждённая отправка другого типа. Проверьте список или явно начните отдельную заявку.':error.code==='retry-lost'?'Прежнюю отправку восстановить не удалось. Проверьте список перед созданием отдельной заявки.':error.status===409?'Обращение изменилось либо содержимое отличается от прежней отправки. Обновите список и проверьте результат; автоматического повтора решения нет.':error.status===429?'Лимит обращений исчерпан. Повторите позже.':error.status===401 || error.status===403?'Проверьте вход и права доступа.':error.status===422?'Проверьте обязательные поля и их длину.':'Не удалось подтвердить операцию. Обновите список или повторите отправку с теми же полями.'});
      return false;
    }finally{clearTimeout(timer);if(id===generation){active=null;busy=false;}}
  }
  return {clear,suspend,isBusy:()=>busy,
    setUser(value){if(!value || !['student','staff'].includes(value.role)){clear();return;}if((user && value.id!==user.id) || value.role==='staff')operations?.remove();if(value.id!==user?.id || value.role!==user?.role)clear();user=value;identityReady=true;return run();},
    setDraft(id,text){if(identityReady && user?.role==='staff' && selected===id && typeof text==='string')drafts.set(id,text.slice(0,1000));},
    getDraft(id){return user?.role==='staff'?drafts.get(id) || '':'';},
    getFilter:()=>pageFilter,setFilter(value){if(identityReady)pageFilter=String(value).slice(0,200);},
    setReplyDraft(id,text){if(identityReady&&user?.role==='staff'&&selected===id&&typeof text==='string')replyDrafts.set(id,text.slice(0,1000));},
    getReplyDraft(id){return user?.role==='staff'?replyDrafts.get(id)||'':'';},
    newOperation(){if(!user || !identityReady || busy)return false;operations?.remove();pending=null;recovery=null;restored=true;if(view){view={...view,recovery:null};publish(view);}return true;},
    retry(){return run();},open(id){if(!identityReady || busy)return;selected=id;return run();},
    close(){if(!identityReady||busy)return;selected=null;return run();},
    page(next){if(!identityReady || busy)return;offset=next;selected=null;return run();},
    async create(payload){
      if(!identityReady || user?.role!=='student' || busy)return false;
      const content={type:payload.type,purpose:payload.type==='appeal'?'':payload.purpose.trim(),message:payload.message.trim()};
      offset=0;
      const ok=await run(async(get,base,current)=>{
        if(recovery?.lost)throw Object.assign(new Error(),{code:'retry-lost'});
        if(pending && pending.type!==content.type)throw Object.assign(new Error(),{code:'retry-type'});
        if(!pending){
          const key=newKey();
          try{if(operations && !await operations.save(user.id,content.type,key,current))throw new Error();}
          catch{throw Object.assign(new Error(),{code:'retry-storage'});}
          if(!current())throw new Error('stale');
          pending={key,type:content.type};recovery={type:content.type};
        }
        return get(base,{method:'POST',body:{...content,request_key:pending.key}});
      });
      if(ok){operations?.remove(pending?.key);pending=null;recovery=null;view={...view,recovery:null};publish(view);}return ok;
    },
    change(action,comment){
      if(!view?.detail || busy)return;
      const item=view.detail,student=user.role==='student';
      if(!item.actions.includes(action))return;
      if(!student)drafts.set(item.id,comment);
      return run((get,base)=>get(base+'/'+item.id+(student?'/cancel':'/decision'),{method:'POST',body:{version:item.version,...(student?{}:{action}),comment}}),()=>{if(!student)drafts.delete(item.id);});
    },
    reply(comment){
      if(!view?.detail||busy||user?.role!=='staff'||!['submitted','processing'].includes(view.detail.status))return false;
      const item=view.detail;replyDrafts.set(item.id,comment);
      return run((get,base)=>get(base+'/'+item.id+'/reply',{method:'POST',body:{version:item.version,comment}}),()=>replyDrafts.delete(item.id));
    },
    certificate(action){
      if(!view?.detail || busy || user?.role!=='staff')return false;
      const item=view.detail;
      if(action==='sign' && (item.status!=='approved' || item.type==='appeal' || item.document))return false;
      if(action==='deliver' && (!item.document || item.document.delivered_at))return false;
      if(!['sign','deliver'].includes(action))return false;
      return run(async get=>{
        const url=action==='sign'?'/api/v1/staff/requests/'+item.id+'/sign':'/api/v1/staff/documents/'+item.document.id+'/deliver';
        await get(url,{method:'POST',body:action==='sign'?{version:item.version}:{}});
        return {id:item.id};
      });
    }
  };
}
