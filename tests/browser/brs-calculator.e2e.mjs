/** Standalone Chrome check. Uses an installed Playwright runtime and synthetic Uvicorn. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {createInterface} from 'node:readline';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {mkdir} from 'node:fs/promises';

const runtime = process.env.MGIMOV_PLAYWRIGHT_MODULE;
const {chromium} = await import(runtime ? pathToFileURL(runtime).href : 'playwright');
const root = fileURLToPath(new URL('../../', import.meta.url));
const python = process.env.MGIMOV_TEST_PYTHON || 'python';
const output = fileURLToPath(new URL('../../.tmp/calculator-browser/', import.meta.url));
await mkdir(output, {recursive:true});
const child = spawn(python, ['-B','-m','tests.browser.forecast_server'],
  {cwd:root, windowsHide:true, stdio:['pipe','pipe','pipe']});
// Keep fixture session data in memory, outside screenshots and console output.
const lines = createInterface({input:child.stdout});
const stopped = once(child,'exit');
let browser, activePage;
const errors=[], network=[];
try {
  const [line] = await Promise.race([once(lines,'line'), stopped.then(()=>{throw Error('Fixture stopped');})]);
  const {origin,sessions} = JSON.parse(line);
  browser = await chromium.launch({channel:'chrome', headless:true});
  const context = await browser.newContext({viewport:{width:390,height:844}});
  await context.addCookies(sessions.alice);
  const page = await context.newPage(); activePage=page;

  page.on('pageerror',error=>errors.push(error.message));
  page.on('requestfailed',r=>network.push([new URL(r.url()).pathname,r.failure()?.errorText]));
  page.on('response',r=>{if(r.url().includes('/api/')) network.push([new URL(r.url()).pathname,r.status()]);});
  await context.request.get(origin+'/api/health',{timeout:5000});
  await page.goto(origin+'/#academics');
  const panel=page.locator('#forecast-panel');
  const card=panel.locator('article').filter({has:page.getByRole('heading',{name:'Math',exact:true})});
  await card.locator('summary.brs-calculator-summary').click();
  await card.locator('.brs-calculator-results').getByText('Опубликованных результатов нет. Введите баллы для сценария.',{exact:true}).waitFor();
  const reply=once(lines,'line'); child.stdin.write('publish\n');
  assert.equal((await reply)[0],'ok');
  await panel.getByRole('button',{name:'Обновить прогноз'}).click();
  await card.locator('summary.brs-calculator-summary').click();
  await card.locator('.brs-sim-total').filter({hasText:'49'}).waitFor();
  const input=card.locator('.brs-calculator-input').nth(2);
  await input.fill('10');
  await card.locator('.brs-sim-total').filter({hasText:'50'}).waitFor();
  await card.getByText('Условия допуска выполнены. Порог: 50.',{exact:true}).waitFor();
  await input.press('ArrowUp');
  await card.locator('.brs-sim-total').filter({hasText:'51'}).waitFor();
  await input.press('ArrowDown');
  await card.locator('.brs-sim-total').filter({hasText:'50'}).waitFor();
  await input.fill('0.5');
  await card.getByText('Введите целое число от 0 до максимума мероприятия.',{exact:true}).waitFor();
  await card.getByRole('button',{name:'Сбросить симуляцию'}).click();
  await card.locator('.brs-sim-total').filter({hasText:'49'}).waitFor();
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth));
  await page.screenshot({path:output+'student-390-ru.png',fullPage:true});
  await page.locator('#language-toggle').click();
  await card.locator('summary.brs-calculator-summary').click();
  await card.getByText('Admission requirements not met. Threshold: 50.',{exact:true}).waitFor();
  assert(!/[А-Яа-я]/.test(await card.locator('.brs-calculator-results').innerText()));
  await page.screenshot({path:output+'student-390-en.png',fullPage:true});
  await page.route('**/api/v1/me/brs/forecast',route=>route.abort());
  await panel.getByRole('button',{name:'Refresh forecast'}).click();
  await page.getByText('Could not load the forecast. Refresh the data.',{exact:true}).waitFor();
  assert.equal(await panel.locator('.brs-calculator-details').count(),0);
  await page.unroute('**/api/v1/me/brs/forecast');
  await page.goto(origin+'/#settings');
  const logout = page.waitForResponse(response=>response.url().endsWith('/api/v1/auth/logout'));
  await page.locator('#logout').click();
  await (await logout).finished();
  await page.locator('#login-form').waitFor();
  await context.clearCookies();
  await context.addCookies(sessions.bobby);
  await page.goto(origin+'/#academics');
  await page.reload();
  await page.locator('#app-account-link').filter({hasText:'bobby'}).waitFor();
  await page.goto(origin+'/#academics');
  await panel.getByText('Нет дисциплин с планом БРС.',{exact:true}).waitFor();
  assert.equal(await panel.locator('.brs-calculator-details').count(),0);
  assert.deepEqual(errors,[]);
  console.log('PASS Chrome: real backend, empty, 49→50, integer rejection, reset, RU/EN, 390px, network failure, logout/account switch');
} catch(error) {
  if(activePage) {
    await activePage.screenshot({path:output+'failure.png',fullPage:true});
    console.error((await activePage.locator('body').innerText()).slice(0,1500));
    console.error(JSON.stringify({errors,network}));
  }
  throw error;
} finally {
  if(browser) await browser.close();
  child.stdin.end();
  const timer=setTimeout(()=>child.kill(),5000);
  await stopped.finally(()=>clearTimeout(timer));
  lines.close();
}
