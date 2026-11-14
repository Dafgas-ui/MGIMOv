import {requestJson} from './api.js';
import {locale,t} from './language.js';

const states = {
  scheduled:['Назначено','Scheduled'],cancelled:['Отменено','Cancelled'],
  draft:['Черновик','Draft'],published:['Опубликовано','Published'],
  completed:['Завершено','Completed'],excused:['Уважительная неявка','Excused absence'],
  unexcused:['Неуважительная неявка','Unexcused absence'],corrected:['Исправлено','Corrected'],
  review_requested:['Пересмотр запрошен','Review requested'],
  review_approved:['Пересмотр разрешён','Review approved'],
  review_revoked:['Разрешение отозвано','Approval revoked'],
  conflict_resolved:['Решение деканата','Dean’s office decision'],
  not_admitted:['Не допущен','Not admitted'],admission_restored:['Допуск восстановлен','Admission restored']
};
const stamp = seconds => new Date(seconds*1000).toLocaleString(locale(),{
  timeZone:'Europe/Moscow',dateStyle:'short',timeStyle:'short'
});
const localStamp = value => Date.parse(value+'+03:00')/1000;
const outcome = row => row.grade!=null?String(row.grade):
  row.outcome==='pass'?t('Зачтено'):row.outcome==='fail'?t('Не зачтено'):'';

