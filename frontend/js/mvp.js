import {t} from './language.js';
import {shellRefresh,navigate} from './ui-shell.js';
import {currentLessons} from './ui-state.js';
import {requestJson} from './api.js';
import {emphasizeProgress} from './progress.js';
import {createWorkspace} from './mvp-state.js';
const get=id=>document.getElementById(id);
const statusLabel={submitted:'Отправлено',processing:'В обработке',approved:'Одобрено',rejected:'Отклонено',cancelled:'Отменено'};
const root=get('mvp-section'),content=get('mvp-content'),status=get('mvp-status');
let owner='',scope='',staffForms=null,pending=false;
let staffGroup='',selectedDocument=null,documentGeneration=0;
const downloadUrls=new Set();
const element=(tag,text,className)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=t(text);if(className)node.className=className;return node;};
function button(text,action){const node=element('button',text);node.type='button';node.addEventListener('click',action);return node;}
function item(title,body){const node=element('article',undefined,'mvp-item');node.append(element('h3',title));if(body)node.append(element('p',body));return node;}
function csrf(){const name=location.protocol==='https:'?'__Host-mgimov_csrf':'mgimov_csrf';return document.cookie.split(';').map(x=>x.trim()).find(x=>x.startsWith(name+'='))?.slice(name.length+1)||'';}
function clearDocument(forget=false){documentGeneration++;if(forget)selectedDocument=null;for(const url of downloadUrls)URL.revokeObjectURL(url);downloadUrls.clear();get('mvp-document').replaceChildren();}
function reset(){staffGroup='';lessonForm=null;owner='';scope='';staffForms=null;content.replaceChildren();clearDocument(true);}
const workspace=createWorkspace({request:requestJson,csrf,publish(value){
  root.hidden=value.state!=='ready'&&value.state!=='error';
  // A confirmed account change clears the old drafts even if its subsequent data load fails.
  if(value.user&&owner&&owner!==value.user.id+':'+value.user.role)reset();
  if(value.state==='anonymous'){reset();if(typeof shellRefresh==='function')shellRefresh();return;}
  if(value.state==='suspended'||value.state==='loading'){clearDocument();if(typeof shellRefresh==='function')shellRefresh();return;}
  if(value.state==='error'){content.hidden=true;status.textContent=t(value.message);if(typeof shellRefresh==='function')shellRefresh();return;}
  const next=value.user.id+':'+value.user.role;
  const signature=JSON.stringify(value.data.catalogue?.groups||[]);
  if(owner!==next||scope!==signature)reset();
  owner=next;scope=signature;content.hidden=false;status.textContent=t('Данные обновлены.');
  render(value.user,value.data);if(typeof shellRefresh==='function')shellRefresh();
  if(selectedDocument){if(value.data.documents.items.some(doc=>doc.id===selectedDocument))showDocument(selectedDocument,{focus:false});else clearDocument(true);}
}});
get('mvp-refresh').addEventListener('click',()=>workspace.refresh());
export function mvpIdentity(user,options){return workspace.identity(user,options);}

