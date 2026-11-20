import {pagesFor,resolvePage} from './ui-state.js';
import {t,locale} from './language.js';
const aliases={'mvp-section':'home','dashboard-section':'home','identity-title':'profile','profile-section':'profile','settings-section':'settings','schedule-section':'schedule','academics-section':'academics',gradebook:'academics','requests-section':'requests','documents-section':'documents','notifications-section':'notifications','staff-section':'staff-schedule','staff-students-section':'students'};
let mounted=null;
export function mountShell(document,host=globalThis){
  const get=id=>document.getElementById(id);
  let user=null,ready=false,page='profile',scopeKey='';
  const positions=new Map();let navigationKey='';
  const roots=['profile-section','settings-section','schedule-section','academics-section','attestations-section','coursework-section','deadlines-section','rooms-section','requests-section','mvp-section','history-section'];
  const make=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;};
  const role=()=>ready?user?.role:null;
  const desktop=get('app-sidebar'),prev=get('app-nav-prev'),next=get('app-nav-next');
  const desktopFrame=desktop.parentElement;
  function updateScroll(){
    // Compare against the whole strip so the arrow buttons cannot create their own overflow.
    const width=desktopFrame?.clientWidth??desktop.clientWidth;
    const overflow=width>0&&desktop.scrollWidth>width;
    prev.hidden=next.hidden=!overflow;
    prev.disabled=!overflow||desktop.scrollLeft<=1;
    next.disabled=!overflow||desktop.scrollLeft+desktop.clientWidth>=desktop.scrollWidth-1;
  }
  function scrollNavigation(direction){desktop.scrollBy?.({left:direction*desktop.clientWidth*.7});}
  function reveal(link){
    if(!desktop.clientWidth || !link?.getBoundingClientRect)return;
    const view=desktop.getBoundingClientRect(),target=link.getBoundingClientRect();
    if(target.left<view.left || target.right>view.right)
      desktop.scrollLeft+=target.left<view.left?target.left-view.left-8:target.right-view.right+8;
  }
  desktop.addEventListener('scroll',updateScroll);
  desktop.addEventListener('wheel',event=>{
    if(prev.hidden||event.ctrlKey||event.shiftKey||event.deltaX||!event.deltaY)return;
    const left=desktop.scrollLeft;
    const step=event.deltaMode===1?16:event.deltaMode===2?desktop.clientWidth:1;
    desktop.scrollLeft+=event.deltaY*step;
    if(desktop.scrollLeft!==left)event.preventDefault();
  },{passive:false});
  desktop.addEventListener('focusin',event=>reveal(event.target));
  desktop.addEventListener('keydown',event=>{
    if(event.target===desktop && ['ArrowLeft','ArrowRight'].includes(event.key)){
      event.preventDefault();scrollNavigation(event.key==='ArrowLeft'?-1:1);
    }
  });
  prev.addEventListener('click',()=>scrollNavigation(-1));
  next.addEventListener('click',()=>scrollNavigation(1));
  function resizeNavigation(){updateScroll();reveal(desktop.querySelector?.('[aria-current="page"]'));updateScroll();}
  host.addEventListener?.('resize',resizeNavigation);
  if(desktopFrame&&typeof host.ResizeObserver==='function')new host.ResizeObserver(updateScroll).observe(desktopFrame);
  const route=value=>{let result=Object.hasOwn(aliases,value)?aliases[value]:value;if((result==='requests'||result==='home')&&role()==='staff')result='queue';return result;};
  const normalized=value=>resolvePage(route(value),role());
  function replaceHash(value){
    if(!host.location)return;
    const target=value?'#'+value:host.location.pathname+host.location.search;
    if(host.history?.replaceState)host.history.replaceState(host.history.state,'',target);
    else host.location.hash=value?'#'+value:'';
  }
  function routeFromLocation(){
    const value=host.location?.hash.slice(1)||'';
    page=normalized(value);
    if(value&&page!==route(value))replaceHash(page);
  }
  function navigation(){
    const key=`${ready}:${user?.role}:${page}:${locale()}`;if(navigationKey===key)return;navigationKey=key;
    const entries=pagesFor(role());
    for(const id of ['app-sidebar','app-bottom','app-mobile-menu']){
      const root=get(id);root.replaceChildren();
      const direct=role()==='staff'?['queue','staff-schedule','certificates']:['home','schedule','academics'];
      for(const [key,label] of id==='app-bottom'?entries.filter(([key])=>direct.includes(key)):entries){
        const link=make('a',t(label));link.href='#'+key;link.className='nav-link';link.dataset.page=key;
        if(key===page)link.setAttribute('aria-current','page');root.append(link);
      }
    }
    resizeNavigation();
    // Keep legacy anchor IDs as stable hooks for existing account lifecycle and tests.
    for(const id of ['home','schedule','academics','requests','notifications','documents','staff']){
      const link=get('nav-'+id);if(link)link.hidden=true;
    }
  }
  function apply(){
    const map={profile:'profile-section',settings:'settings-section',schedule:'schedule-section',academics:'academics-section',attestations:'attestations-section',coursework:'coursework-section',deadlines:'deadlines-section',rooms:'rooms-section',requests:'requests-section',queue:'requests-section',history:'history-section'};
    const visiblePage=ready?page:'profile';
    const active=map[visiblePage]||'mvp-section';
    for(const id of roots){const root=get(id);if(root)root.classList.toggle('screen-off',id!==active);}
    const parts={home:['dashboard-section'],notifications:['notifications-section'],documents:['documents-section'],certificates:['documents-section'],students:['staff-section'], 'staff-schedule':['staff-section']};
    for(const id of ['dashboard-section','notifications-section','documents-section','staff-section'])get(id)?.classList.toggle('screen-off',!(parts[page]||[]).includes(id));
    for(const node of document.querySelectorAll('[data-staff-part]'))node.classList.toggle('screen-off',node.dataset.staffPart!==(page==='students'?'students':'schedule'));
    get('mvp-document')?.classList.toggle('screen-off',!['documents','certificates'].includes(page));
    const title=pagesFor(role()).find(([id])=>id===visiblePage)?.[1]||'Вход в кабинет';
    get('page-title').textContent=t(visiblePage==='home'?'Мой учебный день':title);get('page-subtitle').textContent=new Date().toLocaleDateString(locale(),{timeZone:'Europe/Moscow',weekday:'long',day:'numeric',month:'long',year:'numeric'})+' · '+t('МСК');get('page-kicker').textContent=t(ready?(user.role==='staff'?'РАБОЧЕЕ МЕСТО ДЕКАНАТА':'СТУДЕНЧЕСКИЙ КАБИНЕТ'):'MGIMOv · КОНКУРСНЫЙ КОНЦЕПТ');
    const root=get(active);get('screen-loading').hidden=!ready||!root?.hidden;
    get('app-bottom').hidden=!ready;get('app-mobile-bar').hidden=!ready;get('app-search-area').hidden=!ready;
    document.documentElement.dataset.role=ready?user.role:'anonymous';
    navigation();
    if(typeof CustomEvent==='function')document.dispatchEvent?.(new CustomEvent('mgimov:page',{detail:visiblePage}));
  }
  function go(value,{focus=false,hash=true}={}){
    if(user)positions.set(user.id+':'+page,host.scrollY||0);
    page=normalized(value);get('app-mobile-menu').hidden=true;get('app-menu').setAttribute('aria-expanded','false');
    if(hash&&host.location&&host.location.hash!=='#'+page)host.location.hash=page;
    apply();
    if(focus){get('page-title').focus();host.scrollTo?.(0,user?positions.get(user.id+':'+page)||0:0);}
  }
  document.addEventListener('click',event=>{
    const link=event.target.closest?.('a[href^="#"]');if(!link)return;
    const value=link.getAttribute('href').slice(1);if(value==='main-content')return;
    if(Object.hasOwn(aliases,value)||pagesFor(role()).some(([id])=>id===value)){event.preventDefault();go(value,{focus:true});}
  });
  function setMenu(open){
    const menu=get('app-mobile-menu');menu.hidden=!open;get('app-menu').setAttribute('aria-expanded',String(open));
    if(open)menu.querySelector?.('[aria-current="page"], a')?.focus();
  }
  function dismissMenu(event){if(event.key==='Escape'&&!get('app-mobile-menu').hidden){event.preventDefault();setMenu(false);get('app-menu').focus();}}
  get('app-menu').addEventListener('click',()=>setMenu(get('app-mobile-menu').hidden));
  get('app-menu').addEventListener('keydown',dismissMenu);
  get('app-mobile-menu').addEventListener('keydown',dismissMenu);
  get('app-search').addEventListener('input',event=>{
    const value=event.target.value.trim().toLocaleLowerCase(locale());const target=get('app-search-results');target.replaceChildren();target.hidden=!value;
    for(const [key,label] of pagesFor(role()).filter(([,label])=>t(label).toLocaleLowerCase(locale()).includes(value))){const link=make('a',t(label));link.href='#'+key;link.className='nav-link';target.append(link);}
    if(value&&!target.children.length)target.append(make('p',t('Нет совпадений в доступных разделах.')));
  });
  host.addEventListener?.('hashchange',()=>{if(ready){routeFromLocation();setMenu(false);apply();}});
  function history(detail){
    const target=get('history-content');target.replaceChildren();
    if(!ready||user?.role!=='staff'||!detail){target.append(make('p',t('Выберите обращение в очереди, чтобы увидеть его историю. Это не общий журнал Staff.')));return;}
    target.append(make('h3',t('Обращение № ','Request #')+detail.id));
    const list=make('ol');list.className='request-history';for(const event of detail.history){const row=make('li');row.append(make('p',event.comment),make('small',`${event.actor_name||t('Автор')} · ${new Date(event.created_at*1000).toLocaleString(locale(),{timeZone:'Europe/Moscow'})} · ${t('МСК')}`));list.append(row);}target.append(list);
  }
  apply();
  return {
    go,refresh:apply,
    identity(value){
      ready=value.state==='ready';get('identity-status').textContent=ready?'':t(value.message||'');
      if(!ready){history(null);setMenu(false);get('app-search-results').replaceChildren();get('app-search-results').hidden=true;get('app-search').value='';}
      if(value.state==='anonymous'||value.state==='logout-pending'||(value.state==='loading'&&value.operation==='logout')||value.identityInvalidated){
        if(scopeKey&&!value.preserveRoute)replaceHash('');
        user=null;positions.clear();scopeKey='';page='profile';
      }
      if(ready){
        const key=value.user.id+':'+value.user.role;
        if(scopeKey!==key){
          positions.clear();history(null);
          if(scopeKey)replaceHash('');
          scopeKey=key;
        }
        user=value.user;routeFromLocation();get('app-account-link').textContent=value.profile.full_name;
      }
      else get('app-account-link').textContent=t('Аккаунт');
      apply();
    },
    requests(value){history(value.state==='ready'?value.detail:null);apply();}
  };
}
function shell(){if(!mounted&&typeof document!=='undefined'&&document.getElementById('app-sidebar'))mounted=mountShell(document);return mounted;}
export function shellIdentity(value){shell()?.identity(value);}
export function shellRefresh(){shell()?.refresh();}
export function shellRequests(value){shell()?.requests(value);}
export function navigate(page){shell()?.go(page,{focus:true});}
