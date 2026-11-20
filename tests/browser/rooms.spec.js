import {test,expect} from '@playwright/test';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {createInterface} from 'node:readline';
import {fileURLToPath} from 'node:url';

test('rooms: actual HTTP, known/unknown rules, filters, keyboard and mobile RU/EN',async({browser,request},info)=>{
 const child=spawn(fileURLToPath(new URL('../../.venv/Scripts/python.exe',import.meta.url)),['-B','-m','tests.browser.rooms_server'],{cwd:fileURLToPath(new URL('../../',import.meta.url)),windowsHide:true,stdio:['pipe','pipe','pipe']});
 let diagnostic='';child.stderr.on('data',data=>diagnostic+=data.toString());
 const lines=createInterface({input:child.stdout}),stop=once(child,'exit'),contexts=[];
 try{
  const [line]=await Promise.race([once(lines,'line'),stop.then(()=>{throw Error('Fixture failed: '+diagnostic);})]);
  const {origin,sessions}=JSON.parse(line);
  await expect.poll(async()=>{try{return(await request.get(origin+'/api/health')).status();}catch{return 0;}}).toBe(200);
  for(const [who,width] of [['alice',390],['bobby',768]]){
   const context=await browser.newContext({viewport:{width,height:844}});contexts.push(context);await context.addCookies(sessions[who]);
   const page=await context.newPage();await page.goto(origin+'/#rooms');const root=page.locator('#rooms-section');
   await expect(root).toBeVisible();await expect(root.locator('select option')).toHaveCount(3);
   await root.locator('[name=date]').fill('2027-03-01');await root.locator('[name=start]').fill('10:00');await root.locator('[name=end]').fill('10:30');
   await root.locator('[name=capacity]').focus();await page.keyboard.press('Tab');await expect(root.locator('button')).toBeFocused();
   await page.keyboard.press('Enter');await expect(root.locator('article')).toHaveCount(3);
   await expect(root.getByRole('status')).toHaveText('Найдено аудиторий: 3. Режим доступа не подтверждён: 1.');
   await expect(root.getByRole('status')).toHaveAttribute('aria-live','polite');
   await expect(root.getByRole('heading',{name:'Режим доступа не подтверждён',exact:true})).toBeVisible();
   expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
   await page.screenshot({path:info.outputPath('rooms-'+width+'.png')});
   await root.locator('[name=capacity]').fill('50');await root.locator('button').click();await expect(root.locator('article')).toHaveCount(1);
   await root.locator('[name=capacity]').fill('100');await root.locator('button').click();await expect(root.getByRole('status')).toHaveText('Подходящих аудиторий нет.');
   await page.locator('#language-toggle').click();await expect(root.locator('button')).toHaveText('Find rooms');
   await expect(root.locator('select option')).toHaveCount(3);
   await root.locator('[name=date]').fill('2027-03-01');await root.locator('[name=start]').fill('10:00');await root.locator('[name=end]').fill('10:30');await root.locator('[name=capacity]').fill('100');
   await root.locator('button').click();await expect(root.getByRole('status')).toHaveText('No matching rooms.');
   await page.route('**/api/v1/me/rooms/availability?*',route=>route.abort());await root.locator('button').click();await expect(root.getByText('Search failed. Check the date, interval and access.')).toBeVisible();await expect(root.locator('article')).toHaveCount(0);
  }
  const staff=await browser.newContext();contexts.push(staff);await staff.addCookies(sessions.teacher);const page=await staff.newPage();await page.goto(origin+'/#rooms');await expect(page.locator('#rooms-section')).toBeHidden();
 }finally{
  try{for(const context of contexts)await context.close();}finally{child.stdin.end();const timer=setTimeout(()=>child.kill(),5000);try{await stop;}finally{clearTimeout(timer);lines.close();}}
 }
});
