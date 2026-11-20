import {requestJson} from './api.js';
import {t} from './language.js';
import {createRoomSearch} from './rooms-state.js';
export function renderRooms(document,output,items){
 output.replaceChildren();const node=(tag,text)=>{const e=document.createElement(tag);e.textContent=text;return e;};
 if(!items.length)output.append(node('p',t('Подходящих аудиторий нет.','No matching rooms.')));
 for(const state of ['known','unknown']){
  const rooms=items.filter(r=>r.access_rules===state);if(!rooms.length)continue;
  const section=node('section','');section.append(node('h3',state==='known'?t('Режим доступа известен','Access rules available'):t('Режим доступа не подтверждён','Access rules unconfirmed')));
  for(const room of rooms){const card=node('article','');card.className='lesson-card';
   card.append(node('h4',room.building+' · '+room.number),node('p',t('Свободна по учтённому расписанию','Free according to the recorded timetable')),
    node('p',t(`Вместимость: ${room.capacity}`,`Capacity: ${room.capacity}`)));section.append(card);}
  output.append(section);
 }
}
export function announceRoomSearch(status,value){
 if(value.state==='loading')status.textContent=t('Загрузка…','Loading…');
 else if(value.state==='error')status.textContent=t('Поиск не выполнен. Проверьте дату, интервал и доступ.','Search failed. Check the date, interval and access.');
 else if(value.state==='ready'&&!value.catalogue){
  const count=value.data.items.length,unknown=value.data.items.filter(room=>room.access_rules==='unknown').length;
  status.textContent=count?t(`Найдено аудиторий: ${count}. Режим доступа не подтверждён: ${unknown}.`,`Rooms found: ${count}. Access rules unconfirmed: ${unknown}.`):t('Подходящих аудиторий нет.','No matching rooms.');
 }else status.textContent='';
}
export function mountRooms(document,request=requestJson){
 const root=document.getElementById('rooms-section'),form=document.getElementById('rooms-form'),output=document.getElementById('rooms-results'),status=document.getElementById('rooms-status'),button=document.getElementById('rooms-submit');
 let owner=null,onExpired=()=>{};
 const controller=createRoomSearch({request,expired:()=>onExpired(),publish(value){
  output.replaceChildren();button.disabled=value.state==='loading';announceRoomSearch(status,value);
  if(value.state!=='ready')return;
  if(value.catalogue){const select=form.elements.building;select.replaceChildren();const any=document.createElement('option');any.value='';any.textContent=t('Все корпуса','All buildings');select.append(any);
   for(const b of value.data.buildings){const option=document.createElement('option');option.value=b.id;option.textContent=b.name;select.append(option);}}
  else renderRooms(document,output,value.data.items);
 }});
 form.addEventListener('submit',event=>{event.preventDefault();const query=Object.fromEntries(new FormData(form));if(!query.building)delete query.building;controller.search(query);});
 document.addEventListener('mgimov:language',()=>{controller.setUser(owner);});
 return {identity(value,expired){onExpired=expired;const user=value.state==='ready'&&value.user.role==='student'?value.user:null;
  const changed=owner?.id!==user?.id;owner=user;root.hidden=!user;if(changed)form.reset();return controller.setUser(user);}};
}
let mounted;export function roomsIdentity(value,expired){mounted??=mountRooms(document);return mounted.identity(value,expired);}
