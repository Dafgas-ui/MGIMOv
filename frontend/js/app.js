import { getJson } from './api.js';
const status = document.getElementById('server-status');
const retry = document.getElementById('retry');
async function check() {
  retry.disabled = true;
  status.textContent = 'Проверяем соединение…';
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 8000);
  try {
    const result = await getJson('/api/health', { signal: controller.signal });
    if (result.status !== 'ok') throw new Error('Unexpected status');
    status.textContent = 'Основа приложения готова. Сервер и отдельная база доступны.';
  } catch {
    status.textContent = 'Сервер или база пока недоступны. Проверьте запуск и инициализацию базы, затем повторите проверку.';
  } finally {
    clearTimeout(timer);
    retry.disabled = false;
  }
}
retry.addEventListener('click', check);
check();
