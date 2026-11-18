import {test,expect} from '@playwright/test';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {createInterface} from 'node:readline';
import {fileURLToPath} from 'node:url';

test('Attendance: confirmed roster, unmarked, correction, Student privacy and mobile',async({browser,request},info)=>{
  const repo=fileURLToPath(new URL('../../',import.meta.url));
  const python=fileURLToPath(new URL('../../.venv/Scripts/python.exe',import.meta.url));
  const child=spawn(python,['-B','-m','tests.browser.attendance_server'],{cwd:repo,windowsHide:true,stdio:['pipe','pipe','ignore']});
  const lines=createInterface({input:child.stdout}),stop=once(child,'exit'),contexts=[];
  try{
    const [line]=await Promise.race([once(lines,'line'),stop.then(()=>{throw new Error('Attendance fixture failed');})]);
    const {origin,sessions}=JSON.parse(line);
    await expect.poll(async()=>{try{return(await request.get(origin+'/api/health')).status();}catch{return 0;}}).toBe(200);
    async function open(who,width,hash){
      const context=await browser.newContext({viewport:{width,height:844}});contexts.push(context);
      await context.addCookies(sessions[who]);const page=await context.newPage();
      await page.goto(origin+'/#'+hash);await expect(page.locator('#attendance-open')).toBeVisible();return page;
    }
    const teacher=await open('teacher',1280,'staff-schedule');
    await teacher.locator('#staff-section [data-attendance="l"]').click();
    const dialog=teacher.getByRole('dialog');
    await expect(dialog.getByText('Проверьте датированный состав перед подтверждением.')).toBeVisible();
    await dialog.getByLabel('Причина').fill('Преподаватель сверил состав');
    await dialog.getByRole('button',{name:'Сохранить'}).click();
    await expect(dialog.locator('p').filter({hasText:/^Не отмечено$/})).toBeVisible();
    const student=await open('alice',390,'schedule');
    await student.locator('#schedule-date').fill('2027-03-01');
    await student.locator('#schedule-date').dispatchEvent('change');
    await student.locator('#schedule-days [data-attendance="l"]').click();
    const own=student.getByRole('dialog');
    await expect(own.getByText('Не отмечено',{exact:true})).toBeVisible();
    await own.getByRole('button',{name:'Закрыть журнал'}).click();
    await dialog.getByLabel('Статус').selectOption('present');
    await dialog.getByLabel('Причина').fill('Присутствие на занятии');
    await dialog.getByRole('button',{name:'Сохранить'}).click();
    await expect(dialog.locator('p').filter({hasText:/^Присутствовал$/})).toBeVisible();
    await dialog.getByLabel('Статус').selectOption('late');
    await dialog.getByLabel('Причина').fill('Уточнено время прихода');
    await dialog.getByRole('button',{name:'Сохранить'}).click();
    await expect(dialog.locator('p').filter({hasText:/^Опоздал$/})).toBeVisible();
    await dialog.getByLabel('Статус').selectOption('absent');
    await dialog.getByLabel('Причина').fill('Несохранённое уточнение');
    const endpoint=origin+'/api/v1/staff/attendance/lessons/l';
    await teacher.route(endpoint,route=>route.abort('connectionfailed'),{times:1});
    await dialog.getByRole('button',{name:'Сохранить'}).click();
    await expect(dialog.locator('#attendance-status')).toContainText('Не удалось загрузить посещаемость.');
    await expect(dialog.getByLabel('Причина')).toHaveValue('Несохранённое уточнение');
    await expect(dialog.getByLabel('Статус')).toHaveValue('absent');
    await dialog.getByRole('button',{name:'К списку занятий'}).click();
    const card=name=>dialog.locator('article').filter({has:teacher.getByRole('heading',{name,exact:true})});
    await card('2027-03-01 · Law · A · Teacher').getByRole('button',{name:'Журнал занятия'}).click();
    await expect(dialog.getByLabel('Причина')).toHaveCount(0);
    await expect(dialog.getByText('Несохранённое уточнение',{exact:true})).toHaveCount(0);
    await dialog.getByRole('button',{name:'К списку занятий'}).click();
    await card('2027-03-01 · Math · A · Teacher').getByRole('button',{name:'Журнал занятия'}).click();
    await expect(dialog.getByLabel('Причина')).toHaveValue('Несохранённое уточнение');
    await dialog.getByRole('button',{name:'Закрыть журнал'}).click();
    await teacher.locator('#staff-section [data-attendance="l"]').click();
    await expect(dialog.getByLabel('Причина')).toHaveValue('Несохранённое уточнение');
    await expect(dialog.getByLabel('Статус')).toHaveValue('absent');

    // A second real Staff session changes the same journal through the UI.
    const concurrent=await open('teacher',1280,'staff-schedule');
    await concurrent.locator('#staff-section [data-attendance="l"]').click();
    const competing=concurrent.getByRole('dialog');
    await competing.getByLabel('Статус').selectOption('present');
    await competing.getByLabel('Причина').fill('Параллельное уточнение');
    await competing.getByRole('button',{name:'Сохранить'}).click();
    await expect(competing.locator('p').filter({hasText:/^Присутствовал$/})).toBeVisible();
    await dialog.getByRole('button',{name:'Сохранить'}).click();
    await expect(dialog.locator('#attendance-status')).toContainText('Обновите данные');
    await expect(dialog.getByLabel('Причина')).toHaveValue('Несохранённое уточнение');
    await expect(dialog.getByRole('button',{name:'Сохранить',exact:true})).toBeDisabled();
    await dialog.getByRole('button',{name:'Обновить',exact:true}).click();
    await expect(dialog.getByRole('button',{name:'Применить черновик к обновлённой версии'})).toBeEnabled();
    await expect(dialog.getByLabel('Статус')).toHaveValue('absent');
    const beforeAdopt=(await (await teacher.request.get(endpoint)).json()).version;
    await dialog.getByRole('button',{name:'Применить черновик к обновлённой версии'}).click();
    expect((await (await teacher.request.get(endpoint)).json()).version).toBe(beforeAdopt);
    await dialog.getByRole('button',{name:'Сохранить',exact:true}).click();
    await expect(dialog.locator('p').filter({hasText:/^Отсутствовал$/})).toBeVisible();
    await expect(dialog.getByLabel('Причина')).toHaveValue('');
    await dialog.getByText('История посещаемости',{exact:true}).click();
    await expect(dialog.getByText(/Присутствовал → Опоздал/)).toBeVisible();
    await teacher.screenshot({path:info.outputPath('attendance-staff-1280.png')});
    await student.locator('#attendance-open').click();
    await expect(own.getByText('Отсутствовал',{exact:true})).toBeVisible();
    await expect(own.getByRole('button',{name:'Сохранить'})).toHaveCount(0);
    await own.getByText('История посещаемости',{exact:true}).click();
    await expect(own.getByText(/Уточнено время прихода/)).toBeVisible();
    expect(await own.evaluate(e=>e.scrollWidth<=e.clientWidth+1)).toBe(true);
    await student.screenshot({path:info.outputPath('attendance-student-390.png')});
    const other=await open('bobby',390,'schedule');
    await other.locator('#attendance-open').click();
    await expect(other.getByRole('dialog').getByText('Подтверждённых ведомостей пока нет.')).toBeVisible();
    expect((await other.request.get(origin+'/api/v1/me/attendance/lessons/l')).status()).toBe(404);
  }finally{
    try{
      for(const context of contexts)await context.close();
    }finally{
      child.stdin.end();const timer=setTimeout(()=>child.kill(),5000);
      try{await stop;}finally{clearTimeout(timer);lines.close();}
    }
  }
});
