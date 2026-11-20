import {requestJson} from './api.js';
import {t} from './language.js';

export function takeQrFragment(host){
 const match=/^#attendance-qr=([A-Za-z0-9_-]{43})$/.exec(host.location.hash);
 if(!match)return null;
 host.history.replaceState(null,'',host.location.pathname+host.location.search+'#profile');
 return match[1];
}
// Read before shell navigation resolves an unknown hash. Never persist this bearer.
let incoming=globalThis.location&&globalThis.history?takeQrFragment(globalThis):null;

export function qrMatrix(document,matrix){
 if(!Array.isArray(matrix)||matrix.length<21||matrix.length>185||matrix.some(row=>!Array.isArray(row)||row.length!==matrix.length||row.some(v=>typeof v!=='boolean')))throw Error('Invalid QR matrix');
 const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');
 svg.setAttribute('viewBox',`0 0 ${matrix.length} ${matrix.length}`);svg.setAttribute('width','256');svg.setAttribute('height','256');
 svg.setAttribute('role','img');svg.setAttribute('aria-label',t('QR для отметки посещения','Attendance check-in QR'));
 const bg=document.createElementNS(ns,'rect');bg.setAttribute('width',matrix.length);bg.setAttribute('height',matrix.length);bg.setAttribute('fill','white');svg.append(bg);
 const path=document.createElementNS(ns,'path');path.setAttribute('fill','black');
 path.setAttribute('d',matrix.flatMap((row,y)=>row.flatMap((on,x)=>on?[`M${x} ${y}h1v1h-1z`]:[])).join(''));
 svg.append(path);return svg;
}

export function qrResultMessage(result){
 const labels={present:t('Присутствовал','Present'),absent:t('Отсутствовал','Absent'),
  late:t('Опоздал','Late'),unmarked:t('Не отмечено','Unmarked')};
 const label=labels[result.status];
 if(!label)return t('Не удалось определить текущую отметку. Откройте журнал.','Unable to determine the current mark. Open the journal.');
 if(result.manual_mark||result.outcome==='manual_priority'||result.status!=='present')
  return t(`Текущий статус: ${label}. QR не изменил ручную отметку.`,`Current status: ${label}. The QR did not change the teacher’s manual mark.`);
 return t(`Посещение подтверждено: ${label}.`,`Attendance confirmed: ${label}.`);
}

