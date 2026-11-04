import {requestJson} from './api.js';
import {createAcademicsState} from './academics-state.js';
const controls={exam:'Экзамен',credit:'Зачёт',graded_credit:'Дифференцированный зачёт'};
const statuses={passed:'Успешно завершено',failed:'Неудовлетворительный результат',absent:'Неявка',overdue:'Истёк срок сдачи',upcoming:'Предстоит',ungraded:'Оценка не внесена',not_held:'Испытание не проведено',unscheduled:'Дата / проведение не подтверждены',cancelled:'Отменено'};
function resultText(attempt){return attempt.outcome==='graded'?`Оценка: ${attempt.grade}`:({pass:'Зачтено',fail:'Не зачтено',absent:'Неявка'}[attempt.outcome] || 'Нет оценки');}
export function renderAcademics(document,root,data){
  root.replaceChildren();
  const node=(tag,text,className='')=>{const e=document.createElement(tag);e.textContent=text;if(className)e.className=className;return e;};
  const block=title=>{const section=node('section','','academic-block');section.append(node('h3',title));root.append(section);return section;};
  function card(item){
    const e=node('article','','lesson-card');e.append(node('h4',item.subject),node('p',controls[item.control] || item.control));
    e.append(node('p',statuses[item.status] || item.status,item.status==='passed'?'lesson-time':'change-badge'));
    e.append(node('p',item.scheduled_on?`Дата: ${item.scheduled_on} · МСК`:'Дата не назначена','muted'));
    if(item.deadline_on)e.append(node('p',`Срок сдачи: ${item.deadline_on}`,'muted'));
    if(!item.required)e.append(node('p','Необязательное испытание','muted'));
    if(!item.attempts.length)e.append(node('p','Результат отсутствует','muted'));
    for(const attempt of item.attempts)e.append(node('p',`Попытка ${attempt.number} · ${resultText(attempt)} · сдано ${attempt.performed_on} · внесено ${new Date(attempt.recorded_at*1000).toLocaleDateString('ru-RU',{timeZone:'Europe/Moscow'})}`,'change-detail'));
    return e;
  }
  const progress=block('Прогресс текущей сессии'),p=data.progress;
  if(p.state==='no_data')progress.append(node('p','Нет данных о текущей сессии.'));
  else {
    progress.append(node('p',data.current_semester.name),node('p',`${p.percent}% · завершено ${p.completed} из ${p.total}`,'academic-percent'));
    const meter=node('progress','');meter.max=100;meter.value=p.percent;meter.setAttribute('aria-label','Процент закрытия сессии');progress.append(meter);
    progress.append(node('p',`Всего обязательных: ${p.total} · Завершено: ${p.completed} · Предстоит: ${p.upcoming} · Задолженности: ${p.debts} · Ожидают уточнения: ${p.pending}`));
  }
  progress.append(node('p','Экзамен и дифференцированный зачёт: 3–5; зачёт: «Зачтено». Пересдачи не увеличивают число испытаний.','muted'));
  const upcoming=block('Предстоящие экзамены и зачёты');
  if(!data.upcoming.length)upcoming.append(node('p','Нет назначенных предстоящих испытаний.','muted'));
  for(const item of data.upcoming)upcoming.append(card(item));
  const debts=block('Академические задолженности');
  debts.append(node('p','Неуспешная попытка / неявка либо завершённое испытание с истёкшим подтверждённым сроком. Будущая дата и отсутствие оценки сами по себе не означают долг.','muted'));
  if(!data.debts.length)debts.append(node('p','Подтверждённых задолженностей нет.','muted'));
  for(const item of data.debts)debts.append(card(item));
  const book=block('Электронная зачётка');
  if(!data.semesters.length)book.append(node('p','Нет данных об успеваемости.','muted'));
  for(const semester of data.semesters){
    const details=node('details',''),summary=node('summary',`${semester.name} · ${semester.starts_on} — ${semester.ends_on}`);
    details.open=true;details.append(summary);for(const item of semester.items)details.append(card(item));book.append(details);
  }
}
export function mountAcademics(document){
  const get=id=>document.getElementById(id),root=get('academics-section');
  const controller=createAcademicsState({request:requestJson,publish(value){
    get('academics-content').replaceChildren();root.hidden=value.state==='hidden';
    get('academics-status').textContent=value.state==='loading'?'Загружаем успеваемость…':value.state==='error'?value.message:'';
    if(value.state==='ready')renderAcademics(document,get('academics-content'),value.data);
  }});
  get('academics-retry').addEventListener('click',()=>controller.retry());return controller;
}
let mounted=null;
export function academicsIdentity(user){mounted??=mountAcademics(document);if(user)return mounted.setUser(user);mounted.clear();}
