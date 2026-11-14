import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { withFixture, login, evidence } from './acceptance-support.js';

for (const scenario of [
  { name: 'Student cannot schedule or publish', actor: 's05', target: 's05', operations: [['scheduled', 403], ['published', 403]] },
  { name: 'Unassigned examiner cannot publish', actor: 't03', target: 's05', operations: [['published', 404]] },
  { name: 'Administrator without academic rights cannot schedule', actor: 'a01', target: 's05', operations: [['scheduled', 404]] },
  { name: 'Passing grade prevents another retake with attempts remaining', actor: 'd01', target: 's04', operations: [['scheduled', 409]], used: 1, debt: false },
  { name: 'Three failed attempts prevent a fourth', actor: 'd01', target: 's10', operations: [['scheduled', 409]], used: 3, debt: true },
]) {
  test(scenario.name, async ({ page }, info) => withFixture(async (fixture, snapshot) => {
    await page.goto(fixture.origin);
    await login(page, fixture, scenario.actor);
    await evidence(page, info, 'access', async () => {
      const initial = await snapshot();
      const target = initial.courses[scenario.target];
      if (scenario.used !== undefined) {
        expect(target.used).toBe(scenario.used);
        expect(target.debt).toBe(scenario.debt);
        expect(target.grade).toBe(scenario.debt ? 2 : 4);
      } else {
        expect(Boolean(target.draft)).toBe(true);
      }
      const cookies = await page.context().cookies(fixture.origin);
      const csrf = cookies.find(cookie => cookie.name === 'mgimov_csrf')?.value;
      expect(Boolean(csrf)).toBe(true);
      const starts = Math.floor(Date.now() / 1000) + 86400;
      for (const [action, status] of scenario.operations) {
        const fields = action === 'scheduled'
          ? { starts_at: starts, ends_at: starts + 3600, examiner_id: 't02', commission: ['t02', 't03'] }
          : { slot_id: target.draft };
        const result = await page.evaluate(async ({ course, data, csrf, actor }) => {
          const response = await fetch('/api/v1/staff/attestations/' + course + '/commands', {
            method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf, 'X-Mgimov-User': actor },
            body: JSON.stringify(data),
          });
          return { status: response.status, detail: (await response.json()).detail };
        }, { course: target.course, data: { action, expected_version: target.version, request_key: randomUUID(), ...fields },
          csrf, actor: scenario.actor });
        expect(result.status, action).toBe(status);
        expect(result.detail).not.toMatch(/CSRF|аккаунт изменился/i);
        if (status === 409) expect(result.detail).toBe('Следующую попытку сейчас назначить нельзя.');
        expect((await snapshot()).fingerprint, 'Database state after denied ' + action).toBe(initial.fingerprint);
      }
    });
  }));
}
