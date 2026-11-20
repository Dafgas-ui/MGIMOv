import {test,expect} from '@playwright/test';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {createInterface} from 'node:readline';
import {fileURLToPath} from 'node:url';

test('Final generator: real login, calculator, rooms, Coursework, QR and isolation',async({browser,request},info)=>{
 test.setTimeout(240_000); // Includes private Windows ACL verification and 20 real password hashes.
 const child=spawn(fileURLToPath(new URL('../../.venv/Scripts/python.exe',import.meta.url)),
  ['-B','-m','tests.browser.contest_final_server'],{cwd:fileURLToPath(new URL('../../',import.meta.url)),windowsHide:true,stdio:['pipe','pipe','pipe']});
 const lines=createInterface({input:child.stdout}),stop=once(child,'exit'),contexts=[];
 let diagnostics='';child.stderr.on('data',chunk=>diagnostics+=chunk.toString());
 try{
  const [line]=await Promise.race([once(lines,'line'),stop.then(()=>{throw Error('Final fixture failed: '+diagnostics);})]);
  const {origin,passwords,lesson,summary}=JSON.parse(line);
  console.log('Final fixture generated:',summary);
  expect(summary).toMatchObject({students:11,staff:9,rooms:51,migrations:26});
  await expect.poll(async()=>{try{return(await request.get(origin+'/api/health',{timeout:2000})).status();}catch{return 0;}}).toBe(200);
  async function open(account,width){
   const context=await browser.newContext({viewport:{width,height:844}});contexts.push(context);
   const page=await context.newPage();page.setDefaultTimeout(15_000);
   const bootstrap=await context.request.get(origin+'/api/v1/auth/csrf');expect(bootstrap.status()).toBe(200);
   const login=await context.request.post(origin+'/api/v1/auth/login',{headers:{Origin:origin,'X-CSRF-Token':(await bootstrap.json()).csrf},data:{login:account,password:passwords[account]}});
   expect(login.status()).toBe(200);expect((await login.json()).user.id).toBe(account);
   await page.goto(origin+'/#coursework');return page;
  }
  const student=await open('s07',390),staff=await open('t01',1280),other=await open('s02',390);
  console.log('Final HTTP logins: Student, Staff, second Student accepted');
  await expect(student.locator('#coursework-section')).toContainText('Практика A');
  await expect(other.locator('#coursework-section')).toContainText('Практика B');
  await expect(other.locator('#coursework-section')).not.toContainText('Практика A');
  console.log('Final Coursework isolation accepted');
  await student.goto(origin+'/#academics');
  const calculator=student.locator('#forecast-panel .brs-calculator-summary').first();await calculator.click();
  await expect(student.locator('.brs-calculator-results').first()).toBeVisible();
  console.log('Final calculator visible');
  await student.goto(origin+'/#rooms');
  const form=student.locator('#rooms-form');await form.locator('[name=date]').fill('2026-11-21');
  await form.locator('[name=start]').fill('09:00');await form.locator('[name=end]').fill('10:00');
  await student.locator('#rooms-submit').click();
  await expect(student.locator('#rooms-status')).toContainText('Найдено аудиторий');
  await expect(student.locator('#rooms-results')).toContainText('Режим доступа не подтверждён');
  expect(await student.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await student.screenshot({path:info.outputPath('final-rooms-student-390.png')});
  console.log('Final rooms mobile accepted');
  // Teachers have lesson-specific attendance access, not deanery-wide timetable rights.
  await staff.locator('#attendance-open').click();
  const journal=staff.locator('#attendance-dialog');
  await journal.locator('article').filter({hasText:'Демонстрационное право'}).filter({hasText:'ДЕМО-А'})
   .getByRole('button',{name:'Журнал занятия',exact:true}).click();
  await journal.getByRole('button',{name:'QR-посещаемость',exact:true}).click();
  const issued=staff.waitForResponse(r=>r.url().endsWith(`/attendance/lessons/${lesson}/qr`)&&r.request().method()==='POST');
  await staff.locator('#attendance-qr-dialog').getByRole('button',{name:'Выпустить QR',exact:true}).click();
  const response=await issued;expect(response.status()).toBe(200);const qr=await response.json();
  await student.goto(qr.url);const dialog=student.locator('#attendance-qr-dialog');
  await dialog.getByRole('button',{name:'Подтвердить посещение'}).click();
  await expect(dialog.getByRole('status')).toHaveText('Посещение подтверждено: Присутствовал.');
  await student.screenshot({path:info.outputPath('final-qr-student-390.png')});
  await other.goto(qr.url);await expect(other.locator('#attendance-qr-status')).toContainText('QR недоступен');
  const own=await student.request.get(origin+`/api/v1/me/attendance/lessons/${lesson}`);expect(own.status()).toBe(200);expect((await own.json()).status).toBe('present');
  expect((await other.request.get(origin+`/api/v1/me/attendance/lessons/${lesson}`)).status()).toBe(404);
 }finally{
  try{for(const context of contexts)await context.close();}finally{
   child.stdin.end();
   const timer=setTimeout(()=>child.kill(),10000);try{await stop;}finally{clearTimeout(timer);lines.close();}
  }
 }
});
