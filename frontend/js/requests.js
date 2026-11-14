import {t,locale} from './language.js';
import {requestJson} from './api.js';
import {shellRequests} from './ui-shell.js';
import {createRequestsState} from './requests-state.js';
import {createRequestOperations} from './request-operation.js';
export const requestTypes={study_certificate:'Справка об обучении',general_certificate:'Справка по месту требования',appeal:'Свободное обращение'};
const statuses={submitted:'Отправлено',processing:'В обработке',approved:'Одобрено',rejected:'Отклонено',cancelled:'Отменено студентом'};
const actions={processing:'Взять в обработку',approved:'Одобрить',rejected:'Отклонить',cancel:'Отменить заявку'};
const date=seconds=>new Date(seconds*1000).toLocaleString(locale(),{timeZone:'Europe/Moscow'});

export function renderRequests(document,root,value,controller){
  root.replaceChildren();
  const node=(tag,text,className='')=>{const e=document.createElement(tag);e.textContent=t(text);if(className)e.className=className;return e;};
  const button=(label,callback)=>{const b=node('button',label);b.type='button';b.addEventListener('click',callback);return b;};
  const layout=node('div','','requests-layout'),list=node('div','','queue-list');layout.setAttribute('data-selected',String(!!value.detail));layout.append(list);root.append(layout);
  const entries=[];let filter=null;
  if(value.role==='staff'){
    const label=node('label','Фильтр текущей страницы: тип, номер или текст');label.htmlFor='request-page-filter';filter=node('input','');filter.id='request-page-filter';filter.type='search';filter.maxLength=200;filter.value=controller.getFilter?.()||'';list.append(label,filter,node('p','Фильтр действует только на загруженную страницу. Полный журнал Staff и серверный поиск всей очереди не входят в этот MVP.','muted'));
  }
  if(!value.items.length)list.append(node('p',value.role==='staff'?'В доступной очереди обращений нет.':'Ваших обращений пока нет.','muted'));
  for(const item of value.items){
    const card=node('article','','lesson-card');card.append(node('h3',requestTypes[item.type]),node('p',statuses[item.status],'change-badge'),node('p',`${date(item.created_at)} · МСК · № ${item.id.slice(0,8)}`,'muted'));
    card.append(button(t('Открыть обращение')+' '+item.id.slice(0,8),()=>controller.open(item.id)));list.append(card);entries.push([card,`${t(requestTypes[item.type])} ${item.id} ${item.message}`.toLocaleLowerCase(locale())]);
  }
  const pages=node('div','','schedule-toolbar');
  if(value.offset>0)pages.append(button('Предыдущие обращения',()=>controller.page(Math.max(0,value.offset-20))));
  if(value.next_offset!==null)pages.append(button('Следующие обращения',()=>controller.page(value.next_offset)));
  list.append(pages);
  if(filter){const empty=node('p','На этой странице совпадений нет. Проверьте фильтр или следующую страницу.','muted');list.append(empty);const apply=()=>{const query=filter.value.trim().toLocaleLowerCase('ru');for(const [card,text] of entries)card.hidden=!!query&&!text.includes(query);empty.hidden=!entries.length||entries.some(([card])=>!card.hidden);};filter.addEventListener('input',()=>{controller.setFilter?.(filter.value);apply();});apply();}
  const item=value.detail;if(!item)return;
  const detail=node('section','','request-detail');detail.setAttribute('aria-label',t('Детали обращения'));
  if(controller.close)detail.append(button('Вернуться к списку',()=>controller.close()));
  detail.append(node('h3',t('Детали: ','Details: ')+t(requestTypes[item.type])),node('p',`№ ${item.id} · ${t('версия','version')} ${item.version}`,'muted'),node('p',statuses[item.status],'change-badge'));
  if(item.student)detail.append(node('p',`${item.student.full_name} · ${item.student.study_group}`));
  if(item.purpose)detail.append(node('p',t('Назначение: ','Purpose: ')+item.purpose));
  detail.append(node('p',item.message,'request-text'),node('h4','История обработки'));
  const history=node('ol','','request-history');
  for(const event of item.history){
    const li=node('li','');li.append(node('p',`${date(event.created_at)} · ${t('МСК')} · ${t(statuses[event.to_status])}`,'change-badge'),node('p',`${t(event.actor_role==='staff'?'Сотрудник':'Студент')}: ${event.actor_name || t('Автор действия')}`,'muted'),node('p',event.comment,'request-text'));history.append(li);
  }
  detail.append(history);
  const canReply=value.role==='staff'&&['submitted','processing'].includes(item.status);
  const retainedReply=value.role==='staff'&&!canReply?controller.getReplyDraft?.(item.id):'';
  if(canReply&&controller.reply){
    const form=node('form',''),label=node('label','Ответ студенту');label.htmlFor='request-reply-comment';const input=node('textarea','');input.id='request-reply-comment';input.required=true;input.maxLength=1000;input.rows=3;input.value=controller.getReplyDraft(item.id);input.addEventListener('input',()=>controller.setReplyDraft(item.id,input.value));
    const submit=node('button','Отправить ответ');submit.type='submit';form.append(label,input,submit);form.addEventListener('submit',event=>{event.preventDefault();controller.reply(input.value);});detail.append(form);
  }else if(retainedReply){
    const label=node('label','Неотправленный ответ — обращение завершено');label.htmlFor='request-retained-reply';
    const draft=node('textarea','');draft.id='request-retained-reply';draft.value=retainedReply;draft.readOnly=true;draft.rows=3;
    detail.append(label,draft,node('p','Выделите текст и скопируйте его при необходимости.','muted'));
  }
  if(value.role==='staff' && item.status==='approved' && item.type!=='appeal'){
    detail.append(node('p','Справка и подпись демонстрационные, не являются юридически значимой электронной подписью.','notice'));
    if(!item.document)detail.append(button('Подписать демонстрационную справку',()=>controller.certificate('sign')));
    else if(!item.document.delivered_at)detail.append(button('Передать справку студенту',()=>controller.certificate('deliver')));
    else detail.append(node('p','Демонстрационная справка передана студенту.','change-badge'));
  }
  if(value.role==='student' && item.actions.includes('cancel'))detail.append(button(actions.cancel,()=>controller.change('cancel','Отменено студентом.')));
  if(value.role==='staff' && item.actions.length){
    const form=node('form',''),label=node('label','Действие сотрудника');label.htmlFor='request-action';
    const select=node('select','');select.id='request-action';
    for(const action of item.actions){const option=node('option',actions[action]);option.value=action;select.append(option);}
    const commentLabel=node('label','Комментарий / причина решения');commentLabel.htmlFor='request-decision-comment';
    const comment=node('textarea','');comment.id='request-decision-comment';comment.required=true;comment.maxLength=1000;comment.rows=3;
    comment.value=controller.getDraft?.(item.id) || '';
    comment.addEventListener('input',()=>controller.setDraft(item.id,comment.value));
    const submit=node('button','Применить действие');submit.type='submit';form.append(label,select,commentLabel,comment,submit);
    form.addEventListener('submit',event=>{event.preventDefault();controller.change(select.value,comment.value);});detail.append(form);
  }else if(value.role==='staff' && controller.getDraft?.(item.id)){
    const label=node('label','Несохранённый комментарий — действие уже недоступно');label.htmlFor='request-retained-comment';
    const draft=node('textarea','');draft.id='request-retained-comment';draft.value=controller.getDraft(item.id);draft.readOnly=true;detail.append(label,draft);
  }
  layout.append(detail);
}