export function mountQrAttendance(document,request=requestJson,host=globalThis,initialToken=incoming){
 incoming=null;
 const dialog=document.getElementById('attendance-qr-dialog'),content=document.getElementById('attendance-qr-content'),status=document.getElementById('attendance-qr-status');
 let user=null,owner=null,csrf=()=>'',expired=()=>{},epoch=0,abort,timer,busy=false;
 let token=initialToken,tokenOwner=null,lesson=null,challenge=null,issueRequest=null;
 const node=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;};
 const button=(text,action)=>{const b=node('button',text);b.type='button';b.addEventListener('click',action);content.append(b);return b;};
 const stop=()=>{epoch++;abort?.abort();clearTimeout(timer);busy=false;content.replaceChildren();status.textContent='';};
 const hide=()=>{stop();dialog.close();challenge=null;issueRequest=null;};
 function error(error){status.textContent=error.status===409?t('QR истёк или данные изменились. Обновите занятие и запросите новый код.','QR expired or data changed. Refresh the lesson and request a new code.'):
  error.status===429?t('Слишком много запросов. Повторите через минуту.','Too many requests. Try again in a minute.'):
  t('QR недоступен. Проверьте вход, полномочия и соединение.','QR unavailable. Check your session, permissions and connection.');}
 async function run(path,body,accept){
  if(!user||busy)return;
  const generation=++epoch;abort?.abort();abort=new AbortController();busy=true;
  const pending=abort,timeout=setTimeout(()=>pending.abort(),10000),started=host.performance.now();
  status.textContent=t('Загрузка…','Loading…');
  try{
   const data=await request(path,{method:'POST',body,signal:pending.signal,headers:{'X-MGIMOv-User':user.id,'X-CSRF-Token':csrf()}});
   if(generation!==epoch)return;
   status.textContent='';accept(data,host.performance.now()-started);
  }catch(e){
   if(generation!==epoch)return;error(e);
   if(e.status===409)issueRequest=null;
   if([403,404].includes(e.status))content.replaceChildren();
   if(e.status===401){token=null;hide();expired();}
   else if(path.endsWith('/preview')&&![403,404,409,422].includes(e.status))button(t('Повторить','Retry'),preview);
  }
  finally{clearTimeout(timeout);if(generation===epoch)busy=false;}
 }
 function staff(){
  content.replaceChildren();
  content.append(node('p',t('QR действует 60 секунд, только во время занятия. Пересылка кода не подтверждает физическое присутствие.','QR is valid for 60 seconds during the lesson. Sharing a code does not prove physical presence.')));
  button(t('Выпустить QR','Issue QR'),async()=>{
   if(busy)return;
   content.querySelector('svg')?.remove();
   if(!issueRequest){
    // Refresh the actual journal immediately before creating a new command.
    const generation=++epoch;abort?.abort();abort=new AbortController();busy=true;
    const pending=abort,timeout=setTimeout(()=>pending.abort(),10000);
    try{
     const data=await request('/api/v1/staff/attendance/lessons/'+lesson,{signal:abort.signal,headers:{'X-MGIMOv-User':user.id}});
     if(generation!==epoch)return;
     issueRequest={expected_version:data.version,lesson_version:data.lesson.version,request_key:host.crypto.randomUUID().replaceAll('-','')};
    }catch(e){if(generation===epoch){error(e);if(e.status===401){hide();expired();}}return;}
    finally{clearTimeout(timeout);if(generation===epoch)busy=false;}
   }
   await run('/api/v1/staff/attendance/lessons/'+lesson+'/qr',issueRequest,(data,elapsed)=>{
    clearTimeout(timer);challenge=data;issueRequest=null;staff();
    if(!data.code_available){status.textContent=t('Запрос уже выполнен. Код не хранится на сервере: выпустите новый QR.','Request already completed. The server does not retain the code: issue a new QR.');return;}
    const remaining=data.expires_in*1000-elapsed;
    if(remaining<=0){status.textContent=t('QR истёк. Выпустите новый код.','QR expired. Issue a new code.');return;}
    content.prepend(qrMatrix(document,data.matrix));
    status.textContent=t('QR выпущен. Студент сканирует код камерой и подтверждает отметку после входа.','QR issued. Students scan with their camera and confirm after signing in.');
    timer=setTimeout(()=>{content.querySelector('svg')?.remove();status.textContent=t('QR истёк. Выпустите новый код.','QR expired. Issue a new code.');},remaining);
   });
  });
  if(challenge)button(t('Отозвать QR','Revoke QR'),()=>run('/api/v1/staff/attendance/lessons/'+lesson+'/qr/'+challenge.id+'/close',{},()=>{challenge=null;clearTimeout(timer);staff();status.textContent=t('QR отозван.','QR revoked.');}));
 }
 function preview(){
  if(!token||user?.role!=='student')return;
  tokenOwner=user.id;dialog.showModal();content.replaceChildren();
  run('/api/v1/me/attendance/qr/preview',{token},data=>{
   content.append(node('h3',data.subject),node('p',data.date),node('p',t('Подтверждение установит «Присутствовал». Ручная отметка преподавателя сохраняет приоритет.','Confirmation marks you present. A manual teacher mark takes priority.')));
   button(t('Подтвердить посещение','Confirm attendance'),()=>run('/api/v1/me/attendance/qr/check-in',{token},result=>{
    token=null;content.replaceChildren();status.textContent=qrResultMessage(result);
   }));
  });
 }
 document.addEventListener('mgimov:attendance-qr-open',event=>{
  if(user?.role!=='staff')return;hide();lesson=event.detail.lesson.id;dialog.showModal();staff();
 });
 document.getElementById('attendance-qr-close').addEventListener('click',()=>{token=null;hide();});
 dialog.addEventListener('cancel',event=>{event.preventDefault();token=null;hide();});
 document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden')hide();});
 host.addEventListener?.('pageshow',()=>{if(challenge)hide();});
 host.addEventListener?.('hashchange',()=>{const value=takeQrFragment(host);if(value){hide();token=value;tokenOwner=user?.id??null;preview();}});
 document.addEventListener('mgimov:language',()=>hide());
 return {identity(value,readCsrf,onExpired){
  const next=value.state==='ready'?value.user:null;
  const transient=value.state==='suspended'||(value.state==='loading'&&value.operation==='refresh')||(value.state==='error'&&!value.identityInvalidated);
  if(!next){hide();if(!transient&&owner){token=null;tokenOwner=null;owner=null;}}
  else if(owner!==next.id+':'+next.role){hide();if(owner||(tokenOwner&&tokenOwner!==next.id)){token=null;tokenOwner=null;}owner=next.id+':'+next.role;}
  user=next;csrf=readCsrf;expired=onExpired;
  if(next?.role==='student'&&token)preview();
 }};
}
let mounted;
export function qrAttendanceIdentity(value,csrf,expired){mounted??=mountQrAttendance(document);mounted.identity(value,csrf,expired);}
