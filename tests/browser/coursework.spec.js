import {expect,test as base} from '@playwright/test';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {createInterface} from 'node:readline';
import {fileURLToPath} from 'node:url';

const repo = fileURLToPath(new URL('../../', import.meta.url));
const python = fileURLToPath(new URL('../../.venv/Scripts/python.exe', import.meta.url));

const test=base.extend({coursework:async ({browser,request},use)=>{
  const child = spawn(python, ['-B','-m','tests.browser.coursework_server'], {
    cwd:repo, windowsHide:true, stdio:['pipe','pipe','ignore']
  });
  const lines = createInterface({input:child.stdout});
  const stop = once(child,'exit');
  const contexts=[];
  try {
    const [line] = await Promise.race([once(lines,'line'),stop.then(()=>{throw new Error('Coursework fixture startup failed');})]);
    const {origin,sessions,course,passwords} = JSON.parse(line);
    await expect.poll(async()=>{
      try {return (await request.get(origin+'/api/health',{timeout:1500})).status();} catch {return 0;}
    }).toBe(200);

    async function open(who,width,prepare=()=>{}) {
      const context=await browser.newContext({viewport:{width,height:844}});
      contexts.push(context);
      if(who)await context.addCookies(sessions[who]);
      const page=await context.newPage();
      await prepare(page);
      await page.goto(origin+'/#coursework');
      return page.locator('#coursework-section');
    }
    async function control(command) {
      const received=once(lines,'line');
      child.stdin.write(command+'\n');
      const [reply]=await received;
      expect(reply).toBe('ok');
    }
    async function login(page,who) {
      const token=await page.request.get(origin+'/api/v1/auth/csrf');
      expect(token.status()).toBe(200);
      const {csrf}=await token.json();
      const response=await page.request.post(origin+'/api/v1/auth/login',{
        headers:{Origin:origin,'X-CSRF-Token':csrf},
        data:{login:who,password:passwords[who]}
      });
      expect(response.status()).toBe(200);
      await page.locator('#account-check').click();
      await expect(page.locator('#profile-details')).toContainText(who);
    }
    await use({open,control,sessions,course,login});
  } finally {
    for(const context of contexts)await context.close();
    child.stdin.end();
    const timer=setTimeout(()=>child.kill(),5000);
    try{await stop;}finally{clearTimeout(timer);}
    lines.close();
  }
}});

async function createDraft(staff,title='Синтетическая работа',kind='lab') {
    await staff.getByRole('button',{name:'Создать черновик'}).click();
    await staff.getByLabel('Название').fill(title);
    await staff.getByLabel('Тип работы').selectOption(kind);
    await staff.getByLabel('Условия задания').fill('Проверьте сценарий');
    await staff.getByLabel('Срок (МСК)').fill('2027-02-21T12:00');
    await staff.getByRole('button',{name:'Сохранить черновик'}).click();
    await expect(staff.getByRole('heading',{name:title,exact:true})).toBeVisible();
}

