// Presentation state only. Roles and business permissions always come from the server.
export const studentPages=[['home','Главная'],['schedule','Расписание'],['academics','Зачётка'],['attestations','Аттестации'],['coursework','Учебные работы'],['requests','Обращения'],['documents','Документы'],['notifications','Уведомления'],['profile','Профиль'],['settings','Настройки']];
export const staffPages=[['queue','Очередь'],['staff-schedule','Расписание'],['attestations','Аттестации'],['coursework','Учебные работы'],['certificates','Справки'],['students','Студенты'],['history','История'],['notifications','Уведомления'],['profile','Аккаунт'],['settings','Настройки']];
export function pagesFor(role){return role==='student'?studentPages:role==='staff'?staffPages:[['profile','Вход']];}
export function resolvePage(page,role){return pagesFor(role).some(([id])=>id===page)?page:role==='student'?'home':role==='staff'?'queue':'profile';}
export function currentLessons(schedule,now=new Date()){
  const parts=new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/Moscow',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(now);
  const get=type=>parts.find(p=>p.type===type)?.value;
  const date=`${get('year')}-${get('month')}-${get('day')}`,minute=Number(get('hour'))*60+Number(get('minute'));
  const lessons=(schedule.days.find(day=>day.date===schedule.selected_date)?.lessons||[]).filter(x=>x.placement!=='moved_from'&&x.status==='scheduled').sort((a,b)=>a.start_minute-b.start_minute);
  const live=date===schedule.today&&schedule.selected_date===schedule.today;
  return {live,date:schedule.selected_date,active:live?lessons.filter(x=>x.start_minute<=minute&&minute<x.end_minute):[],next:live?lessons.find(x=>x.start_minute>minute):lessons[0]};
}
