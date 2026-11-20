import {requestJson} from './api.js';
import {locale,t} from './language.js';

export const attendanceLabels={unmarked:'Не отмечено',present:'Присутствовал',absent:'Отсутствовал',late:'Опоздал'};
export function attendanceMessage(error) {
  return ({401:'Сессия завершена. Войдите снова.',403:'Недостаточно прав.',404:'Ведомость недоступна.',
    409:'Занятие, состав или отметка изменились. Обновите данные и проверьте состав.',
    422:'Проверьте поля и укажите причину.',503:'База временно недоступна.'})[error.status]||'Не удалось загрузить посещаемость.';
}

export function mountAttendance(document, request=requestJson) {
  const dialog=document.getElementById('attendance-dialog'),content=document.getElementById('attendance-content');
  const status=document.getElementById('attendance-status'),entry=document.getElementById('attendance-open');
  let user=null,csrf,expired,epoch=0,abort,busy=false,selected=null;
  let lastLesson=null;
  let lastData=null,owner=null;
  const drafts=new Map();
  const node=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=t(text);return e;};
  const button=(parent,text,action)=>{const b=node('button',text);b.type='button';b.addEventListener('click',action);parent.append(b);return b;};
  function clear(discard=false){
    epoch++;abort?.abort();content.replaceChildren();status.textContent='';busy=false;
    if(discard){drafts.clear();lastLesson=null;lastData=null;}
    selected=null;dialog.close();
  }
  const draftKey=(id,action,student='')=>JSON.stringify([id,action,student]);
  function history(parent,events){
    const list=node('details');list.append(node('summary','История посещаемости'));
    for(const event of events){
      const p=event.payload;
      const rosterLabel=Array.isArray(p.students)?`${t('Состав подтверждён')} · ${p.students.length}`:
        t(p.included?'Включение в состав подтверждено':'Исключение из актуального состава подтверждено');
      const change=['mark','qr_mark'].includes(event.kind)?`${t(attendanceLabels[p.previous])} → ${t(attendanceLabels[p.status])}${event.kind==='qr_mark'?' · QR':''}`:
        `${rosterLabel} · ${p.date}`;
      list.append(node('p',`№ ${event.version} · ${change} · ${event.actor_id} · ${new Date(event.created_at*1000).toLocaleString(locale(),{timeZone:'Europe/Moscow'})} · ${event.reason}`));
    }
    parent.append(list);
  }
  function own(parent,item){
    parent.append(node('p',attendanceLabels[item.status]));
    if(item.cancelled)parent.append(node('p','Занятие отменено. Отметка исключена из актуальной посещаемости.'));
    else if(!item.active)parent.append(node('p',item.needs_confirmation?'Требуется проверка состава ведомости.':
      'Вы больше не входите в актуальный состав. История сохранена.'));
    history(parent,item.history);
  }
  function form(parent,title,key,data,submit){
    const f=node('form');f.className='coursework-form';f.append(node('h3',title));
    const draft=drafts.get(key)||{lesson:data.lesson.id,reason:'',expected_version:data.version,
      lesson_version:data.lesson.version};
    const label=node('label','Причина'),reason=node('input');reason.required=true;reason.maxLength=300;label.append(reason);f.append(label);
    reason.value=draft.reason;
    const remember=()=>{draft.reason=reason.value;drafts.set(key,draft);};
    f.addEventListener('input',remember);f.addEventListener('change',remember);
    const b=node('button','Сохранить');b.type='submit';f.append(b);
    const blocked=draft.conflict||draft.expected_version!==data.version||draft.lesson_version!==data.lesson.version;
    b.disabled=!!blocked;
    if(blocked){
      f.append(node('p','Черновик сохранён. Обновите данные, сравните значения и подтвердите применение к новой версии.'));
      const adopt=button(f,'Применить черновик к обновлённой версии',()=>{
        if(!draft.refreshed)return;
        draft.expected_version=data.version;draft.lesson_version=data.lesson.version;draft.conflict=false;
        drafts.set(key,draft);render(data);
      });
      adopt.disabled=!draft.refreshed;
      button(f,'Отменить черновик',()=>{drafts.delete(key);render(data);});
    }
    f.addEventListener('submit',event=>{event.preventDefault();remember();if(!busy&&!blocked)submit(reason.value,key);});
    parent.append(f);return {form:f,draft,remember};
  }
  function render(data){
    lastData=data;
    content.replaceChildren();
    if(!data.items)button(content,'К списку занятий',()=>load());
    if(user.role==='student'){
      if(data.items){
        if(!data.items.length)content.append(node('p','Подтверждённых ведомостей пока нет.'));
        for(const item of data.items){const card=node('article');card.className='lesson-card';
          card.append(node('h3',`${item.date} · ${item.subject}`));own(card,item);content.append(card);}
      }else own(content,data);
      return;
    }
    if(data.items){
      if(!data.items.length)content.append(node('p','Назначенных занятий нет.'));
      for(const lesson of data.items){const card=node('article');card.className='lesson-card';
        card.append(node('h3',`${lesson.date} · ${lesson.subject} · ${lesson.study_group} · ${lesson.teacher}`));
        button(card,'Журнал занятия',()=>load(lesson.id));content.append(card);}
      return;
    }
    const {lesson}=data;
    content.append(node('h3',`${lesson.date} · ${lesson.subject}`));
    if(lesson.status==='cancelled')content.append(node('p','Занятие отменено. Ведомость доступна только для чтения.'));
    if(data.blocked_reason)content.append(node('p',data.blocked_reason));
    if(data.can_mark)button(content,t('QR-посещаемость','QR attendance'),()=>{
      dialog.close();document.dispatchEvent(new CustomEvent('mgimov:attendance-qr-open',{detail:data}));
    });
    if(data.needs_confirmation&&data.candidate&&lesson.status==='scheduled'){
      content.append(node('p','Проверьте датированный состав перед подтверждением.'));
      for(const row of data.candidate.students)content.append(node('p',row.full_name));
      if(!data.candidate.students.length)content.append(node('p','Состав пуст. Это не означает отсутствие студентов на занятии.'));
      form(content,'Подтвердить состав',draftKey(lesson.id,'confirm'),data,
        (reason,key)=>save(data,{action:'confirm',candidate_token:data.candidate_token,reason},key));
    }
    if(!data.students.length)content.append(node('p','В подтверждённом составе нет студентов. Отметки отсутствия не создаются.'));
    for(const row of data.students){
      const card=node('article');card.className='lesson-card';card.append(node('h4',row.full_name),node('p',attendanceLabels[row.status]));
      if(data.can_mark){
        let choice;
        const {form:f,draft,remember}=form(card,'Отметка посещаемости',draftKey(lesson.id,'mark',row.id),data,
          (reason,key)=>save(data,{action:'mark',student_id:row.id,status:choice.value,reason},key));
        const label=node('label','Статус'),select=node('select');
        for(const [value,text] of Object.entries(attendanceLabels)){const option=node('option',text);option.value=value;select.append(option);}
        select.value=draft.status??row.status;choice=select;label.append(select);f.prepend(label);
        select.addEventListener('change',()=>{draft.status=select.value;remember();});
      }content.append(card);
    }
    history(content,data.history);
  }
  async function load(id=null,body,key){
    if(!user)return;
    if(body&&busy)return;
    const current=++epoch;abort?.abort();abort=new AbortController();busy=!!body;selected=id;
    if(id)lastLesson=id;
    status.textContent=t('Загружаем посещаемость…');if(!body)content.replaceChildren();
    const role=user.role==='staff'?'staff':'me';
    const path=`/api/v1/${role}/attendance`+(id?`/lessons/${encodeURIComponent(id)}`:role==='staff'?'/lessons':'');
    try{
      const data=await request(path,{signal:abort.signal,...(body?{method:'POST',body,
        headers:{'X-CSRF-Token':csrf(),'X-MGIMOv-User':user.id}}:{headers:{'X-MGIMOv-User':user.id}})});
      if(current!==epoch||!user)return;
      if(body){
        const draft=drafts.get(key);
        if(draft?.reason===body.reason && (body.action!=='mark'||(draft.status??body.status)===body.status))drafts.delete(key);
      }
      for(const draft of drafts.values())if(draft.lesson===id)draft.refreshed=true;
      render(data);status.textContent=body?t('Изменение сохранено.') : '';
    }catch(error){
      if(current!==epoch)return;
      if(!body||[403,404].includes(error.status))content.replaceChildren();status.textContent=t(attendanceMessage(error));
      if(error.status===401){clear(true);expired?.();}
      else {
        if(error.status===409){
          for(const draft of drafts.values())if(draft.lesson===id){draft.conflict=true;draft.refreshed=false;}
          // Disable stale writes immediately while retaining the visible form values.
          if(body&&lastData?.lesson?.id===id)render(lastData);
        }
        button(content,'Обновить',()=>load(selected));
      }
    }finally{if(current===epoch)busy=false;}
  }
  const save=(data,body,key)=>load(data.lesson.id,{...body,expected_version:data.version,lesson_version:data.lesson.version},key);
  entry.addEventListener('click',()=>{dialog.showModal();load(lastLesson);});
  document.addEventListener('click',event=>{const b=event.target.closest?.('[data-attendance]');if(!b||!user)return;
    dialog.showModal();load(b.dataset.attendance);});
  document.getElementById('attendance-close').addEventListener('click',()=>clear());
  dialog.addEventListener('cancel',event=>{event.preventDefault();clear();});
  return {identity(value,readCsrf,onExpired){
    const next=value.state==='ready'?value.user:null;
    const transient=value.state==='suspended'||(value.state==='loading'&&value.operation==='refresh')||
      (value.state==='error'&&!value.identityInvalidated);
    if(!next){clear(!transient);if(!transient)owner=null;}
    else if(owner!==next.id+':'+next.role){clear(true);owner=next.id+':'+next.role;}
    user=next;csrf=readCsrf;expired=onExpired;entry.hidden=!next;
  }};
}

let mounted;
export function attendanceIdentity(value,csrf,expired){mounted??=mountAttendance(document);mounted.identity(value,csrf,expired);}
