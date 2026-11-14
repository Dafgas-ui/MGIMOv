import { getJson } from './api.js';
import {t} from './language.js';
const status = document.getElementById('server-status');
const retry = document.getElementById('retry');
let health;
function showHealth(){status.textContent=t(...health);}
document.addEventListener('mgimov:language',()=>{if(health)showHealth();});
async function check() {
  retry.disabled = true;
  health=['Проверяем соединение…','Checking connection…'];showHealth();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 8000);
  try {
    const result = await getJson('/api/health', { signal: controller.signal });
    if (result.status !== 'ok') throw new Error('Unexpected status');
    health=['Основа приложения готова. Сервер и отдельная база доступны.','The application server and database are available.'];showHealth();
  } catch {
    health=['Сервер или база пока недоступны. Проверьте запуск и инициализацию базы, затем повторите проверку.',
      'The server or database is unavailable. Check startup and database setup, then retry.'];showHealth();
  } finally {
    clearTimeout(timer);
    retry.disabled = false;
  }
}
retry.addEventListener('click', check);
check();
