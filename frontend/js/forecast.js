import {requestJson} from './api.js';
import {t} from './language.js';
import {createForecast} from './forecast-state.js';
import {emphasizeProgress} from './progress.js';
import {renderCalculator} from './brs-calculator.js';

const reasons={
  no_active_enrollment:['Нет действующего зачисления. Прежние баллы сохранены в истории.','No active enrollment. Previous scores remain in history.'],
  plan_not_ready:['Нет утверждённого плана 20/20/20/40.','No approved 20/20/20/40 plan.'],
  policy_not_ready:['Правила аттестации ещё не утверждены.','Assessment policy is not approved yet.'],
  transfer_reconciliation:['После смены плана требуется сверка результатов.','Results need reconciliation after a plan change.'],
  inconsistent_credit_scale:['Шкала зачёта требует проверки.','The pass/fail scale needs review.'],
  examiner_decides:['Экзаменационную оценку выставляет преподаватель. БРС определяет только условия допуска.','The examiner sets the exam grade. BRS determines admission conditions only.'],
  no_published_results:['Нет опубликованных баллов. Прогноз не рассчитан.','No published scores. A forecast cannot be calculated.'],
  unpublished_events:['Есть мероприятия без опубликованного результата. Прогноз итоговой оценки пока недоступен.','Some events have no published result. A final grade forecast is not available yet.']
};
export function renderForecast(document,root,items,previous=new Map()){
  root.replaceChildren();const node=(tag,text)=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;return e;};
  if(!items.length)root.append(node('p',t('Нет дисциплин с планом БРС.','No BRS courses.')));
  for(const item of items){
    const card=node('article');card.className='lesson-card';card.dataset.courseId=item.id;
    card.append(node('h4',item.subject),node('p',item.semester),node('p',t(
      {exam:'Экзамен',credit:'Зачёт',graded_credit:'Дифференцированный зачёт'}[item.control])));
    if(!item.available){card.append(node('p',t(...reasons[item.reason])));root.append(card);continue;}
    const score=item.published_points;
    card.append(node('p',score==null?t('Опубликованных баллов нет','No published scores'):
      t(`Опубликовано: ${score} из ${item.plan_maximum}`,`Published: ${score} of ${item.plan_maximum}`)));
    if(score!=null){
      const meter=node('progress');meter.max=item.plan_maximum;meter.value=score;
      meter.setAttribute('aria-label',t('Опубликованные баллы БРС','Published BRS scores'));
      card.append(meter);if(previous.get(item.id)!==score)emphasizeProgress(meter);previous.set(item.id,score);
    }
    if(item.control==='exam')card.append(node('p',item.admission==null?t('Допуск: недостаточно опубликованных данных.','Admission: insufficient published data.'):
      item.admission?t('Условия допуска по БРС выполнены.','BRS admission conditions are met.'):
      t('Условия допуска по БРС пока не выполнены.','BRS admission conditions are not yet met.')),
      node('p',t(`Порог допуска: ${item.admission_minimum}. Также учитываются обязательные мероприятия и минимумы категорий.`,
        `Admission threshold: ${item.admission_minimum}. Required events and category minima also apply.`)));
    if(item.predicted_result!=null){
      const value=item.predicted_result==='pass'?t('Зачтено','Pass'):item.predicted_result==='fail'?t('Не зачтено','Fail'):String(item.predicted_result);
      card.append(node('p',t(`Предварительный результат по опубликованным баллам: ${value}`,`Provisional result from published scores: ${value}`)));
    }else card.append(node('p',t(...reasons[item.result_reason])));
    if(item.control==='credit')card.append(node('p',t('Зачёт: от 50 — зачтено; ниже 50 — не зачтено.',
      'Pass/fail assessment: 50 or more is a pass; below 50 is a fail.')));
    if(item.control==='graded_credit')card.append(node('p',t('Утверждённая шкала: ','Approved scale: ')+
      item.scale.map(s=>`${s.minimum} → ${s.outcome}`).join('; ')));
    if(item.required_shortfalls?.length)card.append(node('p',t(
      'Обязательные условия плана ещё не выполнены. Предварительный результат не разрешает подтверждение итога.',
      'Required plan conditions are not yet met. A provisional result does not authorize confirmation.')));
    card.append(node('p',t('Это не официальная оценка и не запись зачётки.','This is not an official grade or a gradebook entry.')),
      node('p',t('Максимум плана — 100. Достижимый итог не рассчитан: будущие результаты и пересдачи неизвестны.',
        'The plan maximum is 100. An attainable total is not calculated: future results and retakes are unknown.')));
    const list=node('ul');
    for(const event of item.events){
      const policy={highest:t('лучший опубликованный результат','highest published result'),
        latest:t('последняя опубликованная попытка','latest published attempt'),none:t('без пересдач','no retakes')};
      const unmet=item.required_shortfalls?.includes(event.code);
      list.append(node('li',`${event.title}: ${event.points==null?t('не опубликовано','not published'):event.points} / ${event.maximum}`+
        (event.retake_policy?' · '+policy[event.retake_policy]:'')+
        (unmet?' · '+t('обязательное условие не выполнено','required condition not met'):'')));
    }
    card.append(list);
    renderCalculator(document,card,item);
    root.append(card);
  }
}
export function mountForecast(document,request=requestJson){
  const panel=document.getElementById('forecast-panel'),root=document.getElementById('forecast-content'),status=document.getElementById('forecast-status');
  let onExpired=()=>{};const previous=new Map();
  const controller=createForecast({request,expired:()=>onExpired(),publish(value){
    panel.hidden=value.state==='hidden';root.replaceChildren();
    status.textContent=value.state==='loading'?t('Загружаем прогноз…','Loading forecast…'):value.state==='error'?
      t('Не удалось загрузить прогноз. Обновите данные.','Could not load the forecast. Refresh the data.') : '';
    if(value.state==='ready')renderForecast(document,root,value.data.items,previous);
  }});
  document.getElementById('forecast-refresh').addEventListener('click',controller.load);
  document.addEventListener?.('mgimov:language',controller.load);
  return {identity(value,expired){onExpired=expired;previous.clear();return controller.setUser(value.state==='ready'?value.user:null);}};
}
let mounted;
export function forecastIdentity(value,expired){mounted??=mountForecast(document);return mounted.identity(value,expired);}
