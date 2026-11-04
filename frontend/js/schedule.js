import {requestJson} from './api.js';
import {createScheduleState} from './schedule-state.js';
const kinds={lecture:'Лекция',seminar:'Семинар',practice:'Практика',lab:'Лабораторная'};
const names={date:'дата',start_minute:'время начала',end_minute:'время окончания',room_id:'аудитория',teacher_id:'преподаватель',status:'статус'};
export function clock(minutes) {return `${String(Math.floor(minutes/60)).padStart(2,'0')}:${String(minutes%60).padStart(2,'0')}`;}
function labelDate(day) {return new Date(day+'T12:00:00').toLocaleDateString('ru-RU',{weekday:'long',day:'numeric',month:'long'});}
export function renderSchedule(document,root,data) {
  root.replaceChildren();
  const node=(tag,text,className='')=>{const e=document.createElement(tag);e.textContent=text;if(className)e.className=className;return e;};
  for(const day of data.days) {
    const section=node('section','','schedule-day');section.append(node('h3',labelDate(day.date)));
    if(!day.lessons.length)section.append(node('p','Занятий нет.','muted'));
    for(const lesson of day.lessons) {
      const card=node('article','','lesson-card');
      if(lesson.status!=='scheduled')card.classList.add('lesson-inactive');
      card.append(node('p',`${clock(lesson.start_minute)}–${clock(lesson.end_minute)} · ${kinds[lesson.kind] || lesson.kind}`,'lesson-time'),node('h4',lesson.subject));
      card.append(node('p',lesson.teacher),node('p',`${lesson.building} · ауд. ${lesson.room}`));
      if(lesson.placement==='moved_from')card.append(node('p',`Перенесено на ${labelDate(lesson.actual.date)}, ${clock(lesson.actual.start_minute)}–${clock(lesson.actual.end_minute)}`,'change-badge'));
      else if(lesson.status==='cancelled')card.append(node('p','Занятие отменено','change-badge'));
      else if(lesson.changes.length)card.append(node('p','Расписание изменено','change-badge'));
      for(const change of lesson.changes) {
        card.append(node('p',`${change.reason} · изменено: ${change.fields.map(key=>names[key] || key).join(', ')}`,'change-detail'));
        const before=change.before,after=change.after;
        const show=item=>`${item.date} ${clock(item.start_minute)}–${clock(item.end_minute)}, ${item.building}, ауд. ${item.room}, ${item.teacher}${item.status==='cancelled'?' (отменено)':''}`;
        card.append(node('p',`Было: ${show(before)}`,'change-detail'),node('p',`Стало: ${show(after)}`,'change-detail'));
      }
      section.append(card);
    }
    root.append(section);
  }
}
export function mountSchedule(document) {
  const get=id=>document.getElementById(id),root=get('schedule-section');
  const controller=createScheduleState({request:requestJson,publish(value) {
    get('schedule-days').replaceChildren();root.hidden=value.state==='hidden';
    if(value.state==='hidden')return;
    get('schedule-date').value=value.selected;
    get('schedule-today').setAttribute('aria-pressed',String(value.view==='today'));
    get('schedule-week').setAttribute('aria-pressed',String(value.view==='week'));
    get('schedule-status').textContent=value.state==='loading'?'Загружаем расписание…':value.state==='error'?value.message:`Группа ${value.data.group.name} · время МСК`;
    if(value.state==='ready')renderSchedule(document,get('schedule-days'),value.data);
  }});
  get('schedule-today').addEventListener('click',()=>controller.setView('today'));
  get('schedule-week').addEventListener('click',()=>controller.setView('week'));
  get('schedule-date').addEventListener('change',event=>{try{controller.setDate(event.target.value);}catch{get('schedule-status').textContent='Укажите существующую дату.';}});
  get('schedule-prev').addEventListener('click',()=>controller.move(-1));
  get('schedule-next').addEventListener('click',()=>controller.move(1));
  get('schedule-now').addEventListener('click',()=>controller.today());
  get('schedule-retry').addEventListener('click',()=>controller.retry());
  return controller;
}
let mounted=null;
export function scheduleIdentity(user) {mounted??=mountSchedule(document);if(user)return mounted.setUser(user);mounted.clear();}