export function mountAttestations(document,request=requestJson){
  const root=document.getElementById('attestations-section');
  const status=document.getElementById('attestations-status');
  const content=document.getElementById('attestations-content');
  const element=(tag,text)=>{
    const node=document.createElement(tag);
    if(text!==undefined)node.textContent=text;
    return node;
  };
  let user=null, csrf=()=>'', read=null, generation=0, selected=null, pending=null, sending=false;
  let lastView=null;
  const headers=()=>({'X-Mgimov-User':user.id});
  const staff='/api/v1/staff/attestations';
  const line=(parent,text)=>parent.append(element('p',text));
  const button=(parent,label,action)=>{
    const control=element('button',label);
    control.type='button';control.addEventListener('click',action);parent.append(control);
    return control;
  };
  const message=error=>error.status===409
    ?t('Состояние изменилось или операция недоступна. Обновите данные.','The state changed or the action is unavailable. Refresh the data.')
    :error.status===422?t('Проверьте введённые значения.','Check the values you entered.')
    :error.status===403||error.status===404?t('Операция недоступна.','This action is unavailable.')
    :t('Ответ не получен. Обновите данные или повторите операцию.','No response. Refresh or retry the action.');

  async function load(course=selected){
    if(!user||sending)return;
    read?.abort();read=new AbortController();
    const epoch=++generation;
    status.textContent=t('Загружаем аттестации…','Loading assessments…');
    content.replaceChildren();
    const endpoint=user.role==='student'?'/api/v1/me/attestations':staff+(course?'/'+course:'');
    try{
      const data=await request(endpoint,{headers:headers(),signal:read.signal});
      if(epoch!==generation||!user)return;
      status.textContent='';
      lastView={course,data};
      if(user.role==='student')showStudent(data.items);
      else if(course)showStaff(course,data);
      else showList(data.items);
    }catch(error){
      if(epoch===generation&&user)status.textContent=message(error);
    }
  }

  async function mutate(course,path,body){
    if(!user||sending)return;
    sending=true;
    const epoch=generation;
    const token=csrf();
    status.textContent=t('Сохраняем…','Saving…');
    try{
      await request(staff+'/'+course+'/'+path,{method:'POST',body,
        headers:{...headers(),'X-CSRF-Token':token}});
      if(epoch!==generation||!user)return;
      pending=null;
      sending=false;await load(course);
    }catch(error){
      if(epoch!==generation||!user)return;
      status.textContent=message(error);
      if(error.status&&error.status<500)pending=null;
    }finally{
      if(epoch===generation)sending=false;
    }
  }

  function send(course,version,action,values){
    const payload={action,expected_version:version,...values};
    const signature=JSON.stringify([course,payload]);
    if(pending&&pending.signature!==signature){
      status.textContent=t('Повторите предыдущую команду или обновите данные.','Retry the previous action or refresh.');
      return;
    }
    pending??={signature,body:{...payload,request_key:crypto.randomUUID().replaceAll('-','')}};
    return mutate(course,'commands',pending.body);
  }

  function showStudent(items){
    if(!items.length)line(content,t('Назначений пока нет.','No assessments yet.'));
    for(const item of items){
      const card=element('details');
      card.className='lesson-card';card.append(element('summary',item.subject));
      line(card,t(`Использовано попыток: ${item.used} из 3`,`Attempts used: ${item.used} of 3`));
      if(item.preview)line(card,t(`Опубликованные баллы БРС: ${item.preview.points} из 100`,
                                   `Published coursework points: ${item.preview.points} of 100`));
      if(item.preview?.missing.length)line(card,t('Есть незавершённые обязательные мероприятия.','Some required coursework is incomplete.'));
      if(item.debt)line(card,t('Академическая задолженность','Outstanding assessment'));
      if(item.awaiting_deanery)line(card,t('Ожидается решение деканата.','Awaiting a dean’s office decision.'));
      for(const event of item.history){
        const label=states[event.kind]?t(...states[event.kind]):event.kind;
        line(card,[label,event.number?t(`Попытка ${event.number}`,`Attempt ${event.number}`):'',
          event.commission?t('Комиссия','Commission'):'',stamp(event.kind==='scheduled'?event.starts_at:event.at),
          outcome(event)].filter(Boolean).join(' · '));
        if(event.commission_members?.length)line(card,event.commission_members.join(', '));
      }
      for(const debt of item.debt_history)line(card,`${debt.active?t('Долг возник','Debt opened'):t('Долг закрыт','Debt closed')} · ${stamp(debt.at)}`);
      content.append(card);
    }
  }

  function showList(items){
    if(!items.length)line(content,t('Доступных учебных позиций нет.','No assessment positions are available.'));
    for(const item of items){
      const card=element('article');card.className='lesson-card';
      line(card,`${item.student} · ${item.subject}`);
      button(card,item.activated?t('Открыть','Open'):t('Активировать','Activate'),()=>{
        selected=item.id;
        if(item.activated)load();else mutate(item.id,'activate',{});
      });
      content.append(card);
    }
  }

  function commandForm(parent,label,fields,submit){
    const details=element('details');details.append(element('summary',label));
    const form=element('form');
    const inputs={};
    for(const [name,title,type,options] of fields){
      const field=element('label',title);
      const input=element(options?'select':'input');
      if(!options){input.type=type;if(type==='text')input.maxLength=300;}
      if(options)for(const [value,caption] of options){
        const option=element('option',caption);option.value=value;input.append(option);
      }
      if(type==='multiple')input.multiple=true;
      else if(type!=='optional')input.required=true;
      inputs[name]=input;field.append(input);form.append(field);
    }
    const control=element('button',label);control.type='submit';form.append(control);
    form.addEventListener('submit',event=>{
      event.preventDefault();
      const values=Object.fromEntries(Object.entries(inputs).map(([key,input])=>
        [key,input.multiple?[...input.selectedOptions].map(x=>x.value):input.value]));
      submit(values);
    });
    details.append(form);parent.append(details);
  }

  function showStaff(course,data){
    const run=(action,values)=>send(course,data.version,action,values);
    const reasons=[['reason',t('Причина','Reason'),'text'],['reference',t('Основание','Reference'),'text']];
    const can=right=>data.permissions.includes(right);
    button(content,t('К списку','Back to list'),()=>{pending=null;selected=null;load();});
    if(data.brs_changed)line(content,t('Опубликованные баллы изменились после подтверждения результата.',
      'Published coursework points changed after the result was confirmed.'));
    if(can('schedule')&&data.state.used<3&&!data.state.conflict&&
        !Object.values(data.state.stages).some(x=>['scheduled','draft','published'].includes(x))&&
        (!data.state.latest||data.state.debt)){
      const people=data.examiners.map(x=>[x.id,x.full_name]);
      const fields=[['starts_at',t('Начало (МСК)','Start (Moscow time)'),'datetime-local'],
        ['ends_at',t('Окончание (МСК)','End (Moscow time)'),'datetime-local'],
        ['examiner_id',t('Ответственный','Examiner'),'select',people],
        ['room_id',t('Аудитория','Room'),'optional',[['',t('Без аудитории','No room')],...data.rooms.map(x=>[x.id,x.label])]]];
      if(data.state.used===2)fields.push(['commission',t('Участники комиссии','Commission members'),'multiple',people]);
      commandForm(content,t('Назначить испытание','Schedule assessment'),fields,v=>run('scheduled',{
        ...v,room_id:v.room_id||null,starts_at:localStamp(v.starts_at),ends_at:localStamp(v.ends_at)}));
    }
    if(can('review')&&data.control==='exam'&&!data.state.used){
      const action=data.state.admitted===false?'admission_restored':'not_admitted';
      commandForm(content,t(...states[action]),reasons.slice(0,1),v=>run(action,v));
    }
    if(can('review')&&data.state.conflict)
      commandForm(content,t('Зафиксировать решение по расхождению','Record a decision on the discrepancy'),reasons,v=>run('conflict_resolved',v));
    for(const [slot,record] of Object.entries(data.slots)){
      const card=element('article');card.className='lesson-card';
      const phase=data.state.stages[slot],values={slot_id:slot};
      line(card,t(`Попытка ${record.number} · ${stamp(record.starts_at)}`,`Attempt ${record.number} · ${stamp(record.starts_at)}`));
      line(card,t(...states[phase]));
      if(record.commission.length)line(card,t('Комиссионная аттестация','Commission assessment'));
      const grade=data.control==='credit'
        ?['outcome',t('Исход','Outcome'),'select',[['pass',t('Зачтено')],['fail',t('Не зачтено')]]]
        :['grade',t('Оценка','Grade'),'select',[2,3,4,5].map(n=>[n,String(n)])];
      if(can('schedule')&&phase==='scheduled'&&Date.now()/1000<record.starts_at){
        commandForm(card,t('Отменить испытание','Cancel assessment'),reasons.slice(0,1),v=>run('cancelled',{...values,...v}));
      }
      if(can('schedule')&&['scheduled','draft'].includes(phase)&&Date.now()/1000>=record.ends_at){
        for(const kind of ['excused','unexcused'])
          commandForm(card,t(...states[kind]),reasons,v=>run(kind,{...values,...v}));
      }
      if(can('examiner')&&record.examiner_id===user.id){
        if(['scheduled','draft'].includes(phase)&&Date.now()/1000>=record.starts_at)
          commandForm(card,t('Сохранить черновик','Save draft'),data.control==='exam'?[grade]:[],
            v=>run('draft',{...values,grade:v.grade?Number(v.grade):null}));
        if(phase==='draft')button(card,t('Подтвердить и опубликовать','Confirm and publish'),()=>run('published',values));
        if(phase==='published')button(card,t('Завершить запись','Complete record'),()=>run('completed',values));
        if(!data.late&&['published','completed'].includes(phase))commandForm(card,t('Запросить пересмотр','Request review'),
          [grade,...reasons],v=>run('review_requested',{...values,...v,executor_id:user.id,...(v.grade?{grade:Number(v.grade)}:{})}));
      }
      if(data.late&&can('late_request')&&data.reviewers.length&&['published','completed'].includes(phase)){
        const executor=['executor_id',t('Исполнитель','Correction executor'),'select',data.reviewers.map(x=>[x.id,x.full_name])];
        commandForm(card,t('Запросить послесеместровый пересмотр','Request a post-term review'),
          [grade,executor,...reasons],v=>run('review_requested',{...values,...v,...(v.grade?{grade:Number(v.grade)}:{})}));
      }
      const result=data.state.official[slot];
      if(result)line(card,outcome(result.data));
      content.append(card);
    }
    const applicable=new Set(data.applicable_review_versions);
    for(const event of data.events.filter(x=>x.kind==='review_requested')){
      const box=element('article'), values={review_version:event.version};
      line(box,`${t(...states.review_requested)} · ${outcome(event.data)} · ${stamp(event.at)}`);
      const approval=data.events.find(x=>x.kind==='review_approved'&&x.data.review_version===event.version);
      const closed=data.events.some(x=>['corrected','review_revoked'].includes(x.kind)&&x.data.review_version===event.version);
      if(can('review')&&!approval&&!closed)button(box,t('Разрешить пересмотр','Approve review'),()=>run('review_approved',values));
      if(can('review')&&approval&&!closed)commandForm(box,t('Отозвать разрешение','Revoke approval'),reasons.slice(0,1),v=>run('review_revoked',{...values,...v}));
      if(applicable.delete(event.version))
        button(box,t('Внести исправление','Apply correction'),()=>run('corrected',values));
      content.append(box);
    }
    for(const review_version of applicable){
      button(content,t(`Внести исправление № ${review_version}`,`Apply correction #${review_version}`),
        ()=>run('corrected',{review_version}));
    }
  }
  document.getElementById('attestations-retry').addEventListener('click',()=>{if(!sending){pending=null;load();}});
  document.addEventListener('mgimov:language',()=>{
    if(!user||!lastView||sending)return;
    content.replaceChildren();
    if(user.role==='student')showStudent(lastView.data.items);
    else if(lastView.course)showStaff(lastView.course,lastView.data);
    else showList(lastView.data.items);
  });
  return {
    setUser(next,token){
      if(next?.id===user?.id&&next?.role===user?.role)return;
      generation++;read?.abort();user=next;csrf=token;
      pending=null;sending=false;selected=null;lastView=null;
      root.hidden=!user;content.replaceChildren();status.textContent='';
      if(user)load();
    }
  };
}

let mounted;
export function attestationIdentity(user,csrf){
  mounted??=mountAttestations(document);
  mounted.setUser(user,csrf);
}
