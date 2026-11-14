import { test, expect } from '@playwright/test';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { mkdir, mkdtemp, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../../', import.meta.url));
const runs = join(root, '.tmp', 'playwright-p1');
const correction = /^Внести исправление(?: № \d+)?$/;

async function startServer() {
  await mkdir(runs, { recursive: true });
  const directory = await mkdtemp(join(runs, 'run-'));
  const child = spawn(join(root, '.venv', 'Scripts', 'python.exe'),
    ['-B', '-m', 'tests.browser.p1_server', directory],
    { cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  const exited = new Promise(resolve => {
    child.once('exit', resolve);
    child.once('error', resolve);
  });
  const stop = async () => {
    child.kill();
    await exited;
    await rm(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  };
  child.stderr.resume();
  const lines = createInterface({ input: child.stdout });
  const timeout = AbortSignal.timeout(15_000);
  try {
    const [line] = await Promise.race([
      once(lines, 'line', { signal: timeout }),
      exited.then(() => { throw new Error('Test server exited during fixture preparation.'); }),
    ]);
    let fixture;
    try {
      fixture = JSON.parse(line);
    } catch {
      throw new Error('Invalid private fixture response.');
    }
    await expect.poll(async () => {
      try {
        return (await fetch(fixture.origin + '/api/health', { signal: AbortSignal.timeout(1000) })).status;
      } catch {
        return 0;
      }
    }, { timeout: 8000, message: 'Isolated Uvicorn health' }).toBe(200);
    return { fixture, stop };
  } catch (error) {
    await stop();
    throw error;
  } finally {
    lines.close();
  }
}

test('P1: only the assigned examiner applies an approved correction; student sees history and debt closure',
  async ({ page, context }, testInfo) => {
    const { fixture, stop } = await startServer();
    const staffCourse = '/api/v1/staff/attestations/' + fixture.course;
    const content = page.locator('#attestations-content');
    const apply = content.getByRole('button', { name: correction });
    const row = content.getByRole('article').filter({ hasText: fixture.student + ' · ' + fixture.subject });
    let tracing = false;

    async function finishTrace(save) {
      if (!tracing) return;
      await context.tracing.stop(save ? { path: testInfo.outputPath('trace.zip') } : {});
      tracing = false;
    }

    async function login(user, role) {
      await page.goto(fixture.origin + '/#attestations');
      const form = page.locator('#login-form');
      await form.getByLabel('Логин', { exact: true }).fill(user);
      // Use a DOM assignment outside tracing. Passwords never enter Playwright's
      // fill action arguments, call log, trace, or assertion output.
      const password = form.getByLabel('Пароль', { exact: true });
      const field = await password.elementHandle();
      if (!field) throw new Error('Login password field is unavailable.');
      try {
        await page.evaluate(({ input, secret }) => { input.value = secret; },
          { input: field, secret: fixture.credentials[user] });
      } catch {
        throw new Error('Could not populate the login form.');
      } finally {
        await field.dispose();
      }
      const [response] = await Promise.all([
        page.waitForResponse(r => r.url().endsWith('/api/v1/auth/login') && r.request().method() === 'POST'),
        form.getByRole('button', { name: 'Войти', exact: true }).click(),
      ]);
      expect(response.status(), 'Browser login HTTP status').toBe(200);
      expect((await response.json()).user.id, 'Authenticated browser identity').toBe(user);
      await expect(page.locator('html')).toHaveAttribute('data-role', role);
      await expect(page.locator('#attestations-section')).toBeVisible();
      await context.tracing.start({ screenshots: true, snapshots: true });
      tracing = true;
    }

    async function logout() {
      await page.getByRole('link', { name: 'Настройки', exact: true }).filter({ visible: true }).first().click();
      const [response] = await Promise.all([
        page.waitForResponse(r => r.url().endsWith('/api/v1/auth/logout') && r.request().method() === 'POST'),
        page.getByRole('button', { name: 'Выйти из аккаунта', exact: true }).click(),
      ]);
      expect(response.status()).toBe(204);
      await expect(page.getByRole('button', { name: 'Войти', exact: true })).toBeVisible();
      await finishTrace(false);
    }

    async function openCourse() {
      const [response] = await Promise.all([
        page.waitForResponse(r => new URL(r.url()).pathname === staffCourse && r.request().method() === 'GET'),
        row.getByRole('button', { name: 'Открыть', exact: true }).click(),
      ]);
      expect(response.status()).toBe(200);
      await expect(content.getByRole('button', { name: 'К списку', exact: true })).toBeVisible();
      return response.json();
    }

    async function command(button, action) {
      const [response] = await Promise.all([
        page.waitForResponse(r => new URL(r.url()).pathname === staffCourse + '/commands' &&
          r.request().method() === 'POST' && r.request().postDataJSON()?.action === action),
        button.click(),
      ]);
      expect(response.status(), 'Browser command ' + action).toBe(200);
      return (await response.json()).version;
    }

    async function requestReview(grade, view) {
      const attempt = content.getByRole('article').filter({ hasText: /^Попытка 1 · / });
      const form = attempt.locator('details').filter({ has: page.locator('summary').filter({ hasText: /^Запросить пересмотр$/ }) });
      await form.locator('summary').click();
      await form.getByLabel('Оценка').selectOption(String(grade));
      await form.getByLabel('Причина').fill('Синтетический сценарий P1');
      await form.getByLabel('Основание').fill('PLAYWRIGHT-P1');
      const version = await command(form.getByRole('button', { name: 'Запросить пересмотр', exact: true }), 'review_requested');
      expect(version).toBe(view.version + 1);
      await logout();

      await login('d02', 'staff');
      const reviewer = await openCourse();
      const pending = reviewer.events.filter(event => event.kind === 'review_requested' &&
        !reviewer.events.some(other => ['review_approved', 'review_revoked', 'corrected'].includes(other.kind) &&
          other.data.review_version === event.version));
      const approvals = content.getByRole('button', { name: 'Разрешить пересмотр', exact: true });
      await expect(approvals).toHaveCount(pending.length);
      const index = pending.findIndex(event => event.version === version);
      expect(index, 'New review in the approver UI').toBeGreaterThanOrEqual(0);
      await command(approvals.nth(index), 'review_approved');
      await logout();
      return version;
    }

    try {
      await login('t02', 'staff');
      let view = await openCourse();
      const approved = grade => view.events.find(event => event.kind === 'review_requested' &&
        event.data.grade === grade && view.applicable_review_versions.includes(event.version));
      if (view.state.latest.data.grade !== 2) {
        const reset = approved(2)?.version ?? await requestReview(2, view);
        if (!tracing) {
          await login('t02', 'staff');
          view = await openCourse();
        }
        expect(view.applicable_review_versions).toContain(reset);
        await expect(apply).toHaveCount(1);
        const refreshed = page.waitForResponse(r => new URL(r.url()).pathname === staffCourse && r.request().method() === 'GET');
        await command(apply, 'corrected');
        view = await (await refreshed).json();
        await expect(content.getByRole('button', { name: 'К списку', exact: true })).toBeVisible();
      }
      expect(view.state.latest.data.grade).toBe(2);
      expect(view.state.debt).toBe(true);
      const review = approved(4)?.version ?? await requestReview(4, view);
      if (tracing) await logout();

      await login('t03', 'staff');
      await expect(content.getByRole('article').first().or(
        content.getByText('Доступных учебных позиций нет.', { exact: true })
      )).toBeVisible();
      await expect(row).toHaveCount(0);
      await expect(apply).toHaveCount(0);
      const forbidden = await page.request.get(fixture.origin + staffCourse, {
        headers: { 'X-Mgimov-User': 't03' },
      });
      expect(forbidden.status(), 'Another examiner cannot read the target course').toBe(404);
      await logout();

      await login('t02', 'staff');
      view = await openCourse();
      expect(view.applicable_review_versions).toContain(review);
      expect(view.state.latest.data.grade).toBe(2);
      await expect(apply).toBeVisible();
      await expect(apply).toBeEnabled();
      const previousFours = view.events.filter(event => event.kind === 'corrected' && event.data.grade === 4).length;
      await command(apply, 'corrected');
      await logout();

      await login('s04', 'student');
      const history = content.locator('details').filter({
        has: page.locator('summary').filter({ hasText: fixture.subject }),
      });
      await history.locator('summary').click();
      await expect(history.getByText(/^Опубликовано · .* · 2$/)).toBeVisible();
      const correctedFours = history.getByText(/^Исправлено · .* · 4$/);
      await expect(correctedFours).toHaveCount(previousFours + 1);
      await expect(correctedFours.last()).toBeVisible();
      await expect(history.getByText(/^Долг закрыт · /).last()).toBeVisible();
      await expect(history.getByText('Академическая задолженность', { exact: true })).toHaveCount(0);
      const response = await page.request.get(fixture.origin + '/api/v1/me/gradebook', {
        headers: { 'X-Mgimov-User': 's04' },
      });
      expect(response.status()).toBe(200);
      const book = await response.json();
      const result = book.semesters.flatMap(semester => semester.items).find(item => item.id === fixture.course);
      expect(result?.official_result?.grade).toBe(4);
      expect(result?.official_result?.corrected).toBe(true);
      expect(book.debts.map(item => item.id)).not.toContain(fixture.course);
      await finishTrace(false);
    } catch (error) {
      if (!page.isClosed()) {
        await page.screenshot({ path: testInfo.outputPath('failure.png'),
          mask: [page.locator('#login-form')], timeout: 3000 }).catch(() => {});
      }
      await finishTrace(true);
      throw error;
    } finally {
      await stop();
    }
  });
