import {test,expect} from '@playwright/test';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {createInterface} from 'node:readline';
import {fileURLToPath} from 'node:url';

test('QR attendance: Staff issue, Student confirmation, manual priority, expiry and revocation',async({browser,request},info)=>{
 const child=spawn(fileURLToPath(new URL('../../.venv/Scripts/python.exe',import.meta.url)),['-B','-m','tests.browser.attendance_qr_server'],{cwd:fileURLToPath(new URL('../../',import.meta.url)),windowsHide:true,stdio:['pipe','pipe','pipe']});
 let diagnostics='';child.stderr.on('data',chunk=>diagnostics+=chunk.toString());
 const lines=createInterface({input:child.stdout}),stop=once(child,'exit'),contexts=[];
 try{
  const [line]=await Promise.race([once(lines,'line'),stop.then(()=>{throw Error('QR fixture failed: '+diagnostics);})]);
  const {origin,sessions}=JSON.parse(line);
  await expect.poll(async()=>{try{return(await request.get(origin+'/api/health')).status();}catch{return 0;}}).toBe(200);
  async function open(who,width,url=origin+'/#staff-schedule'){
   const context=await browser.newContext({viewport:{width,height:844}});contexts.push(context);await context.addCookies(sessions[who]);const page=await context.newPage();
   if(who==='alice')await page.route('**/api/v1/me/attendance/qr/preview',route=>route.abort(),{times:1});
   await page.goto(url);return page;
  }
  const staff=await open('teacher',1280);await staff.locator('#staff-section [data-attendance="l"]').click();
  const journal=staff.locator('#attendance-dialog');await journal.getByLabel('Причина').fill('Состав проверен для QR');await journal.getByRole('button',{name:'Сохранить',exact:true}).click();
  async function issue(){
   await journal.getByRole('button',{name:'QR-посещаемость',exact:true}).click();
   const response=staff.waitForResponse(r=>r.url().endsWith('/attendance/lessons/l/qr')&&r.request().method()==='POST');
   await staff.locator('#attendance-qr-dialog').getByRole('button',{name:'Выпустить QR',exact:true}).click();
   const result=await response;expect(result.status()).toBe(200);const data=await result.json();
   await expect(staff.locator('#attendance-qr-content svg')).toBeVisible();return data;
  }
  async function reopenJournal(){await staff.locator('#attendance-qr-close').click();await staff.locator('#staff-section [data-attendance="l"]').click();}
  const first=await issue();
  const student=await open('alice',390,first.url),own=student.locator('#attendance-qr-dialog');
  await own.getByRole('button',{name:'Повторить',exact:true}).click();
  await expect(own.getByRole('button',{name:'Подтвердить посещение'})).toBeVisible();
  expect(await student.evaluate(()=>!location.hash.startsWith('#attendance-qr='))).toBe(true);
  await own.getByRole('button',{name:'Подтвердить посещение'}).dblclick();
  await expect(own.getByRole('status')).toHaveText('Посещение подтверждено: Присутствовал.');
  expect(await student.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await student.screenshot({path:info.outputPath('qr-student-confirmed-390.png')});
  const other=await open('bobby',390,first.url);await expect(other.locator('#attendance-qr-status')).toContainText('QR недоступен.');
  await expect(other.locator('#attendance-qr-content')).not.toContainText('Math');
  await reopenJournal();await expect(journal.locator('p').filter({hasText:/^Присутствовал$/})).toBeVisible();
  await journal.getByLabel('Статус').selectOption('absent');await journal.getByLabel('Причина').fill('Ручное уточнение преподавателя');await journal.getByRole('button',{name:'Сохранить',exact:true}).click();
  // Replay the original receipt: its historical outcome remains present, current status is absent.
  await student.goto(first.url);
  const replayResponse=student.waitForResponse(r=>r.url().endsWith('/attendance/qr/check-in'));
  await own.getByRole('button',{name:'Подтвердить посещение'}).click();
  const replay=await (await replayResponse).json();expect(replay.status).toBe('absent');expect(replay.outcome).toBe('present');expect(replay.manual_mark).toBe(true);
  await expect(own.getByRole('status')).toHaveText('Текущий статус: Отсутствовал. QR не изменил ручную отметку.');
  const second=await issue();await student.goto(second.url);await own.getByRole('button',{name:'Подтвердить посещение'}).click();
  await expect(own.getByRole('status')).toHaveText('Текущий статус: Отсутствовал. QR не изменил ручную отметку.');
  await staff.locator('#attendance-qr-dialog').getByRole('button',{name:'Отозвать QR',exact:true}).click();await expect(staff.locator('#attendance-qr-content svg')).toHaveCount(0);
  await staff.screenshot({path:info.outputPath('qr-staff-revoked-1280.png')});
  await student.goto(second.url);await expect(student.locator('#attendance-qr-status')).toContainText('QR истёк');
  await reopenJournal();const third=await issue();const control=once(lines,'line');child.stdin.write('expire\n');expect((await control)[0]).toBe('ok');
  await student.goto(third.url);await expect(student.locator('#attendance-qr-status')).toContainText('QR истёк');
  // Close the modal before interacting with the page; do not wait for the minute identity poll.
  await staff.locator('#attendance-qr-close').click();
  const languageSaved=staff.waitForResponse(r=>r.url().endsWith('/me/language')&&r.request().method()==='POST');
  await staff.locator('#language-toggle').click();await languageSaved;
  await staff.locator('#staff-section [data-attendance="l"]').click();
  await journal.getByRole('button',{name:'QR attendance',exact:true}).click();
  const english=staff.locator('#attendance-qr-dialog');
  const englishResponse=staff.waitForResponse(r=>r.url().endsWith('/attendance/lessons/l/qr'));
  await english.getByRole('button',{name:'Issue QR',exact:true}).click();const englishCode=await (await englishResponse).json();
  await expect(english.getByRole('status')).toContainText('QR issued.');
  await student.locator('#attendance-qr-close').click();
  const studentLanguage=student.waitForResponse(r=>r.url().endsWith('/me/language')&&r.request().method()==='POST');
  await student.locator('#language-toggle').click();await studentLanguage;
  await student.goto(englishCode.url);await own.getByRole('button',{name:'Confirm attendance',exact:true}).click();
  await expect(own.getByRole('status')).toHaveText('Current status: Absent. The QR did not change the teacher’s manual mark.');
  await english.getByRole('button',{name:'Revoke QR',exact:true}).click();await expect(english.getByRole('status')).toHaveText('QR revoked.');
 }finally{
  try{for(const context of contexts)await context.close();}finally{child.stdin.end();const timer=setTimeout(()=>child.kill(),5000);try{await stop;}finally{clearTimeout(timer);lines.close();}}
 }
});
