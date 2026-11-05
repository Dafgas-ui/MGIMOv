import {requestJson} from './api.js';
import {requestsIdentity} from './requests.js';
import {academicsIdentity} from './academics.js';
import {scheduleIdentity} from './schedule.js';
import {createAccountState} from './account-state.js';
const get = id => document.getElementById(id);
const form = get('login-form'), fields = get('login-fields'), message = get('account-message');
const profile = get('profile-details'), loginPanel = get('login-panel'), accountPanel = get('account-panel');
const channel = typeof BroadcastChannel === 'function' ? new BroadcastChannel('mgimov-identity-v1') : null;
const controller = createAccountState({request:requestJson,
  readCsrf() {
    const name = location.protocol === 'https:' ? '__Host-mgimov_csrf' : 'mgimov_csrf';
    return document.cookie.split(';').map(s=>s.trim()).find(s=>s.startsWith(name+'='))?.slice(name.length+1) || '';
  },
  signalChange:()=>channel?.postMessage('identity-changing'),
  publish(value) {
    if (typeof scheduleIdentity === 'function') scheduleIdentity(null);
    if (typeof academicsIdentity === 'function') academicsIdentity(null);
    if (typeof requestsIdentity === 'function' && value.state!=='ready') requestsIdentity(null,{suspend:value.state==='suspended' || (value.state==='loading' && value.operation==='refresh') || (value.state==='error' && !value.identityInvalidated),discardOperation:value.operation==='logout'});
    profile.replaceChildren(); accountPanel.hidden = true; loginPanel.hidden = false;
    fields.disabled = ['loading','logout-pending','suspended'].includes(value.state);
    get('account-check').disabled = ['loading','suspended'].includes(value.state);
    get('logout-retry').hidden = value.state !== 'logout-pending';
    message.textContent = value.message;
    if (value.state !== 'ready') return;
    get('password').value = '';
    loginPanel.hidden = true; accountPanel.hidden = false;
    if (typeof scheduleIdentity === 'function') scheduleIdentity(value.user);
    if (typeof academicsIdentity === 'function') academicsIdentity(value.user);
    if (typeof requestsIdentity === 'function') requestsIdentity(value.user);
    get('account-title').textContent = value.user.role === 'student' ? 'Профиль студента' : 'Учётная запись сотрудника';
    const labels = {full_name:'ФИО',faculty:'Факультет',program:'Программа',course:'Курс',study_group:'Группа',position:'Должность'};
    for (const [key,label] of Object.entries(labels)) {
      if (value.profile[key] === undefined) continue;
      const term = document.createElement('dt'), detail = document.createElement('dd');
      term.textContent = label; detail.textContent = String(value.profile[key]); profile.append(term,detail);
    }
  }
});
form.addEventListener('submit', event => {
  event.preventDefault(); if (controller.isBusy()) return;
  const login = get('login').value, password = get('password').value;
  get('password').value = ''; // Clear only after deliberate submission, not a background poll.
  controller.login(login,password);
});
get('logout').addEventListener('click',()=>controller.logout());
get('logout-retry').addEventListener('click',()=>controller.logout());
get('account-check').addEventListener('click',()=>controller.refresh());
if (channel) channel.onmessage = () => controller.clear('Состояние входа изменилось в другой вкладке. Проверьте вход.');
document.addEventListener('visibilitychange',()=> {
  if (document.visibilityState === 'hidden') {get('password').value='';controller.suspend();}
  else controller.refresh();
});
addEventListener('pagehide',()=>{get('password').value='';controller.clear();});
addEventListener('pageshow',event=>{if(event.persisted && document.visibilityState==='visible')controller.refresh();});
addEventListener('online',()=>{if(document.visibilityState==='visible')controller.refresh();});
setInterval(()=>{if(document.visibilityState === 'visible')controller.refresh({background:true});},60000);
if(document.visibilityState==='visible')controller.refresh();else controller.suspend();
