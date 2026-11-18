import {requestJson} from './api.js';
import {t,locale} from './language.js';
import {createScheduleState} from './schedule-state.js';
const kinds={lecture:'Лекция',seminar:'Семинар',practice:'Практика',lab:'Лабораторная'};
const names={date:'дата',start_minute:'время начала',end_minute:'время окончания',room_id:'аудитория',teacher_id:'преподаватель',status:'статус'};
export function clock(minutes) {return `${String(Math.floor(minutes/60)).padStart(2,'0')}:${String(minutes%60).padStart(2,'0')}`;}
function labelDate(day) {return new Date(day+'T12:00:00').toLocaleDateString(locale(),{weekday:'long',day:'numeric',month:'long'});}
export function calendarLayout(days) {
  const lessons=days.flatMap(day=>day.lessons);
  const start=Math.floor(lessons.reduce((min,item)=>Math.min(min,item.start_minute),480)/60)*60;
  const end=Math.ceil(lessons.reduce((max,item)=>Math.max(max,item.end_minute),1200)/60)*60;
  return {start,end,days:days.map(day=>{
    const lanes=[];
    const events=[...day.lessons].sort((a,b)=>a.start_minute-b.start_minute||a.end_minute-b.end_minute).map(lesson=>{
      const top=Math.min(lesson.start_minute,end-44),bottom=Math.max(lesson.end_minute,top+44);
      let lane=lanes.findIndex(until=>until<=top);
      if(lane<0)lane=lanes.length;
      lanes[lane]=bottom;
      return {lesson,lane,top:top-start,height:bottom-top};
    });
    return {...day,events,laneCount:Math.max(1,lanes.length)};
  })};
}
function showTime(item){return `${item.date} ${clock(item.start_minute)}–${clock(item.end_minute)}, ${item.building}, ${t('ауд.','room')} ${item.room}, ${item.teacher}${item.status==='cancelled'?t(' (отменено)',' (cancelled)'):''}`;}
function lessonCard(node,lesson) {
  const card=node('article','','lesson-card');
  if(lesson.status!=='scheduled')card.classList.add('lesson-inactive');
  card.append(node('p',`${clock(lesson.start_minute)}–${clock(lesson.end_minute)} · ${t(kinds[lesson.kind]||lesson.kind)}`,'lesson-time'),node('h4',lesson.subject));
  card.append(node('p',lesson.teacher),node('p',`${lesson.building} · ${t('ауд.','room')} ${lesson.room}`));
  const attendance=node('button','Посещаемость');attendance.type='button';attendance.dataset.attendance=lesson.id;card.append(attendance);
  if(lesson.placement==='moved_from')card.append(node('p',`${t('Перенесено на','Rescheduled to')} ${labelDate(lesson.actual.date)}, ${clock(lesson.actual.start_minute)}–${clock(lesson.actual.end_minute)}`,'change-badge'));
  else if(lesson.status==='cancelled')card.append(node('p','Занятие отменено','change-badge'));
  else if(lesson.changes.length)card.append(node('p','Расписание изменено','change-badge'));
  for(const change of lesson.changes) {
    card.append(node('p',`${change.reason} · ${t('изменено','changed')}: ${change.fields.map(key=>t(names[key]||key)).join(', ')}`,'change-detail'));
    card.append(node('p',`${t('Было','Before')}: ${showTime(change.before)}`,'change-detail'),node('p',`${t('Стало','After')}: ${showTime(change.after)}`,'change-detail'));
  }
  return card;
}
function renderWeek(root,data,node) {
  const layout=calendarLayout(data.days);
  const picker=node('div','','week-picker'),grid=node('div','','week-grid'),mobile=node('div','','week-mobile');
  const details=node('section','','week-details');details.tabIndex=-1;details.hidden=true;
  details.setAttribute('aria-label',t('Детали занятия'));
  const scroll=node('div','','week-scroll');scroll.append(grid);
  root.append(picker,mobile,details,scroll);
  let selected=data.selected_date;
  function showDay(day){
    selected=day.date;
    for(const entry of choices)entry.button.setAttribute('aria-pressed',String(entry.day===day));
    const heading=node('h3',labelDate(day.date));
    mobile.replaceChildren(heading,...(day.lessons.length?day.lessons.map(item=>lessonCard(node,item)):[node('p','Занятий нет.','muted')]));
  }
  const choices=layout.days.map(day=>{
    const button=node('button',new Date(day.date+'T12:00:00').toLocaleDateString(locale(),{weekday:'short',day:'numeric',month:'numeric'}));
    button.type='button';button.addEventListener('click',()=>showDay(day));picker.append(button);
    return {day,button};
  });
  if(choices.length)showDay(choices.find(({day})=>day.date===selected)?.day||choices[0].day);
  const ruler=node('div','','week-ruler');ruler.setAttribute('aria-hidden','true');
  ruler.append(node('div','МСК','week-heading'));
  const scale=node('div','','week-track');
  scale.style.height=(layout.end-layout.start)+'px';
  for(let minute=layout.start;minute<layout.end;minute+=60){
    const tick=node('span',clock(minute),'week-tick');tick.style.top=(minute-layout.start)+'px';scale.append(tick);
  }
  ruler.append(scale);grid.append(ruler);
  for(const day of layout.days){
    const column=node('section','','week-column'),heading=node('h3',labelDate(day.date),'week-heading');
    if(day.date===data.today)heading.classList.add('week-today');
    const track=node('div','','week-track');track.style.height=(layout.end-layout.start)+'px';
    if(!day.events.length)track.append(node('p','Нет занятий','week-empty'));
    for(const {lesson,top,height,lane} of day.events){
      const status=lesson.placement==='moved_from'?'Перенесено':lesson.status==='cancelled'?'Отменено':lesson.changes.length?'Изменено':'';
      const button=node('button','','week-event');button.type='button';
      if(status)button.classList.add(lesson.status==='cancelled'?'week-cancelled':'week-changed');
      const time=`${clock(lesson.start_minute)}–${clock(lesson.end_minute)}`;
      button.setAttribute('aria-label',`${labelDate(day.date)}, ${time}, ${lesson.subject}${status?', '+t(status):''}`);
      button.append(node('small',time+(status?' · '+t(status):'')),node('strong',lesson.subject));
      Object.assign(button.style,{top:top+'px',height:height+'px',left:(lane/day.laneCount*100)+'%',width:(100/day.laneCount)+'%'});
      button.addEventListener('click',()=>{
        const close=node('button','Закрыть детали');close.type='button';
        close.addEventListener('click',()=>{details.hidden=true;details.replaceChildren();button.focus();});
        details.replaceChildren(node('h3',labelDate(day.date)),lessonCard(node,lesson),close);
        details.hidden=false;details.focus();
      });
      track.append(button);
    }
    column.append(heading,track);grid.append(column);
  }
}
export function renderSchedule(document,root,data) {
  root.replaceChildren();
  const node=(tag,text,className='')=>{const e=document.createElement(tag);e.textContent=t(text);if(className)e.className=className;return e;};
  if(data.view==='week'){renderWeek(root,data,node);return;}
  for(const day of data.days) {
    const section=node('section','','schedule-day');section.append(node('h3',labelDate(day.date)));
    if(!day.lessons.length)section.append(node('p','Занятий нет.','muted'));
    for(const lesson of day.lessons) {
      section.append(lessonCard(node,lesson));
    }
    root.append(section);
  }
}
export function mountSchedule(document) {
  const get=id=>document.getElementById(id),root=get('schedule-section');
  const controller=createScheduleState({request:requestJson,publish(value) {
    get('schedule-days').replaceChildren();get('schedule-days').setAttribute('data-view',value.view||'today');root.hidden=value.state==='hidden';
    if(value.state==='hidden')return;
    get('schedule-date').value=value.selected;
    get('schedule-today').setAttribute('aria-pressed',String(value.view==='today'));
    get('schedule-week').setAttribute('aria-pressed',String(value.view==='week'));
    get('schedule-status').textContent=value.state==='loading'?t('Загружаем расписание…'):value.state==='error'?t(value.message):`${t('Группа')} ${value.data.group.name} · ${t('время МСК','Moscow time')}`;
    if(value.state==='ready')renderSchedule(document,get('schedule-days'),value.data);
  }});
  get('schedule-today').addEventListener('click',()=>controller.setView('today'));
  get('schedule-week').addEventListener('click',()=>controller.setView('week'));
  get('schedule-date').addEventListener('change',event=>{try{controller.setDate(event.target.value);}catch{get('schedule-status').textContent=t('Укажите существующую дату.');}});
  get('schedule-prev').addEventListener('click',()=>controller.move(-1));
  get('schedule-next').addEventListener('click',()=>controller.move(1));
  get('schedule-now').addEventListener('click',()=>controller.today());
  get('schedule-retry').addEventListener('click',()=>controller.retry());
  return controller;
}
let mounted=null;
export function scheduleIdentity(user) {mounted??=mountSchedule(document);if(user)return mounted.setUser(user);mounted.clear();}
