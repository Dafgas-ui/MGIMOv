import { test, expect } from '@playwright/test';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { mkdir, mkdtemp, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../../', import.meta.url));
const runs = join(root, '.tmp', 'playwright-p1');
const endpoint = '/api/v1/staff/attestations';
const publish = 'Подтвердить и опубликовать';

async function withServer(student, run) {
  await mkdir(runs, { recursive: true });
  const directory = await mkdtemp(join(runs, 'run-commission-'));
  const child = spawn(join(root, '.venv', 'Scripts', 'python.exe'),
    ['-B', '-m', 'tests.browser.p1_server', directory, student],
    { cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'ignore'] });
  const exited = Promise.race([once(child, 'exit'), once(child, 'error')]).catch(() => {});
  const lines = createInterface({ input: child.stdout });
  try {
    const [line] = await Promise.race([
      once(lines, 'line', { signal: AbortSignal.timeout(15_000) }),
      exited.then(() => { throw new Error('Failed to prepare the commission fixture.'); }),
    ]);
    lines.close();
    let fixture;
    try { fixture = JSON.parse(line); }
    catch { throw new Error('Invalid private commission fixture response.'); }
    await expect.poll(async () => {
      try { return (await fetch(fixture.origin + '/api/health', { signal: AbortSignal.timeout(1000) })).status; }
      catch { return 0; }
    }, { timeout: 8000 }).toBe(200);
    await run(fixture);
  } finally {
    lines.close();
    child.kill();
    await exited;
    await rm(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  }
}

function responseFor(page, path, method = 'GET') {
  return page.waitForResponse(r => new URL(r.url()).pathname === path && r.request().method() === method);
}

async function as(browser, fixture, user, role, info, run) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  let tracing = false;
  try {
    await page.clock.setFixedTime(new Date(fixture.instant * 1000));
    await page.goto(fixture.origin + '/#attestations');
    const form = page.locator('#login-form');
    await form.getByLabel('Логин', { exact: true }).fill(user);
    const input = await form.getByLabel('Пароль', { exact: true }).elementHandle();
    try {
      await page.evaluate(({ field, secret }) => { field.value = secret; }, { field: input, secret: fixture.credentials[user] });
    } catch {
      throw new Error('Could not populate the password field.');
    } finally {
      await input?.dispose();
    }
    const [response] = await Promise.all([
      responseFor(page, '/api/v1/auth/login', 'POST'),
      form.getByRole('button', { name: 'Войти', exact: true }).click(),
    ]);
    expect(response.status()).toBe(200);
    expect((await response.json()).user.id).toBe(user);
    await context.tracing.start({ screenshots: true, snapshots: true });
    tracing = true;
    await expect(page.locator('html')).toHaveAttribute('data-role', role);
    await expect(page.locator('#attestations-section')).toBeVisible();
    await run(page, page.locator('#attestations-content'));
  } catch (error) {
    await page.screenshot({ path: info.outputPath('failure-' + user + '.png'),
      mask: [page.locator('#login-form')], timeout: 3000 }).catch(() => {});
    if (tracing) {
      await context.tracing.stop({ path: info.outputPath('trace-' + user + '.zip') });
      tracing = false;
    }
    throw error;
  } finally {
    if (tracing) await context.tracing.stop();
    await context.close();
  }
}

function courseRow(content, fixture) {
  return content.getByRole('article').filter({ hasText: fixture.student + ' · ' + fixture.subject });
}

async function openCourse(page, content, fixture) {
  const [response] = await Promise.all([
    responseFor(page, endpoint + '/' + fixture.course),
    courseRow(content, fixture).getByRole('button', { name: 'Открыть', exact: true }).click(),
  ]);
  expect(response.status()).toBe(200);
  return response.json();
}

async function command(page, button, course, action) {
  const path = endpoint + '/' + course;
  const [response, refresh] = await Promise.all([
    responseFor(page, path + '/commands', 'POST'),
    responseFor(page, path),
    button.click(),
  ]);
  expect(response.status()).toBe(200);
  expect(response.request().postDataJSON().action).toBe(action);
  expect(refresh.status()).toBe(200);
  return refresh.json();
}

