import {requestJson} from './api.js';
import {locale,t} from './language.js';
import {createDeadlines} from './deadlines-state.js';

export function mountDeadlines(document,request=requestJson){
  const root=document.getElementById('deadlines-section'),content=document.getElementById('deadlines-content');
  const status=document.getElementById('deadlines-status');
  let user=null,active=false,onExpired=()=>{};
  let pendingTarget=null,observer=null;
  function reveal(){
    if(!pendingTarget)return;
    const card=pendingTarget.page==='academics'
      ?document.querySelector('#academics-content [data-deadline-target="'+CSS.escape(pendingTarget.id)+'"]')
      :document.getElementById('deadline-attestations-'+pendingTarget.id);
    if(card&&!card.closest('.screen-off')){
      if(card.tagName==='DETAILS')card.open=true;
      card.tabIndex=-1;card.focus();card.scrollIntoView({block:'start'});
      observer?.disconnect();pendingTarget=null;
    }
  }
  const node=(tag,text)=>{const e=document.createElement(tag);e.textContent=text;return e;};
  const controller=createDeadlines({request,expired:()=>onExpired(),publish(value){
    content.replaceChildren();root.hidden=value.state==='hidden';
    status.textContent=value.state==='loading'?t('Загружаем сроки…','Loading dates…'):
      value.state==='error'?t('Не удалось обновить сроки. Проверьте вход и повторите запрос.','Could not refresh dates. Check your session and retry.') : '';
    if(value.state!=='ready')return;
    if(!value.items.length)content.append(node('p',t('Ближайших учебных сроков нет.','No upcoming academic dates.')));
    const labels={overdue:t('Просрочено','Overdue'),soon:t('В ближайшие 3 дня','Within 3 days'),upcoming:t('Предстоит','Upcoming')};
    for(const item of value.items){
      const card=node('article','');card.className='lesson-card';card.dataset.urgency=item.urgency;
      card.append(node('h3',item.subject),node('p',item.kind==='submission'?item.title:t(item.title)),node('p',labels[item.urgency]));
      const states={assigned:'Ожидает сдачи',returned:'На доработку',retry_allowed:'Повторная сдача разрешена',
        scheduled:'Назначено',failed:'Неудовлетворительный результат',absent:'Неявка',upcoming:'Предстоит',
        overdue:'Истёк срок сдачи',ungraded:'Оценка не внесена',not_held:'Испытание не проведено',unscheduled:'Дата / проведение не подтверждены'};
      card.append(node('p',t(states[item.state]||item.state)));
      const date=item.precision==='time'?new Date(item.at*1000).toLocaleString(locale(),{
        timeZone:'Europe/Moscow',dateStyle:'long',timeStyle:'short'})+' · '+t('МСК'):
        new Date(item.date+'T12:00:00+03:00').toLocaleDateString(locale(),{timeZone:'Europe/Moscow',dateStyle:'long'})+
        ' · '+t('Время не указано','Time not specified');
      card.append(node('p',date));
      if(item.kind==='assessment')card.append(node('p',t('Дата испытания','Assessment date')));
      if(item.kind==='submission')card.append(node('p',t('Срок сдачи работы','Assignment deadline')));
      const button=node('button',t('Открыть событие','Open event'));button.type='button';
      button.addEventListener('click',()=>{
        observer?.disconnect();
        pendingTarget=item.page==='coursework'?null:{page:item.page,id:item.target};
        if(pendingTarget){observer=new MutationObserver(reveal);observer.observe(document.getElementById(item.page==='academics'?'academics-content':'attestations-content'),{childList:true,subtree:true});}
        document.dispatchEvent(new CustomEvent('mgimov:deadline-open',{detail:{page:item.page,id:item.target}}));
        location.hash='#'+item.page;
      });card.append(button);content.append(card);
    }
  }});
  document.getElementById('deadlines-refresh').addEventListener('click',()=>{if(active&&user)controller.load(user);});
  document.addEventListener('mgimov:page',event=>{
    reveal();
    active=event.detail==='deadlines';if(active&&user)controller.load(user);else controller.clear();
  });
  return {identity(value,expired){onExpired=expired;user=value.state==='ready'?value.user:null;
    if(!user){observer?.disconnect();pendingTarget=null;}
    if(user&&active)controller.load(user);else controller.clear();}};
}
let mounted;
export function deadlinesIdentity(value,expired){mounted??=mountDeadlines(document);mounted.identity(value,expired);}
