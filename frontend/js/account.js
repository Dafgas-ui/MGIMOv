import {shellIdentity} from './ui-shell.js';
import {mvpIdentity} from './mvp.js';
import {requestJson} from './api.js';
import {requestsIdentity} from './requests.js';
import {academicsIdentity} from './academics.js';
import {scheduleIdentity} from './schedule.js';
import {attestationIdentity} from './attestations.js';
import {courseworkIdentity} from './coursework.js';
import {attendanceIdentity} from './attendance.js';
import {qrAttendanceIdentity} from './attendance-qr.js';
import {roomsIdentity} from './rooms.js';
import {deadlinesIdentity} from './deadlines.js';
import {forecastIdentity} from './forecast.js';
import {mountLanguage,t} from './language.js';
import {createAccountState,createAppearanceState,appearanceSurfaces} from './account-state.js';
const get = id => document.getElementById(id);
const form = get('login-form'), fields = get('login-fields'), message = get('account-message');
const profile = get('profile-details'), loginPanel = get('login-panel'), accountPanel = get('account-panel');
const channel = typeof BroadcastChannel === 'function' ? new BroadcastChannel('mgimov-identity-v1') : null;
let appearanceStorage=null;
try { appearanceStorage=globalThis.localStorage; } catch { /* Appearance remains usable in memory when browser storage is blocked. */ }
const appearanceTheme=get('appearance-theme'), appearancePalette=get('appearance-palette'), appearanceCustom=get('appearance-custom');
const readCsrf=()=>{
  const name=location.protocol==='https:'?'__Host-mgimov_csrf':'mgimov_csrf';
  return document.cookie.split(';').map(s=>s.trim()).find(s=>s.startsWith(name+'='))?.slice(name.length+1)||'';
};
const language=mountLanguage(document,{request:requestJson,csrf:readCsrf,storage:appearanceStorage,
  changed:()=>controller.refresh()});
