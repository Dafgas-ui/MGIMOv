import { test, expect } from '@playwright/test';
import { withFixture, login, evidence, responseFor } from './acceptance-support.js';

const title = page => page.locator('#page-title');
async function translatedControls(region) {
  const labels = await region.locator('button:visible, label:visible').evaluateAll(nodes =>
    nodes.map(node => node.getAttribute('aria-label') || node.textContent.trim()));
  expect(labels.filter(label => /[А-Яа-яЁё]/.test(label))).toEqual([]);
}
async function open(page, route, name) {
  const direct = page.locator('#app-sidebar, #app-bottom').locator('a[href="#' + route + '"]').filter({ visible: true });
  if (await direct.count()) {
    await direct.first().click();
  } else {
    await page.locator('#app-menu').click();
    await page.locator('#app-mobile-menu').locator('a[href="#' + route + '"]').click();
    await expect(page.locator('#app-mobile-menu')).toBeHidden();
  }
  await expect(title(page)).toHaveText(name);
}

async function language(page, value, signedIn) {
  const toggle = page.locator('#language-toggle');
  if (signedIn) {
    const [response] = await Promise.all([responseFor(page, '/api/v1/me/language', 'POST'), toggle.click()]);
    expect(response.status()).toBe(200);
    expect(response.request().postDataJSON().language).toBe(value);
  } else {
    await toggle.click();
  }
  await expect(page.locator('html')).toHaveAttribute('lang', value);
}

test('RU/EN: public preference, S06 account persistence and English Staff screens', async ({ page, browser }, info) =>
  withFixture(async fixture => {
    await page.goto(fixture.origin);
    await evidence(page, info, 'public-language', async () => {
      await expect(title(page)).toHaveText('Вход');
      await language(page, 'en', false);
      await expect(page.locator('#login-form').getByLabel('Username')).toBeVisible();
      await expect(page.locator('#login-form').getByLabel('Password', { exact: true })).toBeVisible();
      await translatedControls(page.locator('#login-form'));
    });
    const saved = responseFor(page, '/api/v1/me/language', 'POST');
    await login(page, fixture, 's06');
    expect((await saved).status()).toBe(200);
    await evidence(page, info, 'student-language', async () => {
      await expect(title(page)).toHaveText('My study day');
      await language(page, 'ru', true);
      await language(page, 'en', true);
      await language(page, 'ru', true);
      await page.reload();
      await expect(title(page)).toHaveText('Мой учебный день');
      await expect(page.locator('html')).toHaveAttribute('lang', 'ru');
      await open(page, 'settings', 'Настройки');
      const [logout] = await Promise.all([responseFor(page, '/api/v1/auth/logout', 'POST'),
        page.getByRole('button', { name: 'Выйти из аккаунта' }).click()]);
      expect(logout.status()).toBe(204);
      await expect(page.locator('html')).toHaveAttribute('lang', 'en');
      await expect(page.locator('#login-form').getByLabel('Username')).toBeVisible();
    });
    await page.reload();
    await login(page, fixture, 's06');
    await evidence(page, info, 'student-return', async () => {
      await expect(title(page)).toHaveText('Мой учебный день');
      await expect(page.locator('html')).toHaveAttribute('lang', 'ru');
      await language(page, 'en', true);
      await open(page, 'schedule', 'Timetable');
      await expect(page.getByRole('button', { name: 'Week', exact: true })).toBeVisible();
      await translatedControls(page.locator('#schedule-section'));
      await open(page, 'academics', 'Gradebook');
      await expect(page.getByRole('heading', { name: 'Outstanding assessments' })).toBeVisible();
      await open(page, 'attestations', 'Assessments');
      await expect(page.getByRole('heading', { name: 'Аттестации', exact: true })).toHaveCount(0);
      await expect(page.locator('#attestations-content summary').first()).toBeVisible();
      await page.locator('#attestations-content summary').first().click();
      await expect(page.locator('#attestations-content details[open]').getByText(/^Attempts used:/)).toBeVisible();
      await translatedControls(page.locator('#attestations-section'));
    });
    const staff = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    try {
      await staff.goto(fixture.origin);
      await language(staff, 'en', false);
      const staffSaved = responseFor(staff, '/api/v1/me/language', 'POST');
      await login(staff, fixture, 'd01');
      expect((await staffSaved).status()).toBe(200);
      await evidence(staff, info, 'staff-language', async () => {
        await expect(title(staff)).toHaveText('Queue');
        await open(staff, 'attestations', 'Assessments');
        await expect(staff.locator('#attestations-content').getByRole('button', { name: 'Open', exact: true }).first()).toBeVisible();
        await translatedControls(staff.locator('#attestations-section'));
        await open(staff, 'staff-schedule', 'Timetable');
        await expect(staff.getByText('Create or edit a class', { exact: true })).toBeVisible();
        await open(staff, 'students', 'Students');
        await expect(staff.getByText('Students in assigned faculties', { exact: true })).toBeVisible();
        await open(staff, 'certificates', 'Certificates');
      });
    } finally {
      await staff.close();
    }
  }));

