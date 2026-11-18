import {test,expect} from '@playwright/test';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {createInterface} from 'node:readline';
import {fileURLToPath} from 'node:url';

test('BRS forecast: published scores, 49/50, correction, isolation and reduced motion',async({browser,request},info)=>{
  const child=spawn(fileURLToPath(new URL('../../.venv/Scripts/python.exe',import.meta.url)),
    ['-B','-m','tests.browser.forecast_server'],{cwd:fileURLToPath(new URL('../../',import.meta.url)),windowsHide:true,stdio:['pipe','pipe','pipe']});
  let diagnostics='';child.stderr.on('data',chunk=>{diagnostics+=chunk.toString();});
  const lines=createInterface({input:child.stdout}),stopped=once(child,'exit'),contexts=[];
  let student;
  try{
    const [line]=await Promise.race([once(lines,'line'),stopped.then(()=>{throw new Error('Fixture startup failed: '+diagnostics);})]);
    const {origin,sessions}=JSON.parse(line);
    await expect.poll(async()=>{try{return(await request.get(origin+'/api/health')).status();}catch{return 0;}}).toBe(200);
    async function open(who,width,reducedMotion='no-preference'){
      const context=await browser.newContext({viewport:{width,height:844},reducedMotion});contexts.push(context);
      await context.addCookies(sessions[who]);const page=await context.newPage();
      await page.addInitScript(()=>{
        window.progressAnimations=[];const original=Element.prototype.animate;
        Element.prototype.animate=function(...args){
          if(this.tagName==='PROGRESS')window.progressAnimations.push({value:this.value,label:this.getAttribute('aria-label')});
          return original.apply(this,args);
        };
      });
      await page.goto(origin+'/#academics');return page;
    }
    async function control(value){const response=once(lines,'line');child.stdin.write(value+'\n');expect((await response)[0]).toBe('ok');}
    student=await open('alice',390);const panel=student.locator('#forecast-panel');
    await expect(panel.getByText('Опубликованных баллов нет',{exact:true})).toHaveCount(3);
    await control('publish');await panel.getByRole('button',{name:'Обновить прогноз'}).click();
    await expect(panel.getByText('Опубликовано: 49 из 100',{exact:true})).toHaveCount(3);
    await expect(panel.getByText('Предварительный результат по опубликованным баллам: Не зачтено',{exact:true})).toBeVisible();
    await expect(panel.getByText('Условия допуска по БРС пока не выполнены.',{exact:true})).toBeVisible();
    await control('correct');await panel.getByRole('button',{name:'Обновить прогноз'}).click();
    await expect(panel.getByText('Опубликовано: 50 из 100',{exact:true})).toHaveCount(3);
    await expect(panel.getByText('Предварительный результат по опубликованным баллам: Зачтено',{exact:true})).toBeVisible();
    await expect(panel.getByText('Условия допуска по БРС выполнены.',{exact:true})).toBeVisible();
    await expect(panel.locator('progress')).toHaveCount(3);
    expect(await panel.locator('progress').evaluateAll(nodes=>nodes.every(n=>n.value===50&&n.max===100))).toBe(true);
    expect(await student.evaluate(()=>window.progressAnimations.some(e=>e.value===50&&e.label==='Опубликованные баллы БРС'))).toBe(true);
    expect(await student.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth+1)).toBe(true);
    await student.screenshot({path:info.outputPath('forecast-student-390.png'),fullPage:true});
    const reduced=await open('alice',1280,'reduce');
    await expect(reduced.locator('#forecast-content progress')).toHaveCount(3);
    expect(await reduced.evaluate(()=>window.progressAnimations.length)).toBe(0);
    await reduced.screenshot({path:info.outputPath('forecast-reduced-1280.png'),fullPage:true});
    const other=await open('bobby',390);
    await expect(other.locator('#forecast-panel').getByText('Нет дисциплин с планом БРС.')).toBeVisible();
    await expect(other.locator('#forecast-content progress')).toHaveCount(0);
    const staff=await open('teacher',1280);await expect(staff.locator('#forecast-panel')).toBeHidden();
  }catch(error){if(student)await student.screenshot({path:info.outputPath('forecast-failure.png'),fullPage:true}).catch(()=>{});throw error;}
  finally{
    try{for(const context of contexts)await context.close();}finally{
      child.stdin.end();const timer=setTimeout(()=>child.kill(),5000);
      try{await stopped;}finally{clearTimeout(timer);lines.close();}
    }
  }
});
