import {createCourseworkClient, courseworkError, filterWorks, unicodeLength} from './coursework-client.js';
import {locale,t} from './language.js';

const states={draft:['Черновик','Draft'],published:['Опубликовано','Published'],
  submitted:['Ожидает проверки','Awaiting review'],reviewed:['Проверено','Reviewed'],
  returned:['На доработку','Returned'],retry_allowed:['Повторная сдача разрешена','Resubmission allowed']};
const grading={ungraded:['Без баллов','Ungraded'],independent:['Независимые баллы','Independent score'],brs:['Связано с БРС','Linked to BRS']};
const modes={both:['Текстовая и очная','Text and in person'],online:['Текстовая','Text'],in_person:['Очная','In person']};
const kinds={lab:['Лабораторная','Lab'],test:['Контрольная','Test'],practice:['Практическая','Practice'],other:['Другая','Other']};
const label=(map,key)=>Object.hasOwn(map,key)?t(...map[key]):'';
const options=map=>Object.entries(map).map(([key,value])=>[key,t(...value)]);
const date=seconds=>new Date(seconds*1000).toLocaleString(locale(),{timeZone:'Europe/Moscow',dateStyle:'short',timeStyle:'short'})+' '+t('МСК','MSK');
const path=value=>'/'+encodeURIComponent(value);

