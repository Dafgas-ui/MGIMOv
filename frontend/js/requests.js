import {requestJson} from './api.js';
import {createRequestsState} from './requests-state.js';
import {createRequestOperations} from './request-operation.js';
export const requestTypes={study_certificate:'Справка об обучении',general_certificate:'Справка по месту требования',appeal:'Свободное обращение'};
const statuses={submitted:'Отправлено',processing:'В обработке',approved:'Одобрено',rejected:'Отклонено',cancelled:'Отменено студентом'};
const actions={processing:'Взять в обработку',approved:'Одобрить',rejected:'Отклонить',cancel:'Отменить заявку'};
const date=seconds=>new Date(seconds*1000).toLocaleString('ru-RU',{timeZone:'Europe/Moscow'});

export function renderRequests(document,root,value,controller){
  root.replaceChildren();
  const node=(tag,text,className='')=>{const e=document.createElement(tag);e.textContent=text;if(className)e.className=className;return e;};
  const button=(label,callback)=>{const b=node('button',label);b.type='button';b.addEventListener('click',callback);return b;};
  if(!value.items.length)root.append(node('p',value.role==='staff'?'В доступной очереди обращений нет.':'Ваших обращений пока нет.','muted'));
  for(const item of value.items){
    const card=node('article','','lesson-card');card.append(node('h3',requestTypes[item.type]),node('p',statuses[item.status],'change-badge'),node('p',`${date(item.created_at)} · МСК · № ${item.id.slice(0,8)}`,'muted'));
    card.append(button('Открыть обращение '+item.id.slice(0,8),()=>controller.open(item.id)));root.append(card);
  }
  const pages=node('div','','schedule-toolbar');
  if(value.offset>0)pages.append(button('Предыдущие обращения',()=>controller.page(Math.max(0,value.offset-20))));
  if(value.next_offset!==null)pages.append(button('Следующие обращения',()=>controller.page(value.next_offset)));
  root.append(pages);
  const item=value.detail;if(!item)return;
  const detail=node('section','','request-detail');detail.setAttribute('aria-label','Детали обращения');
  detail.append(node('h3','Детали: '+requestTypes[item.type]),node('p',`№ ${item.id} · версия ${item.version}`,'muted'),node('p',statuses[item.status],'change-badge'));
  if(item.student)detail.append(node('p',`${item.student.full_name} · ${item.student.study_group}`));
  if(item.purpose)detail.append(node('p','Назначение: '+item.purpose));
  detail.append(node('p',item.message,'request-text'),node('h4','История обработки'));
  const history=node('ol','','request-history');
  for(const event of item.history){
    const li=node('li','');li.append(node('p',`${date(event.created_at)} · МСК · ${statuses[event.to_status]}`,'change-badge'),node('p',`${event.actor_role==='staff'?'Сотрудник':'Студент'}: ${event.actor_name || 'Автор действия'}`,'muted'),node('p',event.comment,'request-text'));history.append(li);
  }
  detail.append(history);
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
  root.append(detail);
}

export function mountRequests(document){
  const get=id=>document.getElementById(id),root=get('requests-section'),form=get('request-create-form'),fields=get('request-fields');
  function purpose(){const enabled=get('request-type').value!=='appeal';get('request-purpose-field').hidden=!enabled;get('request-purpose').required=enabled;if(!enabled)get('request-purpose').value='';}
  const controller=createRequestsState({request:requestJson,operations:createRequestOperations(),readCsrf(){
    const name=location.protocol==='https:'?'__Host-mgimov_csrf':'mgimov_csrf';
    return document.cookie.split(';').map(x=>x.trim()).find(x=>x.startsWith(name+'='))?.slice(name.length+1) || '';
  },publish(value){
    get('requests-content').replaceChildren();root.hidden=['hidden','suspended'].includes(value.state);
    if(value.state==='suspended'){fields.disabled=true;return;}
    if(value.state==='hidden'){form.reset();form.hidden=true;return;}
    get('request-recovery').hidden=!value.recovery;
    get('request-recovery-text').textContent=value.recovery?.lost?'Не удалось восстановить прежнюю отправку. Сначала проверьте список обращений.':value.recovery?`Осталась неподтверждённая отправка: ${requestTypes[value.recovery.type]}. Проверьте список или повторите те же поля. Изменённый текст проверит сервер.`:'';
    get('requests-title').textContent=value.role==='staff'?'Очередь обращений деканата':'Мои обращения';
    get('request-new').hidden=value.role!=='student';if(value.role==='staff')form.hidden=true;
    fields.disabled=value.state==='loading';get('request-new').disabled=value.state==='loading';get('requests-retry').disabled=value.state==='loading';
    get('requests-status').textContent=value.state==='loading'?'Загружаем обращения…':value.state==='error'?value.message:value.role==='staff'?'Только обращения факультетов, к которым вам предоставлен доступ.':'Справки и ответы в этом прототипе не являются официальными документами.';
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
  get('requests-retry').addEventListener('click',()=>controller.retry());return controller;
}
let mounted=null;
export function requestsIdentity(user,{suspend=false,discardOperation=false}={}){mounted??=mountRequests(document);if(user)return mounted.setUser(user);if(suspend)mounted.suspend();else mounted.clear({discardOperation});}