export function mountRequests(document){
  const get=id=>document.getElementById(id),root=get('requests-section'),form=get('request-create-form'),fields=get('request-fields');
  let currentRole=null;
  function purpose(){const enabled=get('request-type').value!=='appeal';get('request-purpose-field').hidden=!enabled;get('request-purpose').required=enabled;if(!enabled)get('request-purpose').value='';}
  const controller=createRequestsState({request:requestJson,operations:createRequestOperations(),onMutation(){if(document.dispatchEvent&&typeof CustomEvent==='function')document.dispatchEvent(new CustomEvent('mgimov:requests-changed'));},readCsrf(){
    const name=location.protocol==='https:'?'__Host-mgimov_csrf':'mgimov_csrf';
    return document.cookie.split(';').map(x=>x.trim()).find(x=>x.startsWith(name+'='))?.slice(name.length+1) || '';
  },publish(value){
    currentRole=value.state==='ready'?value.role:null;
    if(typeof shellRequests==='function')shellRequests(value);
    get('requests-content').replaceChildren();root.hidden=['hidden','suspended'].includes(value.state);
    if(value.state==='suspended'){fields.disabled=true;return;}
    if(value.state==='hidden'){form.reset();form.hidden=true;return;}
    get('request-recovery').hidden=!value.recovery;
    get('request-recovery-text').textContent=value.recovery?.lost?t('Не удалось восстановить прежнюю отправку. Сначала проверьте список обращений.'):value.recovery?t(`Осталась неподтверждённая отправка: ${requestTypes[value.recovery.type]}. Проверьте список или повторите те же поля. Изменённый текст проверит сервер.`,
      `Unconfirmed submission: ${t(requestTypes[value.recovery.type])}. Check the list or retry with the same fields.`):'';
    get('requests-title').textContent=t(value.role==='staff'?'Очередь обращений деканата':'Мои обращения');
    get('request-new').hidden=value.role!=='student';if(value.role==='staff')form.hidden=true;
    fields.disabled=value.state==='loading';get('request-new').disabled=value.state==='loading';get('requests-retry').disabled=value.state==='loading';
    get('requests-status').textContent=t(value.state==='loading'?'Загружаем обращения…':value.state==='error'?value.message:value.role==='staff'?'Только обращения факультетов, к которым вам предоставлен доступ.':'Справки и ответы в этом прототипе не являются официальными документами.');
    if(value.state==='ready')renderRequests(document,get('requests-content'),value,controller);
  }});
  get('request-new').addEventListener('click',()=>{form.hidden=!form.hidden;purpose();if(!form.hidden)get('request-type').focus();});
  get('request-type').addEventListener('change',purpose);
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(controller.isBusy())return;
    const ok=await controller.create({type:get('request-type').value,purpose:get('request-purpose').value,message:get('request-message').value});
    if(ok){form.reset();form.hidden=true;}
  });
  get('request-new-operation').addEventListener('click',()=>{if(controller.newOperation()){form.reset();form.hidden=false;purpose();controller.retry();}});
  get('requests-retry').addEventListener('click',()=>controller.retry());
  document.addEventListener?.('mgimov:new-request',()=>{if(currentRole==='student'){form.hidden=false;purpose();get('request-type').focus();}});
  document.addEventListener?.('mgimov:open-request',event=>{const id=event.detail?.id;if(typeof id==='string'&&/^[a-f0-9-]{1,100}$/.test(id))controller.open(id);});return controller;
}
let mounted=null;
export function requestsIdentity(user,{suspend=false,discardOperation=false}={}){mounted??=mountRequests(document);if(user)return mounted.setUser(user);if(suspend)mounted.suspend();else mounted.clear({discardOperation});}
