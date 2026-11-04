import {addDays, weekDates} from './utils/dates.js';
export function moscowToday(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/Moscow',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(now);
  const get = type => parts.find(p=>p.type===type).value;
  return `${get('year')}-${get('month')}-${get('day')}`;
}
export function createScheduleState({request,publish,today=moscowToday,timeoutMs=10000}) {
  let user=null,lastUser=null,view='today',selected=today(),generation=0,active=null;
  function clear() { generation++;active?.abort();active=null;user=null;publish({state:'hidden'}); }
  async function load() {
    if(!user)return;
    const owner=user.id,id=++generation;active?.abort();const abort=new AbortController();active=abort;
    const timer=setTimeout(()=>abort.abort(),timeoutMs);
    publish({state:'loading',view,selected});
    try {
      const data=await request('/api/v1/me/schedule',{query:{view,date:selected},headers:{'X-Mgimov-User':owner},signal:abort.signal});
      if(id!==generation || user?.id!==owner)return;
      if(data.view!==view || data.selected_date!==selected || !Array.isArray(data.days))throw new Error('Invalid schedule');
      publish({state:'ready',view,selected,data});
    } catch(error) {
      if(id!==generation)return;
      publish({state:'error',view,selected,message:error.status===401?'Сессия завершилась. Проверьте вход.':error.status===403?'Аккаунт или права изменились. Проверьте вход.':'Не удалось загрузить расписание. Повторите запрос.'});
    } finally { clearTimeout(timer);if(id===generation)active=null; }
  }
  return {
    clear,
    setUser(value) {
      if(!value || value.role!=='student'){clear();return;}
      if(value.id!==lastUser){view='today';selected=today();lastUser=value.id;}
      user=value;return load();
    },
    setView(value) {if(!['today','week'].includes(value))throw new TypeError('Invalid view');view=value;return load();},
    setDate(value) {weekDates(value);selected=value;return load();},
    move(direction) {if(![-1,1].includes(direction))throw new TypeError('Invalid direction');selected=addDays(view==='week'?weekDates(selected)[0]:selected,direction*(view==='week'?7:1));return load();},
    today() {selected=today();return load();},retry:load
  };
}