const appearance = createAppearanceState({
  storage:appearanceStorage,
  cryptoObject:globalThis.crypto,
  prefersDark:()=>typeof matchMedia==='function'&&matchMedia('(prefers-color-scheme: dark)').matches,
  apply(value) {
    const root=document.documentElement;
    root.dataset.theme=value.resolvedTheme;
    root.dataset.themeMode=value.settings.theme;
    root.dataset.palette=value.settings.palette;
    root.style.setProperty('--accent',value.colors.accent);
    root.style.setProperty('--on-accent',value.colors.onAccent);
    root.style.setProperty('--accent-soft',value.colors.accentSoft);
    root.style.setProperty('--focus',value.colors.focus);
    const meta=document.querySelector('meta[name="theme-color"]');
    if(meta)meta.content=appearanceSurfaces[value.resolvedTheme].background;
  },
  publish(value) {
    appearanceTheme.value=value.settings.theme;
    appearancePalette.value=value.settings.palette;
    appearanceCustom.value=value.settings.custom;
    const color=value.colors;
    get('appearance-contrast').textContent=`${t('Акцент','Accent')} ${color.accent.toUpperCase()} · ${t('текст','text')} ${color.textRatio.toFixed(2)}:1 · ${t('ссылки','links')} ${color.linkRatio.toFixed(2)}:1.${color.adjusted?t(' Цвет скорректирован для контраста.',' Colour adjusted for contrast.'):''}`;
    const labels={anonymous:'Настройки применяются в этой вкладке. Войдите, чтобы сохранить их отдельно для аккаунта.',loading:'Загружаем настройки этого аккаунта…',ready:'Настройки сохраняются отдельно для этого аккаунта на устройстве.',saved:'Настройки сохранены для этого аккаунта на устройстве.',unavailable:'Локальное сохранение недоступно. Настройки останутся до закрытия страницы.'};
    get('appearance-storage-status').textContent=t(labels[value.persistence]||labels.unavailable);
  }
});
appearanceTheme.addEventListener('change',()=>appearance.update({theme:appearanceTheme.value}));
appearancePalette.addEventListener('change',()=>appearance.update({palette:appearancePalette.value,custom:appearanceCustom.value}));
appearanceCustom.addEventListener('input',()=>appearance.update({palette:'custom',custom:appearanceCustom.value}));
get('appearance-reset').addEventListener('click',()=>appearance.reset());
if(typeof matchMedia==='function') {
  const systemTheme=matchMedia('(prefers-color-scheme: dark)');
  systemTheme.addEventListener?.('change',()=>appearance.systemThemeChanged());
}
appearance.setUser(null);
const controller = createAccountState({request:requestJson,
  readCsrf,
  signalChange:()=>channel?.postMessage('identity-changing'),
  publish(value) {
    if(value.state==='ready')language.setUser(value.user);
    else if(['anonymous','logout-pending'].includes(value.state)||value.identityInvalidated)language.setUser(null);
    attestationIdentity(value.state==='ready'?value.user:null,readCsrf);
    roomsIdentity(value,()=>{controller.clear(t('Сессия завершена. Войдите снова.','Your session expired. Sign in again.'));channel?.postMessage('identity-changing');});
    forecastIdentity(value,()=>{
      controller.clear(t('Сессия завершена. Войдите снова.','Your session expired. Sign in again.'));
      channel?.postMessage('identity-changing');
    });
    deadlinesIdentity(value,()=>{
      controller.clear(t('Сессия завершена. Войдите снова.','Your session expired. Sign in again.'));
      channel?.postMessage('identity-changing');
    });
    attendanceIdentity(value,readCsrf,()=>{
      controller.clear(t('Сессия завершена. Войдите снова.','Your session expired. Sign in again.'));
      channel?.postMessage('identity-changing');
    });
    qrAttendanceIdentity(value,readCsrf,()=>{
      controller.clear(t('Сессия завершена. Войдите снова.','Your session expired. Sign in again.'));
      channel?.postMessage('identity-changing');
    });
    courseworkIdentity(value,readCsrf,()=>{
      controller.clear(t('Сессия завершена. Войдите снова.','Your session expired. Sign in again.'));
      channel?.postMessage('identity-changing');
    });
    if(value.state!=='ready'&&typeof shellIdentity==='function')shellIdentity(value);
    for(const name of ['schedule','academics','requests','notifications','documents'])get('nav-'+name).hidden=value.state!=='ready'||(['schedule','academics'].includes(name)&&value.user?.role!=='student');
    get('nav-staff').hidden=value.state!=='ready'||value.user?.role!=='staff';
    get('nav-home').href=value.state==='ready'?'#mvp-section':'#identity-title';
    if(typeof mvpIdentity==='function'&&value.state!=='ready')mvpIdentity(null,{suspend:value.state==='suspended'||(value.state==='loading'&&value.operation==='refresh')||(value.state==='error'&&!value.identityInvalidated)});
    if(value.state==='anonymous')appearance.setUser(null);
    if (typeof scheduleIdentity === 'function') scheduleIdentity(null);
    if (typeof academicsIdentity === 'function') academicsIdentity(null);
    if (typeof requestsIdentity === 'function' && value.state!=='ready') requestsIdentity(null,{suspend:value.state==='suspended' || (value.state==='loading' && value.operation==='refresh') || (value.state==='error' && !value.identityInvalidated),discardOperation:value.operation==='logout'});
    profile.replaceChildren(); accountPanel.hidden = true; loginPanel.hidden = false;
    fields.disabled = ['loading','logout-pending','suspended'].includes(value.state);
    get('account-check').disabled = ['loading','suspended'].includes(value.state);
    get('logout').hidden = value.state !== 'ready';
    get('logout-retry').hidden = value.state !== 'logout-pending';
    get('settings-account-message').textContent=value.state==='ready'
      ? t(`Вход выполнен · ${value.user.role==='student'?'студент':'сотрудник'}. Выход завершает текущую серверную сессию.`,
          `Signed in as ${value.user.role==='student'?'a student':'a staff member'}. Signing out ends this session.`)
      : t(value.state==='logout-pending'?value.message
        : value.state==='loading'?'Проверяем состояние аккаунта…':'Войдите, чтобы увидеть состояние аккаунта.');
    message.textContent = t(value.message);
    if (value.state !== 'ready') return;
    if(typeof mvpIdentity==='function')mvpIdentity(value.user);
    appearance.setUser(value.user.id);
    get('password').value = '';
    loginPanel.hidden = true; accountPanel.hidden = false;
    if (typeof scheduleIdentity === 'function') scheduleIdentity(value.user);
    if (typeof academicsIdentity === 'function') academicsIdentity(value.user);
    if (typeof requestsIdentity === 'function') requestsIdentity(value.user);
    get('account-title').textContent = t(value.user.role === 'student' ? 'Профиль студента' : 'Учётная запись сотрудника');
    const labels = {full_name:'ФИО',faculty:'Факультет',program:'Программа',course:'Курс',study_group:'Группа',position:'Должность'};
    for (const [key,label] of Object.entries(labels)) {
      if (value.profile[key] === undefined) continue;
      const term = document.createElement('dt'), detail = document.createElement('dd');
      term.textContent = t(label); detail.textContent = String(value.profile[key]); profile.append(term,detail);
    }
    if(typeof shellIdentity==='function')shellIdentity(value);
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
addEventListener('pagehide',()=>{get('password').value='';controller.clear(undefined,{preserveRoute:true});});
addEventListener('pageshow',event=>{if(event.persisted && document.visibilityState==='visible')controller.refresh();});
addEventListener('online',()=>{if(document.visibilityState==='visible')controller.refresh();});
setInterval(()=>{if(document.visibilityState === 'visible')controller.refresh({background:true});},60000);
if(document.visibilityState==='visible')controller.refresh();else controller.suspend();