for (const { student, grade, debt } of [
  { student: 's02', grade: 4, debt: false },
  { student: 's05', grade: 2, debt: true },
]) {
  test(student.toUpperCase() + ': commission grade ' + grade + ', three attempts and retake restriction',
    async ({ browser }, info) => withServer(student, async fixture => {
      await as(browser, fixture, 't03', 'staff', info, async (page, content) => {
        await expect(content.getByRole('article').first().or(
          content.getByText('Доступных учебных позиций нет.', { exact: true }))).toBeVisible();
        await expect(courseRow(content, fixture)).toHaveCount(0);
        const response = await page.request.get(fixture.origin + endpoint + '/' + fixture.course,
          { headers: { 'X-Mgimov-User': 't03' } });
        expect(response.status()).toBe(404);
      });

      await as(browser, fixture, 't02', 'staff', info, async (page, content) => {
        let view = await openCourse(page, content, fixture);
        const [slot, appointment] = Object.entries(view.slots).find(([, entry]) => entry.number === 3);
        expect(appointment.examiner_id).toBe('t02');
        expect(appointment.commission).toEqual(['t02', 't03']);
        expect(view.state.used).toBe(2);
        expect(view.state.debt).toBe(true);
        const third = content.getByRole('article').filter({ hasText: /^Попытка 3 · / });
        await expect(third.getByText('Комиссионная аттестация', { exact: true })).toBeVisible();
        expect(view.state.stages[slot]).toBe(student === 's02' ? 'scheduled' : 'draft');
        await third.locator('summary').filter({ hasText: /^Сохранить черновик$/ }).click();
        await third.getByLabel('Оценка').selectOption(String(grade));
        view = await command(page, third.getByRole('button', { name: 'Сохранить черновик' }), fixture.course, 'draft');
        expect(view.state.stages[slot]).toBe('draft');
        view = await command(page, third.getByRole('button', { name: publish }), fixture.course, 'published');
        expect(view.state.official[slot].data.grade).toBe(grade);
        view = await command(page, third.getByRole('button', { name: 'Завершить запись' }), fixture.course, 'completed');
        expect(view.state.stages[slot]).toBe('completed');
        expect(view.state.used).toBe(3);
        expect(view.state.debt).toBe(debt);
      });

      await as(browser, fixture, student, 'student', info, async (page, content) => {
        const history = content.locator('details').filter({
          has: page.locator('summary').filter({ hasText: fixture.subject }),
        });
        await history.locator('summary').click();
        await expect(history.getByText('Использовано попыток: 3 из 3', { exact: true })).toBeVisible();
        for (const [index, result] of [2, 2, grade].entries()) {
          await expect(history.getByText(new RegExp('^Опубликовано · Попытка ' + (index + 1) + ' · .* · ' + result + '$'))).toBeVisible();
        }
        await expect(history.getByText(/^Завершено · Попытка 3 · Комиссия · /)).toBeVisible();
        await expect(history.getByText('Академическая задолженность', { exact: true })).toHaveCount(Number(debt));
        await expect(history.getByText(/^Долг закрыт · /)).toHaveCount(Number(!debt));
        const response = await page.request.get(fixture.origin + '/api/v1/me/gradebook',
          { headers: { 'X-Mgimov-User': student } });
        expect(response.status()).toBe(200);
        const book = await response.json();
        const item = book.semesters.flatMap(semester => semester.items).find(item => item.id === fixture.course);
        expect(item?.official_result?.grade).toBe(grade);
        expect(book.debts.some(item => item.id === fixture.course)).toBe(debt);
      });

      await as(browser, fixture, 'd01', 'staff', info, async (page, content) => {
        const view = await openCourse(page, content, fixture);
        expect(view.permissions).toContain('schedule');
        expect(view.state.used).toBe(3);
        expect(Object.keys(view.slots)).toHaveLength(3);
        await expect(content.getByRole('button', { name: 'К списку' })).toBeVisible();
        await expect(content.locator('summary').filter({ hasText: /^Назначить испытание$/ })).toHaveCount(0);
      });
    }));
}
