// Derived exclusively from the existing Student API projections.
import {addDays} from './utils/dates.js';

export function deadlineRows({coursework,attestations,gradebook},now=Date.now()) {
  const today=gradebook.today, nearDay=addDays(today,3), rows=[];
  function add(row){
    const date=row.precision==='date'?row.date:new Intl.DateTimeFormat('sv-SE',{
      timeZone:'Europe/Moscow',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(row.at*1000));
    const overdue=row.kind!=='assessment'&&(row.precision==='date'?date<today:row.at*1000<now);
    const passed=row.kind==='assessment'&&(row.precision==='date'?date<today:(row.until??row.at)*1000<now);
    if(passed)return; // A past exam date is not a missed submission deadline.
    rows.push({...row,date,urgency:overdue?'overdue':date<=nearDay?'soon':'upcoming'});
  }
  for(const work of coursework.items){
    if(work.status!=='published'||!work.needs_submission)continue;
    add({id:'work:'+work.id,target:work.id,page:'coursework',kind:'submission',precision:'time',
      at:work.due_at,title:work.title,subject:work.subject_name,state:work.latest_attempt_state||'assigned'});
  }
  for(const course of attestations.items){
    const slots=new Map();
    for(const event of course.history){
      if(event.kind==='scheduled')slots.set(event.slot_id,event);
      else if(['cancelled','excused','unexcused','published','completed','corrected'].includes(event.kind))slots.delete(event.slot_id);
    }
    for(const slot of slots.values())add({id:'slot:'+slot.slot_id,target:course.id,page:'attestations',
      kind:'assessment',precision:'time',at:slot.starts_at,until:slot.ends_at,title:course.control==='exam'?'Экзамен':'Зачёт',
      subject:course.subject,state:'scheduled'});
  }
  for(const item of gradebook.exams){
    if(Object.hasOwn(item,'official_result')||item.event_status==='cancelled'||item.status==='passed')continue;
    if(item.scheduled_on)add({id:'exam:'+item.id,target:item.id,page:'academics',kind:'assessment',precision:'date',
      date:item.scheduled_on,title:item.control==='exam'?'Экзамен':'Зачёт',subject:item.subject,state:item.status});
    if(item.deadline_on)add({id:'due:'+item.id,target:item.id,page:'academics',kind:'assessment_deadline',precision:'date',
      date:item.deadline_on,title:'Срок сдачи аттестации',subject:item.subject,state:item.status});
  }
  return rows.sort((a,b)=>a.date.localeCompare(b.date)||(a.at??0)-(b.at??0)||a.id.localeCompare(b.id));
}

export function createDeadlines({request,publish,expired,clock=()=>Date.now()}) {
  let owner=null,generation=0,abort;
  return {
    clear(){generation++;abort?.abort();owner=null;publish({state:'hidden'});},
    async load(user){
      owner=user;const current=++generation;abort?.abort();abort=new AbortController();
      if(user?.role!=='student'){publish({state:'hidden'});return;}
      publish({state:'loading'});
      try{
        const options={signal:abort.signal,headers:{'X-Mgimov-User':user.id}};
        const [coursework,attestations,gradebook]=await Promise.all([
          request('/api/v1/me/coursework',options),request('/api/v1/me/attestations',options),
          request('/api/v1/me/gradebook',options)]);
        if(current!==generation||owner!==user)return;
        publish({state:'ready',items:deadlineRows({coursework,attestations,gradebook},clock())});
      }catch(error){
        if(current!==generation)return;
        publish({state:'error',status:error.status});
        if(error.status===401){this.clear();expired();}
      }
    }
  };
}