test('coursework staff draft, publish, student Unicode submission, return and resubmit', async ({coursework:{open}}, info) => {
    const staff=await open('teacher',1280);
    await createDraft(staff);
    await staff.getByLabel('Название').fill('Уточнённая работа');
    await staff.getByRole('button',{name:'Сохранить черновик'}).click();
    await expect(staff.getByRole('heading',{name:'Уточнённая работа'})).toBeVisible();
    await staff.getByRole('button',{name:'Опубликовать задание'}).click();
    await expect(staff.getByRole('button',{name:'alice',exact:true})).toBeVisible();

    const student=await open('alice',390);
    await student.getByRole('button',{name:'Открыть задание'}).click();
    const stale=await open('alice',390);
    await stale.getByRole('button',{name:'Открыть задание'}).click();
    await stale.getByLabel('Текст работы').fill('Черновик из другой вкладки');
    await expect(student.locator('input[type=file]')).toHaveAttribute('accept','.txt,.md');
    await student.getByLabel('Текст работы').fill('Проверка 😀');
    await student.getByRole('button',{name:'Отправить работу'}).click();
    await expect(student.getByText('Проверка 😀',{exact:true})).toBeVisible();
    expect(await student.page().evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    await stale.getByRole('button',{name:'Отправить работу'}).click();
    await expect(stale.getByRole('status')).toHaveAttribute('data-state','conflict');
    await expect(stale.getByLabel('Текст работы')).toHaveValue('Черновик из другой вкладки');
    await expect(stale.getByRole('button',{name:'Отправить работу'})).toBeDisabled();
    await stale.screenshot({path:info.outputPath('coursework-conflict.png')});
    await stale.getByRole('button',{name:'Обновить',exact:true}).click();
    await expect(stale.getByText('Проверка 😀',{exact:true})).toBeVisible();
    await expect(stale.getByRole('button',{name:'Отправить работу'})).toHaveCount(0);

    await staff.getByRole('button',{name:'alice',exact:true}).click();
    await staff.getByLabel('Решение').selectOption('returned');
    await staff.getByLabel('Комментарий').fill('Уточните ответ');
    await staff.getByRole('button',{name:'Сохранить решение'}).click();
    await expect(staff.getByText('Уточните ответ',{exact:true})).toBeVisible();
    await staff.getByLabel('Решение').selectOption('retry_allowed');
    await staff.getByLabel('Комментарий').fill('Повторный ответ разрешён');
    await staff.getByLabel('Основание новой версии').fill('Уточнение решения');
    await staff.getByRole('button',{name:'Сохранить решение'}).click();
    await expect(staff.getByText(/Версия проверки 2/)).toBeVisible();
    await expect(staff.getByRole('button',{name:/Опубликовать баллы|Пересмотр деканатом/})).toHaveCount(0);
    await staff.screenshot({path:info.outputPath('staff-review.png')});

    await student.getByRole('button',{name:'Обновить',exact:true}).click();
    await student.getByLabel('Текст работы').fill('Исправлено 😀');
    await student.getByRole('button',{name:'Сдать повторно'}).click();
    await expect(student.getByText('Исправлено 😀',{exact:true})).toBeVisible();
    await student.screenshot({path:info.outputPath('student-history-mobile.png')});
    const outsider=await open('bobby',390);
    await expect(outsider.getByText('В этом списке пока нет работ.')).toBeVisible();
    await outsider.screenshot({path:info.outputPath('coursework-empty.png')});
});

for(const kind of ['lab','test']){
  test(`Coursework ${kind}: return an in-person attempt, resubmit text, review for points`, async ({coursework:{open}})=>{
    const staff=await open('teacher',1280);
    await createDraft(staff,'Смешанная работа',kind);
    await staff.getByLabel('Файлы материалов (TXT, MD)').setInputFiles({
      name:'guide.txt',mimeType:'text/plain',buffer:Buffer.from('Synthetic material')
    });
    await staff.getByRole('button',{name:'Добавить материалы'}).click();
    await expect(staff.getByRole('link',{name:'guide.txt'})).toBeVisible();
    await staff.getByLabel('Режим оценивания').selectOption('independent');
    await staff.getByLabel('Максимум баллов').fill('10');
    await staff.getByRole('button',{name:'Опубликовать задание'}).click();
    const recipient=staff.getByRole('button',{name:'alice',exact:true});
    await recipient.click();
    const record=staff.getByRole('button',{name:'Зарегистрировать очную сдачу'});
    await record.click();
    await expect(record).toHaveCount(0);
    await staff.getByLabel('Решение').selectOption('returned');
    await staff.getByLabel('Комментарий').fill('Дополните ответ');
    await staff.getByRole('button',{name:'Сохранить решение'}).click();
    await expect(record).toBeVisible();

    const student=await open('alice',390);
    await student.getByRole('button',{name:'Открыть задание'}).click();
    const material=student.getByRole('link',{name:'guide.txt'});
    await expect(material).toBeVisible();
    const [download]=await Promise.all([student.page().waitForEvent('download'),material.click()]);
    await expect(download.suggestedFilename()).toBe('guide.txt');
    await student.getByLabel('Текст работы').fill('Синтетический ответ');
    await student.getByLabel('Вложения к сдаче (TXT, MD)').setInputFiles({
      name:'answer.md',mimeType:'text/markdown',buffer:Buffer.from('Synthetic answer')
    });
    await student.getByRole('button',{name:'Сдать повторно'}).click();
    await expect(student.getByText('Синтетический ответ',{exact:true})).toBeVisible();
    await staff.getByRole('button',{name:'Обновить',exact:true}).click();
    await expect(staff.getByText('Синтетический ответ',{exact:true})).toBeVisible();
    await expect(staff.getByRole('link',{name:'answer.md'})).toBeVisible();
    await staff.getByLabel('Баллы',{exact:true}).fill('8');
    await staff.getByLabel('Комментарий').fill('Результат проверен');
    await staff.getByRole('button',{name:'Сохранить решение'}).click();
    await expect(staff.getByText('Результат проверен',{exact:true})).toBeVisible();
    await expect(record).toHaveCount(0);
    await student.getByRole('button',{name:'Обновить',exact:true}).click();
    await expect(student.getByText('Результат проверен',{exact:true})).toBeVisible();
    await expect(student.getByText('Дополните ответ',{exact:true})).toBeVisible();
    await expect(student.getByText('Баллы · 8',{exact:true})).toBeVisible();
    const outsider=await open('bobby',390);
    await expect(outsider.getByText('В этом списке пока нет работ.')).toBeVisible();
  });
}

test('Staff publishes and corrects a reviewed Coursework score in BRS explicitly', async ({coursework:{open}})=>{
  const staff=await open('teacher',1280);
  await createDraft(staff,'Контрольная с БРС','test');
  await staff.getByLabel('Режим оценивания').selectOption('brs');
  await staff.getByLabel('Код мероприятия БРС').fill('e');
  await staff.getByRole('button',{name:'Опубликовать задание'}).click();
  const student=await open('alice',390);
  await student.getByRole('button',{name:'Открыть задание'}).click();
  await student.getByLabel('Текст работы').fill('Тестовый ответ БРС');
  await student.getByRole('button',{name:'Отправить работу'}).click();
  await expect(student.getByText('Тестовый ответ БРС',{exact:true})).toBeVisible();

  await staff.getByRole('button',{name:'Обновить',exact:true}).click();
  await staff.getByRole('button',{name:'alice',exact:true}).click();
  const publish=staff.getByRole('button',{name:'Опубликовать баллы в БРС'});
  await staff.getByLabel('Баллы',{exact:true}).fill('8');
  await staff.getByLabel('Комментарий').fill('Проверено');
  await staff.getByRole('button',{name:'Сохранить решение'}).click();
  await expect(publish).toBeVisible();
  await expect(staff.getByText(/БРС · попытка 1 · версия 1/)).toHaveCount(0);
  await publish.click();
  await expect(staff.getByText('БРС · попытка 1 · версия 1 · баллы 8',{exact:true})).toBeVisible();
  await expect(publish).toHaveCount(0);
  await staff.getByLabel('Баллы',{exact:true}).fill('7');
  await staff.getByLabel('Комментарий').fill('Уточнённый результат');
  await staff.getByLabel('Основание новой версии').fill('Пересчитан критерий');
  await staff.getByRole('button',{name:'Сохранить решение'}).click();
  await publish.click();
  await expect(staff.getByText('БРС · попытка 1 · версия 2 · баллы 7',{exact:true})).toBeVisible();
  await student.getByRole('button',{name:'Обновить',exact:true}).click();
  await expect(student.getByText('БРС · попытка 1 · версия 1 · баллы 8',{exact:true})).toBeVisible();
  await expect(student.getByText('БРС · попытка 1 · версия 2 · баллы 7',{exact:true})).toBeVisible();
});

async function observeSubmissionCompletion(page) {
  await page.route('**/js/coursework.js',async route=>{
    const response=await route.fetch();
    let source=await response.text();
    const end='\n    }\n  }\n  function metadata(parent,work)';
    if(source.split(end).length!==2)throw new Error('Cannot instrument Coursework mutation completion');
    // The browser receives a disposable copy. The marker runs at the end of the actual finally block.
    source=source.replace(end,"\n      if(endpoint.endsWith('/submissions')) document.dispatchEvent(new Event('test:coursework-mutation-complete'));"+end);
    if(process.env.MGIMOV_COURSEWORK_MUTATION==='1'){
      const guard='||session!==sessionEpoch';
      if(source.split(guard).length!==2)throw new Error('Cannot remove session guard from disposable copy');
      source=source.replace(guard,'');
    }
    await route.fulfill({response,body:source});
  });
}

function holdWrite(page, url, beforeFetch=()=>{}) {
  let entered, release, delivered;
  const started=new Promise(resolve=>{entered=resolve;});
  const gate=new Promise(resolve=>{release=resolve;});
  const finished=new Promise(resolve=>{delivered=resolve;});
  const handler=async route=>{
    if(!['POST','PATCH'].includes(route.request().method()))return route.continue();
    await beforeFetch();
    const response=await route.fetch();
    entered({status:response.status(),key:route.request().postDataJSON().request_key});
    await gate;
    await route.fulfill({response});
    delivered();
  };
  const installed=page.route(url,handler);
  return {installed,started,release,finished,remove:()=>page.unroute(url,handler)};
}

test('Coursework filters keep keyboard focus at 390, 768 and 1280 px',async ({coursework:{open,control}},info)=>{
  await control('separate-student-works');
  await control('long-coursework-title');
  for(const width of [390,768,1280]){
    const panel=await open('alice',width);
    const page=panel.page();
    const refresh=panel.getByRole('button',{name:'Обновить',exact:true});
    const semester=panel.getByLabel('Семестр');
    const subject=panel.getByLabel('Дисциплина');
    await expect(panel.getByRole('heading',{name:/ДлинноеНазваниеУчебнойРаботы/})).toBeVisible();
    await refresh.focus();
    await page.keyboard.press('Tab');
    await expect(semester).toBeFocused();
    const original=await semester.elementHandle();
    const before=await page.evaluate(()=>window.scrollY);
    await page.keyboard.press('ArrowDown');
    await expect(semester).toHaveValue('s');
    expect(await original.evaluate(el=>el===document.activeElement)).toBe(true);
    expect(await page.evaluate(()=>window.scrollY)).toBe(before);
    await page.keyboard.press('Tab');
    await expect(subject).toBeFocused();
    await page.keyboard.press('ArrowDown');
    await expect(subject).toHaveValue('Math');
    await expect(subject).toBeFocused();
    await page.keyboard.press('Shift+Tab');
    await expect(semester).toBeFocused();
    await expect(semester).toHaveValue('s');
    await expect(subject).toHaveValue('Math');
    await expect(panel.getByRole('button',{name:'Открыть задание'})).toHaveCount(1);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await panel.screenshot({path:info.outputPath('student-filters-'+width+'.png')});

    if(width===390){
      // A controlled transport failure exercises the real UI error and retry path.
      let release;
      const held=new Promise(resolve=>{release=resolve;});
      await page.route('**/api/v1/me/coursework',async route=>{
        await held;
        await route.abort('connectionfailed');
      },{times:1});
      try{
        await refresh.click();
        await expect(panel.getByRole('status')).toHaveAttribute('data-state','loading');
        await panel.screenshot({path:info.outputPath('coursework-loading.png')});
      }finally{release();}
      await expect(panel.getByRole('status')).toHaveAttribute('data-state','error');
      await panel.screenshot({path:info.outputPath('coursework-error.png')});
      await refresh.click();
      await expect(panel.getByRole('heading',{name:/ДлинноеНазваниеУчебнойРаботы/})).toBeVisible();
    }
  }
});

async function navigate(page,hash,selector) {
  await page.evaluate(value=>{location.hash=value;},hash);
  await expect(page.locator(selector)).toBeVisible();
}

async function assertAnonymous(page) {
  await expect(page.locator('#login-form')).toBeVisible();
  await expect(page.locator('#account-panel')).toBeHidden();
  for(const id of ['profile-details','schedule-days','academics-content','requests-content','attestations-content',
    'mvp-content','mvp-document','coursework-content']){
    await expect(page.locator('#'+id)).toBeEmpty();
  }
  await expect(page.locator('#app-mobile-bar')).toBeHidden();
}

test('real 401 clears Student and Staff from other screens; tablet navigation smoke',async ({coursework:{open,control,course}},info)=>{
  const staff=await open('teacher',1280);
  await createDraft(staff);
  await staff.getByRole('button',{name:'Опубликовать задание'}).click();
  await expect(staff.getByRole('button',{name:'alice',exact:true})).toBeVisible();
  // A second draft provides a valid protected Staff mutation to receive the 401.
  await staff.getByRole('button',{name:'Вернуться к списку'}).click();
  await createDraft(staff,'Черновик для проверки сессии');
  const student=await open('alice',768);
  const studentPage=student.page();
  for(const [hash,selector] of [['home','#dashboard-section'],['schedule','#schedule-section'],
    ['academics','#academics-section'],['attestations','#attestations-section'],
    ['profile','#profile-section'],['settings','#settings-section']]){
    await navigate(studentPage,hash,selector);
  }
  expect(await studentPage.evaluate(async id=>(await fetch('/api/v1/me/brs/courses/'+id+'/results')).status,course)).toBe(200);
  await navigate(studentPage,'coursework','#coursework-section');
  await student.getByRole('button',{name:'Открыть задание'}).click();
  await student.getByLabel('Текст работы').fill('Ввод до истечения сессии');
  expect(await studentPage.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(768);
  await student.screenshot({path:info.outputPath('student-tablet.png')});
  for(const [who,panel,pattern,button] of [
    ['alice',student,'**/submissions','Отправить работу'],
    ['teacher',staff,'**/api/v1/staff/coursework/*','Сохранить черновик'],
  ]){
    const page=panel.page();
    await control('expire:'+who);
    const held=holdWrite(page,pattern);
    await held.installed;
    try{
      await panel.getByRole('button',{name:button,exact:true}).click();
      expect((await held.started).status).toBe(401);
      await navigate(page,'profile','#profile-section');
      await expect(page.locator('#profile-details')).toContainText(who);
    }finally{held.release();}
    await assertAnonymous(page);
    await expect(page.locator('#account-message')).toContainText('Сессия завершена');
  }
});

test('late server 401 from Student A preserves Student B, draft and request isolation',async ({coursework:{open,control,login}},info)=>{
  await control('separate-student-works');
  const panel=await open(null,390,observeSubmissionCompletion);
  const page=panel.page();
  const oldTitle='Работа только Alice', oldDraft='Черновик только Alice';
  const newTitle='Работа только Bobby', newDraft='Ответ только Bobby 😀';

  await login(page,'alice');
  await navigate(page,'coursework','#coursework-section');
  await expect(panel.getByRole('heading',{name:oldTitle,exact:true})).toBeVisible();
  await panel.getByRole('button',{name:'Открыть задание'}).click();
  await panel.getByLabel('Текст работы').fill(oldDraft);
  const old=holdWrite(page,'**/submissions',()=>control('expire:alice'));
  await old.installed;
  try{
    await panel.getByRole('button',{name:'Отправить работу',exact:true}).click();
    const rejected=await old.started;
    expect(rejected.status).toBe(401);
    await navigate(page,'settings','#settings-section');
    await page.locator('#logout').click();
    await assertAnonymous(page);

    await login(page,'bobby');
    await navigate(page,'coursework','#coursework-section');
    await expect(panel.getByRole('heading',{name:newTitle,exact:true})).toBeVisible();
    await panel.getByRole('button',{name:'Открыть задание'}).click();
    await expect(panel.getByLabel('Текст работы')).toHaveValue('');
    await panel.getByLabel('Текст работы').fill(newDraft);

    await page.evaluate(()=>{
      window.courseworkMutationCompleted=false;
      document.addEventListener('test:coursework-mutation-complete',()=>{
        window.courseworkMutationCompleted=true;
      },{once:true});
    });
    old.release();
    await old.finished;
    await page.waitForFunction(()=>window.courseworkMutationCompleted===true);
    await old.remove();
    await expect(page.locator('html')).toHaveAttribute('data-role','student');
    await expect(page.locator('#app-account-link')).toHaveText('bobby');
    await expect(page.locator('#login-form')).toBeHidden();
    await expect(panel.getByLabel('Текст работы')).toHaveValue(newDraft);
    await expect(page.locator('body')).not.toContainText(oldTitle);
    await expect(page.locator('body')).not.toContainText(oldDraft);

    const next=holdWrite(page,'**/submissions');
    await next.installed;
    try{
      await panel.getByRole('button',{name:'Отправить работу',exact:true}).click();
      const submitted=await next.started;
      expect(submitted.status).toBe(201);
      expect(submitted.key).toMatch(/^[A-Za-z0-9_-]{16,64}$/);
      expect(rejected.key).toMatch(/^[A-Za-z0-9_-]{16,64}$/);
      expect(submitted.key).not.toBe(rejected.key);
    }finally{next.release();}
    await next.finished;
    await next.remove();
    await expect(panel.getByText(newDraft,{exact:true})).toBeVisible();
    await expect(page.locator('body')).not.toContainText(oldDraft);
    await panel.screenshot({path:info.outputPath('student-b-after-late-401.png')});
  }finally{old.release();}
});

test('logout and account switch discard late success; server role switch clears draft',async ({coursework:{open,control,sessions}})=>{
  const staff=await open('teacher',1280);
  await createDraft(staff);
  const page=staff.page();
  const first=holdWrite(page,'**/api/v1/staff/coursework/*');
  await first.installed;
  await staff.getByLabel('Название').fill('Текст старого аккаунта');
  try{
    await staff.getByRole('button',{name:'Сохранить черновик',exact:true}).click();
    expect((await first.started).status).toBe(200);
    await navigate(page,'settings','#settings-section');
    await page.locator('#logout').click();
    await assertAnonymous(page);
    await page.context().addCookies(sessions.bobby);
    await page.locator('#account-check').click();
    await expect(page.locator('#profile-details')).toContainText('bobby');
    first.release();
    await first.finished;
    await first.remove();
    await navigate(page,'coursework','#coursework-section');
    await expect(staff.getByText('В этом списке пока нет работ.')).toBeVisible();
    await expect(staff.getByText('Текст старого аккаунта')).toHaveCount(0);
    await expect(staff.locator('form')).toHaveCount(0);
  }finally{first.release();}

  // Restore the isolated Staff fixture session for the separate role-change scenario.
  await control('renew:teacher');
  const teacher=await open('teacher',1280);
  await teacher.getByRole('button',{name:'Открыть задание'}).click();
  const second=holdWrite(teacher.page(),'**/api/v1/staff/coursework/*');
  await second.installed;
  try{
    await teacher.getByLabel('Название').fill('Новая команда');
    await teacher.getByRole('button',{name:'Сохранить черновик',exact:true}).click();
    const saved=await second.started;
    expect(saved.status).toBe(200);
    expect(saved.key).not.toBe((await first.started).key);
  }finally{second.release();}
  await second.finished;
  await second.remove();
  await expect(teacher.getByRole('heading',{name:'Новая команда',exact:true})).toBeVisible();
  await teacher.getByLabel('Название').fill('Черновик прежней роли');
  await control('role:teacher');
  await navigate(teacher.page(),'profile','#profile-section');
  await teacher.page().locator('#account-check').click();
  await expect(teacher.page().locator('html')).toHaveAttribute('data-role','student');
  await navigate(teacher.page(),'coursework','#coursework-section');
  await expect(teacher.getByText('В этом списке пока нет работ.')).toBeVisible();
  await expect(teacher.locator('form')).toHaveCount(0);
  await expect(teacher.getByText('Черновик прежней роли')).toHaveCount(0);
});
