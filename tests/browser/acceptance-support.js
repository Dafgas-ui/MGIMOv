import { expect } from '@playwright/test';
import { spawn, execFile } from 'node:child_process';
import { once } from 'node:events';
import { mkdir, mkdtemp, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';

const root = fileURLToPath(new URL('../../', import.meta.url));
const runs = join(root, '.tmp', 'playwright-p1');
const python = join(root, '.venv', 'Scripts', 'python.exe');
const execute = promisify(execFile);

export async function withFixture(run) {
  await mkdir(runs, { recursive: true });
  const directory = await mkdtemp(join(runs, 'run-acceptance-'));
  const child = spawn(python, ['-B', '-m', 'tests.browser.p1_server', directory, 'acceptance'],
    { cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'ignore'] });
  const exited = Promise.race([once(child, 'exit'), once(child, 'error')]).catch(() => {});
  const lines = createInterface({ input: child.stdout });
  try {
    const [line] = await Promise.race([
      once(lines, 'line', { signal: AbortSignal.timeout(15_000) }),
      exited.then(() => { throw new Error('Acceptance server exited during preparation.'); }),
    ]);
    lines.close();
    let fixture;
    try { fixture = JSON.parse(line); }
    catch { throw new Error('Invalid private fixture response.'); }
    await expect.poll(async () => {
      try { return (await fetch(fixture.origin + '/api/health', { signal: AbortSignal.timeout(1000) })).status; }
      catch { return 0; }
    }, { timeout: 8000 }).toBe(200);
    const snapshot = async () => {
      const { stdout } = await execute(python, ['-B', '-m', 'tests.browser.acceptance_snapshot', directory],
        { cwd: root, windowsHide: true });
      return JSON.parse(stdout);
    };
    await run(fixture, snapshot);
  } finally {
    lines.close();
    child.kill();
    await exited;
    await rm(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  }
}

export function responseFor(page, path, method = 'GET') {
  return page.waitForResponse(r => new URL(r.url()).pathname === path && r.request().method() === method,
    { timeout: 8000 });
}

export async function login(page, fixture, user) {
  const form = page.locator('#login-form');
  await form.locator('#login').fill(user);
  const field = await form.locator('#password').elementHandle();
  try {
    await page.evaluate(({ input, secret }) => { input.value = secret; },
      { input: field, secret: fixture.credentials[user] });
  } catch {
    throw new Error('Could not populate the login form.');
  } finally {
    await field?.dispose();
  }
  const [response] = await Promise.all([
    responseFor(page, '/api/v1/auth/login', 'POST'),
    form.getByRole('button', { name: /^(Войти|Sign in)$/ }).click(),
  ]);
  expect(response.status()).toBe(200);
  expect((await response.json()).user.id).toBe(user);
  await expect(page.locator('html')).toHaveAttribute('data-role', user.startsWith('s') ? 'student' : 'staff');
}

export async function evidence(page, info, label, run) {
  const context = page.context();
  await context.tracing.start({ screenshots: true, snapshots: true });
  try {
    await run();
    await context.tracing.stop();
  } catch (error) {
    await page.screenshot({ path: info.outputPath(label + '.png'), mask: [page.locator('#login-form')],
      timeout: 3000 }).catch(() => {});
    await context.tracing.stop({ path: info.outputPath(label + '-trace.zip') });
    throw error;
  }
}