export function mountCoursework(document, makeClient=createCourseworkClient) {
  const get=id=>document.getElementById(id);
  const root=get('coursework-section'), content=get('coursework-content');
  const status=get('coursework-status'), refresh=get('coursework-refresh');
  let client, owner, ready=false, active=false, sending=false, blocked=false;
  let view, selection, recipient, creating=false, read, epoch=0, draft;
  let sessionEpoch=0, onSessionExpired;
  let filters={semester:'',subject:''};
  const node=(tag,text,css)=>{
    const element=document.createElement(tag);
    if(text!==undefined)element.textContent=text;
    if(css)element.className=css;
    return element;
  };
  const say=(message,state='')=>{status.textContent=message;status.dataset.state=state;};
  const line=(parent,text,css)=>parent.append(node('p',text,css));
  function button(parent,text,action) {
    const control=node('button',text);control.type='button';
    control.addEventListener('click',action);parent.append(control);
  }
  function field(parent,name,title,{type='text',value='',choices,required=true}={}) {
    const wrapper=node('label',title), input=node(choices?'select':type==='textarea'?'textarea':'input');
    input.name=name;
    if(choices)for(const [key,text] of choices){
      const option=node('option',text);option.value=key;input.append(option);
    }
    else if(type!=='textarea')input.type=type;
    input.value=draft?.key===parent.dataset.draft && Object.hasOwn(draft?.values||{},name)?draft.values[name]:value;
    input.required=required;
    wrapper.append(input);parent.append(wrapper);
    return input;
  }
  function formFor(parent,key,title,action,submit) {
    const form=node('form',undefined,'coursework-form');form.dataset.draft=key;
    form.append(node('h3',title));
    const control=node('button',action);control.type='submit';
    const remember=()=>{draft={key,values:Object.fromEntries(new FormData(form))};};
    form.addEventListener('input',remember);
    form.addEventListener('submit',event=>{
      event.preventDefault();
      if(sending||blocked||!ready)return;
      remember();
      submit(draft.values);
    });
    parent.append(form);
    return {form,finish:()=>form.append(control)};
  }
  function hide() {
    epoch++;read?.abort();view=null;sending=false;
    content.replaceChildren();say('');refresh.disabled=false;
  }
  function reset() {
    hide();selection=null;recipient=null;creating=false;
    blocked=false;draft=null;client=null;owner=null;filters={semester:'',subject:''};
  }
  function sessionExpired(error,session) {
    if(error.status!==401||!ready||session!==sessionEpoch)return false;
    onSessionExpired();
    return true;
  }
  function select(id=null,course=null) {
    if(sending)return;
    draft=null;selection=id;recipient=course;creating=false;load();
  }
  async function load(success='') {
    if(!ready||!active||sending)return;
    const current=++epoch, session=sessionEpoch;
    read?.abort();read=new AbortController();
    const signal=read.signal, connection=client;
    say(t('Загружаем учебные работы…','Loading coursework…'),'loading');
    content.replaceChildren();refresh.disabled=true;
    try{
      const list=await connection.read('',signal);
      const work=selection?await connection.read(path(selection),signal):null;
      const history=recipient&&work?await connection.read(path(selection)+'/recipients'+path(recipient),signal):null;
      if(current!==epoch)return;
      if(creating&&!list.offerings?.length){creating=false;draft=null;}
      view={list,work,history};blocked=false;connection.refreshed();
      render();say(success,success?'success':'');
    }catch(error){
      if(sessionExpired(error,session))return;
      if(current!==epoch)return;
      view=null;
      if(selection&&(error.status===403||error.status===404))
        button(content,t('Вернуться к списку','Back to coursework'),()=>select());
      say(courseworkError(error),'error');
    }finally{if(current===epoch||!ready)refresh.disabled=false;}
  }
  async function mutate(endpoint,method,fields,onSuccess) {
    if(sending||blocked||!ready)return;
    const current=epoch, session=sessionEpoch;
    sending=true;
    const controls=[...content.querySelectorAll('button, input, select, textarea')];
    controls.forEach(control=>{control.disabled=true;});
    refresh.disabled=true;say(t('Сохраняем…','Saving…'),'loading');
    try{
      const saved=await client.write(endpoint,method,fields);
      if(current!==epoch||!saved)return;
      draft=null;onSuccess?.(saved);
      sending=false;await load(t('Изменения сохранены.','Changes saved.'));
    }catch(error){
      if(sessionExpired(error,session))return;
      if(current!==epoch)return;
      if(error.status===403||error.status===404)content.replaceChildren();
      blocked=error.status===409;
      say(error.message==='retry-original'
        ?t('Ответ не получен. Повторите отправку с прежними данными.','No response. Retry with the original values.')
        :courseworkError(error),blocked?'conflict':'error');
    }finally{
      if(current===epoch||!ready){
        sending=false;refresh.disabled=false;
        controls.forEach(control=>{control.disabled=false;});
        if(blocked)for(const control of content.querySelectorAll('button[type="submit"]'))control.disabled=true;
      }
    }
  }
  function metadata(parent,work) {
    line(parent,[work.subject_name,work.group_name].filter(Boolean).join(' · '),'coursework-context');
    line(parent,t('Срок','Due')+' · '+date(work.due_at));
    line(parent,label(grading,work.grading_mode)+(work.max_points==null?'':' · '+t('Максимум','Maximum')+' '+work.max_points));
  }
  function files(parent, list=[]) {
    for(const file of list){
      const link=node('a',file.name);
      link.href='/api/v1/'+(owner.role==='student'?'me':'staff')+'/coursework/files'+path(file.id);
      const row=node('p');row.append(link);parent.append(row);
    }
  }
  function fileInput(form, label) {
    const wrapper=node('label',label), input=node('input');
    input.type='file';input.multiple=true;input.accept='.txt,.md';
    wrapper.append(input);form.append(wrapper);
    return input;
  }
  async function readFiles(input, send) {
    const current=epoch, session=sessionEpoch, selected=[...input.files];
    if(selected.length>2||selected.some(file=>file.size<1||file.size>65536||!(/\.(txt|md)$/i).test(file.name))){
      say(t('Выберите до двух файлов TXT или MD по 64 КиБ.','Choose up to two TXT or MD files, 64 KiB each.'),'error');return;
    }
    let attachments;
    try {
      attachments=await Promise.all(selected.map(async file=>{
        let bytes='';for(const byte of new Uint8Array(await file.arrayBuffer()))bytes+=String.fromCharCode(byte);
        return {name:file.name,content:btoa(bytes)};
      }));
    }catch{
      if(current===epoch&&session===sessionEpoch)say(t('Не удалось прочитать файл.','Could not read the file.'),'error');
      return;
    }
    if(current===epoch&&session===sessionEpoch&&ready&&active)send(attachments);
  }
  function pill(parent,value) {
    const badge=node('span',label(states,value)||t('Сдач пока нет','No submissions yet'),'coursework-pill');
    if(Object.hasOwn(states,value))badge.dataset.state=value;
    parent.append(badge);
  }
  function history(parent,data) {
    parent.append(node('h3',t('История попыток','Submission history')));
    if(!data.attempts.length){line(parent,t('Сдач пока нет.','No submissions yet.'));return;}
    const list=node('ol',undefined,'coursework-history');parent.append(list);
    for(const attempt of data.attempts){
      const item=node('li');
      item.append(node('h4',t('Попытка','Attempt')+' '+attempt.number+' · '+date(attempt.submitted_at)));
      line(item,attempt.method==='in_person'?t('Очная сдача','In-person submission'):t('Текстовая сдача','Text submission'));
      if(attempt.late)line(item,t('Сдано с опозданием, без автоматического штрафа.','Submitted late, without an automatic penalty.'),'coursework-late');
      if(attempt.response!=null)line(item,attempt.response,'coursework-text');
      files(item,data.files?.filter(file=>file.attempt_no===attempt.number));
      for(const review of data.reviews.filter(entry=>entry.attempt_no===attempt.number)){
        const entry=node('div',undefined,'coursework-review');
        pill(entry,review.decision);
        line(entry,t('Версия проверки','Review version')+' '+review.revision+' · '+date(review.reviewed_at));
        if(review.points!=null)line(entry,t('Баллы','Points')+' · '+review.points);
        line(entry,review.comment,'coursework-text');
        if(review.reason)line(entry,t('Основание','Reason')+' · '+review.reason,'coursework-text');
        item.append(entry);
      }
      list.append(item);
    }
    for(const publication of data.brs_publications||[])
      line(parent,t(`БРС · попытка ${publication.brs_attempt_no} · версия ${publication.revision_no} · баллы ${publication.points}`,
        `BRS · attempt ${publication.brs_attempt_no} · revision ${publication.revision_no} · points ${publication.points}`));
  }
  function renderList() {
    const staff=owner.role==='staff';
    const results=node('div',undefined,'coursework-results');
    if(staff&&view.list.offerings.length)
      button(content,t('Создать черновик','New draft'),()=>{creating=true;draft=null;render();});
    if(!staff&&view.list.items.length){
      const bar=node('div',undefined,'coursework-actions');
      for(const [key,name,value] of [['semester',t('Семестр','Semester'),'semester_id'],['subject',t('Дисциплина','Subject'),'subject_name']]){
        const values=[...new Set(view.list.items.map(row=>row[value]))];
        const input=field(bar,key,name,{choices:[['',t('Все','All')],...values.map(item=>[item,item])],value:filters[key]});
        input.addEventListener('change',()=>{
          filters[key]=input.value;
          renderRows(results,false);
        });
      }
      content.append(bar);
    }
    content.append(results);
    renderRows(results,staff);
  }
  function renderRows(results,staff) {
    results.replaceChildren();
    const rows=staff?view.list.items:filterWorks(view.list.items,filters);
    if(!rows.length)line(results,staff&&!view.list.offerings.length
      ?t('Нет действующих преподавательских назначений.','No active teaching assignments.')
      :t('В этом списке пока нет работ.','No coursework in this list.'));
    for(const work of rows){
      const row=node('article',undefined,'coursework-row'), copy=node('div'), actions=node('div',undefined,'coursework-actions');
      copy.append(node('h3',work.title));metadata(copy,work);
      pill(actions,staff?work.status:work.latest_attempt_state);
      if(staff)line(actions,t('Ожидают проверки','Awaiting review')+': '+work.queue.awaiting_review);
      button(actions,t('Открыть задание','Open assignment'),()=>select(work.id));
      row.append(copy,actions);results.append(row);
    }
  }
  function studentDetail(work) {
    const layout=node('div',undefined,'coursework-split'), summary=node('div'), submission=node('div');
    summary.append(node('h3',work.title));metadata(summary,work);pill(summary,work.latest_attempt_state);
    line(summary,work.description,'coursework-text');
    files(summary,work.materials);
    if(work.can_submit_text) {
      const {form,finish}=formFor(submission,'submit:'+work.id,t('Текстовая сдача','Text submission'),
        work.can_resubmit?t('Сдать повторно','Resubmit'):t('Отправить работу','Submit work'), values=>{
          if(!values.response.trim()||unicodeLength(values.response)>4000||values.response.includes('\0')){
            say(t('Введите от 1 до 4000 кодовых точек без нулевых символов.',
                  'Enter 1–4000 code points with no null characters.'),'error');return;
          }
          readFiles(attachments, selected=>mutate(path(work.id)+'/submissions'+(selected.length?'/with-files':''),'POST',{
            expected_version:work.recipient_version,response:values.response,...(selected.length?{files:selected}:{})
          }));
        });
      const input=field(form,'response',t('Текст работы','Your response'),{type:'textarea'});
      const attachments=fileInput(form,t('Вложения к сдаче (TXT, MD)','Submission attachments (TXT, MD)'));
      const count=node('small');form.append(count);
      const update=()=>{count.textContent=unicodeLength(input.value)+' / 4000';};
      input.addEventListener('input',update);update();finish();
    }else line(submission,t('Текстовая сдача сейчас недоступна.','Text submission is currently unavailable.'));
    layout.append(summary,submission);content.append(layout);history(content,work);
  }
  function draftForm(work) {
    const {form,finish}=formFor(content,work?'edit:'+work.id:'create',
      work?t('Редактирование черновика','Edit draft'):t('Новая учебная работа','New coursework'),
      t('Сохранить черновик','Save draft'),values=>{
        const {offering_id,...data}=values;data.due_at=Date.parse(data.due_at+'+03:00')/1000;
        mutate(work?path(work.id):'',work?'PATCH':'POST',
          work?{expected_version:work.version,data}:{offering_id,...data},
          saved=>{selection=saved.assignment_id;creating=false;});
      });
    if(!work)field(form,'offering_id',t('Поток','Offering'),{choices:view.list.offerings.map(
      flow=>[flow.id,flow.subject_name+' · '+flow.group_name+' · '+flow.semester_id]),value:view.list.offerings[0]?.id});
    field(form,'title',t('Название','Title'),{value:work?.title}).maxLength=160;
    field(form,'description',t('Условия задания','Assignment instructions'),{type:'textarea',value:work?.description}).maxLength=4000;
    field(form,'due_at',t('Срок (МСК)','Due (MSK)'),{type:'datetime-local',
      value:work?new Date((work.due_at+10800)*1000).toISOString().slice(0,19):''}).step=1;
    field(form,'kind',t('Тип работы','Assignment type'),{choices:options(kinds),value:work?.kind||'lab'});
    field(form,'mode',t('Способ сдачи','Submission method'),{choices:options(modes),value:work?.mode||'both'});
    finish();
  }
  function command(work,action,version,data) {
    mutate(path(work.id)+'/commands','POST',{expected_version:version,action,data});
  }
  function publishForm(work) {
    const {form,finish}=formFor(content,'publish:'+work.id,t('Публикация задания','Publish assignment'),
      t('Опубликовать задание','Publish assignment'),values=>{
        const data={grading_mode:values.grading_mode};
        if(data.grading_mode==='independent')data.max_points=Number(values.max_points);
        if(data.grading_mode==='brs')data.event_code=values.event_code.trim();
        command(work,'publish',work.version,data);
      });
    line(form,t('После публикации параметры оценивания фиксируются.','Grading settings are locked after publication.'));
    const mode=field(form,'grading_mode',t('Режим оценивания','Grading mode'),{choices:options(grading),value:'ungraded'});
    const points=field(form,'max_points',t('Максимум баллов','Maximum score'),{type:'number',required:false});
    points.min=1;points.max=100;
    const event=field(form,'event_code',t('Код мероприятия БРС','BRS event code'),{required:false});
    const toggle=()=>{
      for(const [input,value] of [[points,'independent'],[event,'brs']]){
        input.parentElement.hidden=mode.value!==value;input.required=mode.value===value;
      }
    };
    mode.addEventListener('change',toggle);toggle();finish();
  }
  function staffDetail(work,details) {
    content.append(node('h3',work.title));metadata(content,work);pill(content,work.status);
    line(content,work.description,'coursework-text');
    files(content,work.materials);
    if(work.status==='draft'){
      draftForm(work);
      if((work.materials?.length||0)<2){
        const {form,finish}=formFor(content,'materials:'+work.id,t('Материалы задания','Assignment materials'),
          t('Добавить материалы','Add materials'),()=>readFiles(input, selected=>{
            if(selected.length)mutate(path(work.id)+'/materials','POST',{expected_version:work.version,files:selected});
          }));
        const input=fileInput(form,t('Файлы материалов (TXT, MD)','Material files (TXT, MD)'));
        input.required=true;finish();
      }
      publishForm(work);return;
    }
    line(content,t('Ожидают проверки','Awaiting review')+': '+work.queue.awaiting_review+' · '+t('Сдали','Submitted')+': '+work.queue.submitted);
    if(!work.recipients.length)line(content,t('Получателей нет.','No recipients.'));
    const recipients=node('div',undefined,'coursework-actions');content.append(recipients);
    for(const item of work.recipients)button(recipients,item.student_name,()=>select(work.id,item.course_id));
    if(!details)return;
    content.append(node('h3',details.student_name));history(content,details);
    if(details.can_record_in_person){
      const {finish}=formFor(content,'in-person:'+work.id+':'+details.course_id,
        t('Очная сдача','In-person submission'),t('Зарегистрировать очную сдачу','Record in-person submission'),
        ()=>command(work,'record_in_person',details.recipient_version,{course_id:details.course_id}));
      finish();
    }
    const attempt=details.attempts.at(-1);
    if(!attempt)return;
    const latest=details.reviews.filter(review=>review.attempt_no===attempt.number).at(-1);
    const published=details.brs_publications?.some(entry=>entry.attempt_no===attempt.number&&entry.review_revision===latest?.revision);
    if(work.grading_mode==='brs'&&latest?.decision==='reviewed'&&latest.points!=null&&!published){
      const {finish}=formFor(content,'brs:'+work.id+':'+details.course_id,t('Подтверждение баллов БРС','Confirm BRS points'),
        t('Опубликовать баллы в БРС','Publish points to BRS'),()=>command(work,'publish_brs',details.recipient_version,{
          course_id:details.course_id,attempt_no:attempt.number,review_revision:latest.revision,
          expected_result_version:details.brs_result_version
        }));
      finish();
    }
    const {form,finish}=formFor(content,'review:'+work.id+':'+details.course_id,t('Проверка и возврат','Review and return'),
      t('Сохранить решение','Save decision'),values=>{
        const data={course_id:details.course_id,attempt_no:attempt.number,decision:values.decision,comment:values.comment};
        if(values.decision==='reviewed'&&values.points!=null&&values.points!=='')data.points=Number(values.points);
        if(latest)data.reason=values.reason;
        command(work,'review',details.recipient_version,data);
      });
    const decision=field(form,'decision',t('Решение','Decision'),{
      choices:options({reviewed:states.reviewed,returned:states.returned,retry_allowed:states.retry_allowed}),value:'reviewed'});
    field(form,'comment',t('Комментарий','Comment'),{type:'textarea'}).maxLength=2000;
    if(latest){
      const reason=field(form,'reason',t('Основание новой версии','Reason for the new version'));
      reason.minLength=3;reason.maxLength=500;
    }
    if(work.max_points!=null){
      const points=field(form,'points',t('Баллы','Points'),{type:'number',required:false});
      points.min=0;points.max=work.max_points;
      const toggle=()=>{points.parentElement.hidden=decision.value!=='reviewed';};
      decision.addEventListener('change',toggle);toggle();
    }
    finish();
  }
  function render() {
    if(!ready||!active||!view)return;
    content.replaceChildren();
    if(view.work||creating)button(content,t('Вернуться к списку','Back to coursework'),()=>select());
    if(creating)draftForm(null);
    else if(!view.work)renderList();
    else if(owner.role==='student')studentDetail(view.work);
    else staffDetail(view.work,view.history);
    line(content,t('Пересмотр деканатом пока недоступен.','Dean’s office reviews are currently unavailable.'),'coursework-note');
  }
  refresh.addEventListener('click',()=>load());
  document.addEventListener('mgimov:language',()=>{
    get('coursework-title').textContent=t('Учебные работы','Coursework');
    refresh.textContent=t('Обновить','Refresh');
    if(ready&&active&&!sending&&!blocked)render();
  });
  document.addEventListener('mgimov:deadline-open',event=>{
    if(event.detail?.page==='coursework'&&typeof event.detail.id==='string'&&ready&&owner.role==='student')select(event.detail.id);
  });
  document.addEventListener('mgimov:page',event=>{
    const next=event.detail==='coursework';
    if(active===next)return;
    active=next;
    if(active)load();else hide();
  });
  return {
    identity(value,csrf,expired) {
      onSessionExpired=expired;
      if(value.state!=='ready'){
        sessionEpoch++;
        if(value.state==='anonymous'||value.state==='logout-pending'||value.identityInvalidated
           ||['login','logout'].includes(value.operation))reset();
        else hide();
        ready=false;root.hidden=true;return;
      }
      const changed=owner?.id!==value.user.id||owner?.role!==value.user.role;
      if(changed){sessionEpoch++;reset();owner=value.user;client=makeClient(owner,csrf);}
      if(ready&&!changed)return;
      ready=true;root.hidden=false;
      if(active)load();
    }
  };
}

let mounted;
export function courseworkIdentity(value,csrf,onSessionExpired) {
  mounted??=mountCoursework(document);
  mounted.identity(value,csrf,onSessionExpired);
}
