import {test,expect} from '@playwright/test';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {createInterface} from 'node:readline';
import {fileURLToPath} from 'node:url';

test('Student academic dates: real sources, links, overdue, reschedule, cancel and isolation',async({browser,request},info)=>{
  const child=spawn(fileURLToPath(new URL('../../.venv/Scripts/python.exe',import.meta.url)),
    ['-B','-m','tests.browser.deadlines_server'],{cwd:fileURLToPath(new URL('../../',import.meta.url)),windowsHide:true,stdio:['pipe','pipe','pipe']});
  // Startup diagnostics contain no fixture credentials.
  let diagnostics='';child.stderr.on('data',chunk=>{diagnostics+=chunk.toString();});
  const lines=createInterface({input:child.stdout}),stop=once(child,'exit'),contexts=[];
  try{
    const [line]=await Promise.race([once(lines,'line'),stop.then(()=>{throw new Error('Date fixture failed: '+diagnostics);})]);
    const {origin,sessions,now,course}=JSON.parse(line);
    await expect.poll(async()=>{try{return(await request.get(origin+'/api/health')).status();}catch{return 0;}}).toBe(200);
    async function open(who,width){
      const context=await browser.newContext({viewport:{width,height:844}});contexts.push(context);
      await context.addCookies(sessions[who]);const page=await context.newPage();
      await page.clock.install({time:new Date(now*1000)});
      await page.goto(origin+'/#deadlines');return page;
    }
    async function control(value){const response=once(lines,'line');child.stdin.write(value+'\n');expect((await response)[0]).toBe('ok');}
    const page=await open('alice',390),root=page.locator('#deadlines-section');
    await expect(root.getByText('Просроченная работа',{exact:true})).toBeVisible();
    await expect(root.getByText('Скрытый черновик',{exact:true})).toHaveCount(0);
    await expect(root.getByText('Просрочено',{exact:true})).toHaveCount(1);
    await expect(root.getByText(/Время не указано/)).toHaveCount(2);
    const work=root.locator('article').filter({hasText:'Ближайшая работа'});
    await work.getByRole('button',{name:'Открыть событие'}).click();
    await expect(page.locator('#coursework-section').getByRole('heading',{name:'Ближайшая работа',exact:true})).toBeVisible();
    await page.goto(origin+'/#deadlines');
    await expect(root.locator('article')).toHaveCount(5);
    const exam=root.locator('article').filter({has:page.getByRole('heading',{name:'Math',exact:true})}).filter({hasText:'Дата испытания'});
    await expect(exam).toContainText('25 февраля');
    await control('reschedule');await root.getByRole('button',{name:'Обновить',exact:true}).click();
    await expect(exam).toContainText('26 февраля');
    await exam.getByRole('button',{name:'Открыть событие'}).click();
    await expect(page.locator('#deadline-attestations-'+course)).toHaveAttribute('open','');
    await expect(page.locator('#deadline-attestations-'+course)).toContainText('26.02.2027');
    await page.goto(origin+'/#deadlines');await expect(exam).toBeVisible();
    await control('cancel');await root.getByRole('button',{name:'Обновить',exact:true}).click();
    await expect(exam).toHaveCount(0);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth+1)).toBe(true);
    await page.screenshot({path:info.outputPath('deadlines-student-390.png')});
    const other=await open('bobby',1280);
    await expect(other.locator('#deadlines-section').getByText('Ближайших учебных сроков нет.')).toBeVisible();
    await other.screenshot({path:info.outputPath('deadlines-empty-1280.png')});
  }finally{
    try{for(const context of contexts)await context.close();}finally{
      child.stdin.end();const timer=setTimeout(()=>child.kill(),5000);
      try{await stop;}finally{clearTimeout(timer);lines.close();}
    }
  }
});
