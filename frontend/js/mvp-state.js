// Requests are bound to an identity generation. Restoring a view never submits work.
export function createWorkspace({request,csrf,publish,timeout=15000}) {
  let user=null,epoch=0,abort=null,suspended=false;
  let notificationCursor=null,nextCursor=null,notificationHistory=[];
  function resetNotifications(){notificationCursor=null;nextCursor=null;notificationHistory=[];}
  async function bounded(path,options={}) {
    const controller=new AbortController();
    const cancel=()=>controller.abort();options.signal?.addEventListener('abort',cancel,{once:true});
    if(options.signal?.aborted)controller.abort();
    let timer;
    try {
      return await Promise.race([request(path,{...options,signal:controller.signal}),new Promise((_,reject)=>{timer=setTimeout(()=>{controller.abort();reject(new Error('timeout'));},timeout);})]);
    } finally {clearTimeout(timer);options.signal?.removeEventListener('abort',cancel);}
  }
  async function load() {
    if(!user||suspended)return;
    const generation=++epoch,owner=user;abort?.abort();abort=new AbortController();
    const options={signal:abort.signal,headers:{'X-MGIMOv-User':owner.id}};
    publish({state:'loading',user:owner});
    try {
      const names=owner.role==='staff'?['notifications','documents','students','catalogue','lessons','requests']:['notifications','documents','schedule','progress','requests'];
      const paths={notifications:'/api/v1/me/notifications',documents:owner.role==='staff'?'/api/v1/staff/documents':'/api/v1/me/documents',students:'/api/v1/staff/students',catalogue:'/api/v1/staff/catalogue',lessons:'/api/v1/staff/lessons',requests:owner.role==='staff'?'/api/v1/staff/requests':'/api/v1/me/requests',schedule:'/api/v1/me/schedule',progress:'/api/v1/me/progress'};
      const values=await Promise.all(names.map(name=>bounded(paths[name],name==='notifications'&&notificationCursor?{...options,query:{cursor:notificationCursor}}:options)));
      if(generation!==epoch||suspended)return;
      const data=Object.fromEntries(names.map((name,i)=>[name,values[i]]));
      nextCursor=data.notifications.next_cursor??null;
      data.notifications.has_previous=notificationHistory.length>0;
      publish({state:'ready',user:owner,data});
    } catch(error) {
      if(generation!==epoch)return;
      if([401,403].includes(error.status)){user=null;publish({state:'anonymous',message:'Проверьте вход и права доступа.'});}
      else publish({state:'error',user:owner,message:'Не удалось обновить кабинет. Повторите загрузку.'});
    }
  }
  return {
    identity(next,{suspend=false}={}) {
      ++epoch;abort?.abort();
      if(!next){suspended=suspend;if(!suspend){user=null;resetNotifications();}publish({state:suspend?'suspended':'anonymous'});return;}
      if(!user||user.id!==next.id||user.role!==next.role)resetNotifications();
      user={id:next.id,role:next.role};suspended=false;return load();
    },
    refresh:load,
    nextNotifications(){if(!user||suspended||!nextCursor)return;notificationHistory.push(notificationCursor);notificationCursor=nextCursor;nextCursor=null;return load();},
    previousNotifications(){if(!user||suspended||!notificationHistory.length)return;notificationCursor=notificationHistory.pop();return load();},
    async action(path,body={}) {
      if(!user||suspended)throw new Error('Проверьте вход.');
      const generation=epoch,owner=user;
      try {
        const value=await bounded(path,{method:'POST',body,headers:{'X-MGIMOv-User':owner.id,'X-CSRF-Token':csrf()}});
        if(generation!==epoch||suspended)throw new Error('Состояние входа изменилось. Обновите данные перед повтором.');
        return value;
      } catch(error) {
        if(generation===epoch&&[401,403].includes(error.status)){user=null;++epoch;publish({state:'anonymous',message:'Проверьте вход и права доступа.'});}
        throw error;
      }
    },
    async document(id) {
      if(!user||suspended)throw new Error('Проверьте вход.');
      const generation=epoch;
      const value=await bounded('/api/v1/me/documents/'+id,{headers:{'X-MGIMOv-User':user.id}});
      if(generation!==epoch||suspended)throw new Error('Состояние входа изменилось.');return value;
    }
  };
}
