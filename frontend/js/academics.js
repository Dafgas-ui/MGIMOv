import {requestJson} from './api.js';
import {createAcademicsState} from './academics-state.js';
import {locale,t} from './language.js';
const controls={exam:'Экзамен',credit:'Зачёт',graded_credit:'Дифференцированный зачёт'};
const statuses={passed:'Успешно завершено',failed:'Неудовлетворительный результат',absent:'Неявка',overdue:'Истёк срок сдачи',upcoming:'Предстоит',ungraded:'Оценка не внесена',not_held:'Испытание не проведено',not_admitted:'Не допущен',unscheduled:'Дата / проведение не подтверждены',cancelled:'Отменено'};
function resultText(attempt){return attempt.outcome==='graded'?t(`Оценка: ${attempt.grade}`,`Grade: ${attempt.grade}`):t({pass:'Зачтено',fail:'Не зачтено',absent:'Неявка'}[attempt.outcome] || 'Нет оценки');}
export function renderAcademics(document,root,data){
  root.replaceChildren();
  const node=(tag,text,className='')=>{const e=document.createElement(tag);e.textContent=text;if(className)e.className=className;return e;};
  const block=title=>{const section=node('section','','academic-block');section.append(node('h3',t(title)));root.append(section);return section;};
  function card(item){
    const e=node('article','','lesson-card');e.append(node('h4',item.subject),node('p',t(controls[item.control] || item.control)));
    e.append(node('p',t(statuses[item.status] || item.status),item.status==='passed'?'lesson-time':'change-badge'));
    e.append(node('p',item.scheduled_on?t(`Дата: ${item.scheduled_on} · МСК`,`Date: ${item.scheduled_on} · MSK`):t('Дата не назначена'),'muted'));
    if(item.deadline_on)e.append(node('p',t(`Срок сдачи: ${item.deadline_on}`,`Deadline: ${item.deadline_on}`),'muted'));
    if(!item.required)e.append(node('p',t('Необязательное испытание'),'muted'));
    if(!item.attempts.length)e.append(node('p',t('Результат отсутствует'),'muted'));
    for(const attempt of item.attempts){
      const recorded=new Date(attempt.recorded_at*1000).toLocaleDateString(locale(),{timeZone:'Europe/Moscow'});
      const corrected=attempt.corrected?t(' · исправлено',' · corrected'):'';
      e.append(node('p',t(`Попытка ${attempt.number} · ${resultText(attempt)} · сдано ${attempt.performed_on} · внесено ${recorded}`,
        `Attempt ${attempt.number} · ${resultText(attempt)} · taken ${attempt.performed_on} · recorded ${recorded}`)+corrected,'change-detail'));
    }
    if(item.awaiting_deanery)e.append(node('p',t('Ожидается решение деканата.','Awaiting a dean’s office decision.'),'muted'));
    return e;
  }
  const progress=block('Прогресс текущей сессии'),p=data.progress;
  if(p.state==='no_data')progress.append(node('p',t('Нет данных о текущей сессии.')));
  else {
    progress.append(node('p',data.current_semester.name),node('p',t(`${p.percent}% · завершено ${p.completed} из ${p.total}`,`${p.percent}% · ${p.completed} of ${p.total} complete`),'academic-percent'));
    const meter=node('progress','');meter.max=100;meter.value=p.percent;meter.setAttribute('aria-label',t('Процент закрытия сессии','Term completion percentage'));progress.append(meter);
    progress.append(node('p',t(`Всего обязательных: ${p.total} · Завершено: ${p.completed} · Предстоит: ${p.upcoming} · Задолженности: ${p.debts} · Ожидают уточнения: ${p.pending}`,
      `Required: ${p.total} · Complete: ${p.completed} · Upcoming: ${p.upcoming} · Outstanding: ${p.debts} · Pending: ${p.pending}`)));
  }
  progress.append(node('p',t('Экзамен и дифференцированный зачёт: 3–5; зачёт: «Зачтено». Пересдачи не увеличивают число испытаний.',
    'Grades 3–5 and a pass count as complete. Retakes do not increase the number of assessments.'),'muted'));
  const upcoming=block('Предстоящие экзамены и зачёты');
  if(!data.upcoming.length)upcoming.append(node('p',t('Нет назначенных предстоящих испытаний.'),'muted'));
  for(const item of data.upcoming)upcoming.append(card(item));
  const debts=block('Академические задолженности');
  debts.append(node('p',t('Список подтверждённых академических задолженностей.',
    'This list shows confirmed outstanding assessments.'),'muted'));
  if(!data.debts.length)debts.append(node('p',t('Подтверждённых задолженностей нет.'),'muted'));
  for(const item of data.debts)debts.append(card(item));
  const book=block('Электронная зачётка');
  if(!data.semesters.length)book.append(node('p',t('Нет данных об успеваемости.'),'muted'));
  for(const semester of data.semesters){
    const details=node('details',''),summary=node('summary',`${semester.name} · ${semester.starts_on} — ${semester.ends_on}`);
    details.open=true;details.append(summary);for(const item of semester.items)details.append(card(item));book.append(details);
  }
}
export function mountAcademics(document){
  const get=id=>document.getElementById(id),root=get('academics-section');
  const controller=createAcademicsState({request:requestJson,publish(value){
    get('academics-content').replaceChildren();root.hidden=value.state==='hidden';
    get('academics-status').textContent=t(value.state==='loading'?'Загружаем успеваемость…':value.state==='error'?value.message:'');
    if(value.state==='ready')renderAcademics(document,get('academics-content'),value.data);
  }});
  get('academics-retry').addEventListener('click',()=>controller.retry());return controller;
}
let mounted=null;
export function academicsIdentity(user){mounted??=mountAcademics(document);if(user)return mounted.setUser(user);mounted.clear();}