async function geometry(page, info, name, control) {
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth),
    { message: name + ' page horizontal overflow' }).toBeLessThanOrEqual(1);
  await expect(control).toBeVisible();
  await control.scrollIntoViewIfNeeded();
  // Trial click checks enabled state, stability and whether another element intercepts the click.
  await control.click({ trial: true, timeout: 3000 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: info.outputPath(name + '.png'), fullPage: true, animations: 'disabled',
    mask: [page.locator('#login-form input')] });
}

for (const width of [390, 1280]) {
  test('Responsive at ' + width + ' px', async ({ page }, info) => withFixture(async fixture => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await page.goto(fixture.origin);
    await evidence(page, info, 'login-failure', async () =>
      geometry(page, info, 'login', page.locator('#login-form button[type=submit]')));
    await login(page, fixture, 's06');
    await evidence(page, info, 'student-failure', async () => {
      await expect(title(page)).toHaveText('Мой учебный день');
      await geometry(page, info, 'student-home', page.locator('#dashboard-section').getByRole('link', { name: 'Открыть расписание', exact: true }));
      await page.locator('#dashboard-section').getByRole('link', { name: 'Открыть уведомления', exact: true }).click({ trial: true });
      await open(page, 'schedule', 'Расписание');
      await geometry(page, info, 'student-timetable', page.locator('#schedule-week'));
      await page.locator('#schedule-week').click();
      await expect(page.locator('#schedule-week')).toHaveAttribute('aria-pressed', 'true');
      await geometry(page, info, 'student-timetable-week', page.locator('#schedule-next'));
      await open(page, 'academics', 'Зачётка');
      await expect(page.getByRole('heading', { name: 'Академические задолженности' })).toBeVisible();
      await geometry(page, info, 'student-gradebook', page.getByRole('button', { name: 'Обновить успеваемость' }));
      await open(page, 'settings', 'Настройки');
      const signout = page.getByRole('button', { name: 'Выйти из аккаунта' });
      await geometry(page, info, 'student-settings', signout);
      await signout.click();
      await expect(page.locator('#login-form')).toBeVisible();
    });
    await page.reload();
    await login(page, fixture, 'd01');
    await evidence(page, info, 'staff-failure', async () => {
      await expect(title(page)).toHaveText('Очередь');
      await geometry(page, info, 'staff-queue', page.locator('#requests-retry'));
      await open(page, 'attestations', 'Аттестации');
      await geometry(page, info, 'staff-assessments', page.locator('#attestations-content').getByRole('button', { name: 'Открыть' }).last());
      await open(page, 'staff-schedule', 'Расписание');
      await geometry(page, info, 'staff-timetable', page.getByText('Создать или изменить занятие', { exact: true }));
      await open(page, 'students', 'Студенты');
      await geometry(page, info, 'staff-students', page.getByText('Отправить уведомление студенту', { exact: true }).first());
      await open(page, 'certificates', 'Справки');
      await geometry(page, info, 'staff-certificates', page.getByRole('link', { name: 'Справки', exact: true }).filter({ visible: true }).first());
    });
  }));
}