async function act(path,body,success='Изменения сохранены.'){
  if(pending)return false;
  pending=true;root.querySelectorAll('button,fieldset').forEach(x=>x.disabled=true);
  status.textContent=t('Сохраняем…');
  try {await workspace.action(path,body);await workspace.refresh();status.textContent=t(success);return true;}
  catch(error){status.textContent=t(error.status===409?'Данные уже изменились или действие недоступно. Обновите кабинет, проверьте результат и повторите вручную.':error.status===422?'Проверьте обязательные поля, дату и время.':error.status===403||error.status===401?'Проверьте вход и полномочия.':'Не удалось подтвердить результат. Обновите данные перед повтором.');return false;}
  finally {pending=false;root.querySelectorAll('button,fieldset').forEach(x=>x.disabled=false);}
}
function field(form,label,name,type='text',options=null){
  const id='mvp-field-'+name;const labelNode=element('label',label);labelNode.htmlFor=id;
  const input=element(options?'select':type==='textarea'?'textarea':'input');input.id=id;input.name=name;input.required=true;
  if(!options&&type!=='textarea')input.type=type;
  if(options)for(const option of options){const node=element('option',option.label);node.value=option.value;input.append(node);}
  if(type==='textarea'){input.rows=3;input.maxLength=1000;}
  form.append(labelNode,input);return input;
}
function section(title,id){const node=element('section');if(id)node.id=id;node.append(element('h3',title));return node;}
function render(user,data){
  const fragment=document.createDocumentFragment();
  const summary=section('Главная','dashboard-section');
  const jump=(label,href)=>{const link=element('a',label);link.href=href;return link;};
  if(user.role==='student'){
    const context=currentLessons(data.schedule),hero=element('article',undefined,'mvp-hero');
    const layout=element('div',undefined,'daybook-layout'),main=element('div',undefined,'daybook-main'),aside=element('aside',undefined,'daybook-side');
    aside.setAttribute('aria-label','Прогресс и важные действия');
    const lesson=context.active[0]||context.next;
    const body=element('div');body.append(element('p',context.active.length?'Сейчас · по времени устройства, МСК':context.live?(context.next?'Следующее занятие сегодня':'Учебный день · МСК'):t('Расписание на ','Timetable for ')+context.date,'hero-status'));
    body.append(element('h2',lesson?.subject||(context.live?'Сегодня занятий больше нет':'На выбранную дату занятий нет')));
    if(lesson){body.append(element('p',`${lesson.teacher} · ${lesson.building} · ${t('ауд.','room')} ${lesson.room}`));hero.append(body,element('p',`${time(lesson.start_minute)}–${time(lesson.end_minute)} · ${t('МСК')}`,'hero-time'));}
    else hero.append(body);
    const link=jump('Открыть расписание','#schedule');link.className='daybook-primary';body.append(link);main.append(hero);
    if(context.active.length>1)main.append(element('p','В расписании несколько одновременных занятий. Проверьте полный список.','notice'));
    if(context.active.length&&context.next){
      const next=context.next,block=element('article',undefined,'daybook-next'),copy=element('div');
      copy.append(element('p','Дальше сегодня','eyebrow'),element('h3',next.subject),element('p',`${next.building} · ${t('ауд.','room')} ${next.room}`,'muted'));
      block.append(copy,element('p',`${time(next.start_minute)}–${time(next.end_minute)}`,'lesson-time'));main.append(block);
    }
    const today=section(context.live?'Расписание на сегодня':'Расписание на день'),list=element('ol',undefined,'daybook-timeline');
    const lessons=data.schedule.days.find(day=>day.date===data.schedule.selected_date)?.lessons||[];
    for(const event of lessons){
      const row=element('li'),text=element('div');
      const status=event.placement==='moved_from'?'Перенесено':event.status==='cancelled'?'Отменено':context.active.includes(event)?'Сейчас':'';
      row.append(element('span',`${time(event.start_minute)}–${time(event.end_minute)}`,'lesson-time'));
      text.append(element('strong',event.subject),element('p',`${event.building} · ${t('ауд.','room')} ${event.room}`,'muted'));
      if(status)text.append(element('p',status,status==='Сейчас'?'hero-status':'change-badge'));
      if(context.active.includes(event))row.classList.add('daybook-current');
      row.append(text);list.append(row);
    }
    today.append(element('p',`${data.schedule.group.name} · ${t('МСК')}`,'muted'));
    today.append(lessons.length?list:element('p','Занятий нет. Можно посмотреть неделю.','muted'));
    today.append(jump('Всё расписание','#schedule'));main.append(today);

    const attention=section('Требует внимания');
    let hasAttention=false;
    const changed=lessons.find(event=>event.changes?.length);
    if(changed){const card=item('Изменение расписания',`${changed.subject} · ${changed.changes.at(-1).reason}`);card.append(jump('Посмотреть изменения','#schedule'));attention.append(card);hasAttention=true;}
    const pending=data.requests.items.filter(x=>['submitted','processing'].includes(x.status)).length;
    if(pending){const card=item('Обращения в работе',t('На загруженной странице: ','On this page: ')+pending);card.append(jump('Открыть обращения','#requests'));attention.append(card);hasAttention=true;}
    if(data.documents.items.length){const card=item('Демонстрационные справки',t('Доступно: ','Available: ')+data.documents.items.length);card.append(jump('Перейти к документам','#documents'));attention.append(card);hasAttention=true;}
    if(!hasAttention)attention.append(element('p','Действий, требующих внимания, пока нет.','muted'));
    const notices=item('Уведомления',t('Непрочитанных: ','Unread: ')+data.notifications.unread);
    notices.append(jump('Открыть уведомления','#notifications'));
    const {completed,total}=data.progress.progress,study=item('Учебный прогресс');
    if(total>0){
      const number=element('p',undefined,'daybook-progress-number');number.append(element('strong',String(completed)),element('span',t(` из ${total} испытаний завершено`,` of ${total} assessments complete`)));
      const meter=element('progress',undefined,'daybook-progress');meter.max=total;meter.value=completed;meter.setAttribute('aria-label',t('Завершённые обязательные испытания'));study.append(number,meter);emphasizeProgress(meter);
    }else study.append(element('p','В зачётке пока нет обязательных испытаний.','muted'));
    study.append(jump('Открыть зачётку','#academics'));
    aside.append(study,attention,notices);layout.append(main,aside);summary.append(layout);
  }
  fragment.append(summary);
  const notices=section('Уведомления','notifications-section');
  if(!data.notifications.items.length)notices.append(element('p','Уведомлений пока нет.'));
  for(const notice of data.notifications.items){const card=item(notice.title,notice.body);if(!notice.read_at){card.classList.add('mvp-unread');card.append(button('Отметить прочитанным',()=>act('/api/v1/me/notifications/'+notice.id+'/read')));}else card.append(element('p','Прочитано','muted'));if(notice.kind==='document'&&data.documents.items.some(doc=>doc.id===notice.resource_id))card.append(button('Открыть документ',()=>{if(typeof navigate==='function')navigate('documents');showDocument(notice.resource_id);}));else if(notice.kind==='request'&&notice.resource_id)card.append(button('Открыть обращение',()=>openRequest(notice.resource_id)));else if(notice.kind==='lesson'){const link=element('a','Открыть расписание');link.href='#schedule-section';card.append(link);}else if(notice.title==='Изменение аттестации'&&user.role==='student')card.append(jump(t('Аттестации'),'#attestations'));notices.append(card);}
  const notificationPages=element('div',undefined,'schedule-toolbar');
  if(data.notifications.has_previous)notificationPages.append(button('Новые уведомления',()=>workspace.previousNotifications()));
  if(data.notifications.next_cursor)notificationPages.append(button('Старые уведомления',()=>workspace.nextNotifications()));
  notices.append(notificationPages);
  fragment.append(notices);
  const documents=section('Документы','documents-section');
  if(user.role==='student')documents.append(button('Запросить справку',()=>{if(typeof navigate==='function')navigate('requests');document.dispatchEvent(new CustomEvent('mgimov:new-request'));}));documents.append(element('p','Все справки демонстрационные. Подпись не является юридически значимой электронной подписью.','notice'));
  if(!data.documents.items.length)documents.append(element('p','Готовых справок пока нет. Создайте заявку в разделе обращений.'));
  for(const doc of data.documents.items){const card=item(t('Справка ','Certificate ')+doc.id.slice(0,8),doc.delivered_at?'Передана студенту':'Подписана, ещё не передана');
    card.append(button('Открыть справку',()=>showDocument(doc.id)));
    if(user.role==='staff'&&!doc.delivered_at)card.append(button('Передать студенту',()=>act('/api/v1/staff/documents/'+doc.id+'/deliver')));
    if(doc.request_id)card.append(button('Исходное обращение',()=>openRequest(doc.request_id)));
    documents.append(card);}
  fragment.append(documents);
  if(user.role==='staff'){
    const staff=section('Кабинет сотрудника','staff-section');
    staff.append(element('p','Доступ ограничен факультетами, назначенными на сервере. Список занятий показывает последние 200 записей.'));
    const students=section('Студенты разрешённых факультетов','staff-students-section');students.dataset.staffPart='students';
    students.append(element('p','Показаны до 200 доступных студентов. Уведомление отправляется выбранному студенту через backend.','muted'));
    const roster=element('div',undefined,'mvp-cards');for(const student of data.students.items)roster.append(item(student.full_name,student.study_group));students.append(roster);staff.append(students);
    if(!staffForms)staffForms=buildStaffForms(data);staff.append(staffForms);
    const lessons=section('Загруженные занятия');lessons.dataset.staffPart='schedule';
    const filter=element('select');filter.id='staff-group-filter';filter.append(Object.assign(element('option','Все загруженные группы'),{value:''}));
    for(const group of data.catalogue.groups)filter.append(Object.assign(element('option',group.name),{value:group.id}));filter.value=staffGroup;
    const label=element('label','Фильтр групп среди загруженных занятий (до 200)');label.htmlFor=filter.id;lessons.append(label,filter);
    const cards=[];
    for(const lesson of data.lessons.items){
      const card=item(`${lesson.date} · ${time(lesson.start_minute)} · ${lesson.subject}`,
        `${lesson.building}, ${lesson.room} · ${lesson.teacher} · ${t(lesson.status==='cancelled'?'Отменено':'Запланировано')}`);
      card.append(button('Изменить занятие',()=>editLesson(lesson)));
      const attendance=element('button','Журнал занятия');
      attendance.type='button';attendance.dataset.attendance=lesson.id;card.append(attendance);
      card.hidden=!!staffGroup&&lesson.group_id!==staffGroup;
      cards.push([card,lesson.group_id]);lessons.append(card);
    }
    if(!cards.length)lessons.append(element('p','Загруженных занятий нет. Можно создать новое занятие.'));
    filter.addEventListener('change',()=>{staffGroup=filter.value;for(const [card,group] of cards)card.hidden=!!staffGroup&&group!==staffGroup;});staff.append(lessons);fragment.append(staff);
  }
  content.replaceChildren(fragment);
}
const time=minutes=>`${String(Math.floor(minutes/60)).padStart(2,'0')}:${String(minutes%60).padStart(2,'0')}`;
const minutes=value=>{const [hour,minute]=value.split(':').map(Number);return hour*60+minute;};
let lessonForm=null;
function buildStaffForms(data){
  const container=element('div');lessonForm=element('form',undefined,'mvp-form');const form=lessonForm;form.dataset.staffPart='schedule';form.append(element('h4','Создать или изменить занятие'));
  const fields=element('fieldset');form.append(fields);
  const group=field(fields,'Учебная группа','group_id','text',data.catalogue.groups.map(x=>({value:x.id,label:x.name})));
  const subject=field(fields,'Дисциплина','subject_id','text',data.catalogue.subjects.map(x=>({value:x.id,label:x.name})));
  field(fields,'Преподаватель','teacher_id','text',data.catalogue.teachers.map(x=>({value:x.id,label:x.full_name})));
  field(fields,'Корпус и аудитория','room_id','text',data.catalogue.rooms.map(x=>({value:x.id,label:x.building+' · '+x.number})));
  field(fields,'Дата','date','date');field(fields,'Начало','start','time');field(fields,'Окончание','end','time');
  const kind=field(fields,'Тип занятия','kind','text',[['lecture','Лекция'],['seminar','Семинар'],['practice','Практика'],['lab','Лабораторная']].map(([value,label])=>({value,label})));
  field(fields,'Состояние','status','text',[{value:'scheduled',label:'Запланировано'},{value:'cancelled',label:'Отменено'}]);
  const reason=field(fields,'Причина / описание','reason');reason.maxLength=300;
  const save=element('button','Предпросмотр изменения');save.type='submit';fields.append(save);
  const preview=element('div');preview.id='lesson-preview';let proposal=null;
  const invalidate=()=>{proposal=null;preview.replaceChildren();};form.addEventListener('input',invalidate);form.addEventListener('change',invalidate);
  const clear=button('Новое занятие',()=>{form.reset();delete form.dataset.id;delete form.dataset.version;delete form.dataset.before;group.disabled=subject.disabled=kind.disabled=false;invalidate();});form.append(clear,preview);
  form.addEventListener('submit',event=>{event.preventDefault();if(pending)return;const value=new FormData(form);const body={date:value.get('date'),start_minute:minutes(value.get('start')),end_minute:minutes(value.get('end')),teacher_id:value.get('teacher_id'),room_id:value.get('room_id'),status:value.get('status'),reason:value.get('reason')};
    const id=form.dataset.id;
    if(id)body.version=Number(form.dataset.version);else Object.assign(body,{group_id:value.get('group_id'),subject_id:value.get('subject_id'),kind:value.get('kind')});
    if(body.start_minute>=body.end_minute){status.textContent=t('Окончание должно быть позже начала.');return;}
    proposal={id,body,owner};preview.replaceChildren();preview.append(element('h4','Предпросмотр: подтверждение на сервере ещё не выполнено'));
    if(form.dataset.before)preview.append(element('p',t('Было: ','Before: ')+form.dataset.before));
    preview.append(element('p',`${t('Стало: ','After: ')}${body.date}, ${value.get('start')}–${value.get('end')} · ${form.elements.room_id.selectedOptions[0]?.textContent} · ${form.elements.teacher_id.selectedOptions[0]?.textContent} · ${t(body.status==='cancelled'?'Отменено':'Запланировано')}`));
    preview.append(element('p',t('Причина: ','Reason: ')+body.reason),element('p','Группа будет уведомлена автоматически в той же операции.','notice'));
    preview.append(button('Подтвердить изменение',async()=>{const current=proposal;if(!current||current.owner!==owner||pending)return;
      if(await act('/api/v1/staff/lessons'+(current.id?'/'+current.id:''),current.body,'Изменение сохранено. Группа уведомлена автоматически.')){form.reset();delete form.dataset.id;delete form.dataset.version;delete form.dataset.before;group.disabled=subject.disabled=kind.disabled=false;invalidate();}
    }),button('Вернуться к редактированию',invalidate));
  });container.append(form);
  const notify=element('form',undefined,'mvp-form');notify.dataset.staffPart='students';notify.append(element('h4','Отправить уведомление студенту'));
  field(notify,'Студент','student_id','text',data.students.items.map(x=>({value:x.id,label:x.full_name+' · '+x.study_group})));
  const title=field(notify,'Заголовок','title');title.maxLength=160;field(notify,'Сообщение','body','textarea');const send=element('button','Отправить уведомление');send.type='submit';notify.append(send);
  notify.addEventListener('submit',async e=>{e.preventDefault();if(await act('/api/v1/staff/notifications',Object.fromEntries(new FormData(notify))))notify.reset();});container.append(notify);return container;
}
function openRequest(id){if(typeof navigate==='function')navigate('requests');document.dispatchEvent(new CustomEvent('mgimov:open-request',{detail:{id}}));}
function editLesson(lesson){
  const form=lessonForm;get('lesson-preview').replaceChildren();form.dataset.before=`${lesson.date}, ${time(lesson.start_minute)}–${time(lesson.end_minute)} · ${lesson.building}, ${lesson.room} · ${lesson.teacher}`;form.dataset.id=lesson.id;form.dataset.version=String(lesson.version);
  for(const key of ['group_id','subject_id','teacher_id','room_id','kind','date','status'])form.elements[key].value=lesson[key];
  form.elements.start.value=time(lesson.start_minute);form.elements.end.value=time(lesson.end_minute);form.elements.reason.value='';
  for(const key of ['group_id','subject_id','kind'])form.elements[key].disabled=true;
  form.scrollIntoView({block:'start'});form.elements.reason.focus();
}
async function showDocument(id,{focus=true}={}){
  clearDocument();selectedDocument=id;const generation=documentGeneration,target=get('mvp-document');
  try {
    const doc=await workspace.document(id);if(generation!==documentGeneration||selectedDocument!==id)return;
    const pre=element('pre',doc.content,'mvp-document');
    target.append(pre,button('Скачать текст справки',()=>{
      if(generation!==documentGeneration||selectedDocument!==id)return;
      try {
        const url=URL.createObjectURL(new Blob([doc.content],{type:'text/plain;charset=utf-8'}));downloadUrls.add(url);
        const a=element('a');a.href=url;a.download='mgimov-demo-'+id+'.txt';document.body.append(a);a.click();a.remove();
        setTimeout(()=>{URL.revokeObjectURL(url);downloadUrls.delete(url);},1000);
      }catch {status.textContent=t('Не удалось начать скачивание. Попробуйте открыть справку снова.');}
    }),button('Закрыть справку',()=>clearDocument(true)));
    if(focus){target.tabIndex=-1;target.focus({preventScroll:true});target.scrollIntoView({block:'start'});}
  }catch {if(generation===documentGeneration)status.textContent=t('Документ недоступен. Проверьте вход и обновите данные.');}
}

const registration=get('registration-form');
registration.addEventListener('submit',async event=>{
  event.preventDefault();const fields=registration.querySelector('fieldset'),message=get('registration-status');
  const data=Object.fromEntries(new FormData(registration));fields.disabled=true;message.textContent=t('Регистрируем…');
  try {const bootstrap=await requestJson('/api/v1/auth/csrf');await requestJson('/api/v1/auth/register',{method:'POST',body:data,headers:{'X-CSRF-Token':bootstrap.csrf}});registration.reset();message.textContent=t('Аккаунт создан. Войдите с выбранным логином и паролем.');}
  catch(error){message.textContent=t(error.status===409?'Выйдите из аккаунта или выберите другой логин.':error.status===429?'Слишком много попыток. Повторите позже.':'Регистрация не завершена. Проверьте приглашение, поля и пароль от 15 символов.');}
  finally {registration.elements.password.value='';registration.elements.invitation.value='';fields.disabled=false;}
});

document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden'){registration.elements.password.value='';registration.elements.invitation.value='';}});

document.addEventListener('mgimov:requests-changed',()=>workspace.refresh());
