import { defineConfig } from '@playwright/test';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  testDir: '.',
  testMatch: ['p1.spec.js', 'commission.spec.js', 'acceptance-*.spec.js'],
  workers: 1,
  retries: 0,
  timeout: 90_000,
  outputDir: fileURLToPath(new URL('../../.tmp/playwright-p1/results', import.meta.url)),
  reporter: [['list'], ['html', {
    open: 'never',
    outputFolder: fileURLToPath(new URL('../../.tmp/playwright-p1/report', import.meta.url)),
  }]],
  use: {
    channel: 'chrome',
    headless: true,
    viewport: { width: 1280, height: 900 },
    // Login is deliberately outside manual tracing to keep passwords out of artifacts.
    trace: 'off',
    screenshot: 'off',
  },
});
