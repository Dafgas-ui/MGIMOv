// Same-origin read-only client for V2. Mutations and CSRF arrive with V3.
export class ApiError extends Error {
  constructor(status) { super('Не удалось получить ответ сервера'); this.status = status; }
}
export async function getJson(path, { signal } = {}) {
  if (typeof path !== 'string' || !/^\/api\/[a-z0-9/_-]+$/.test(path)) throw new TypeError('Local API path required');
  const response = await fetch(path, { method: 'GET', credentials: 'same-origin', cache: 'no-store',
    redirect: 'error', headers: { Accept: 'application/json' }, signal });
  if (!response.ok) throw new ApiError(response.status);
  return response.json();
}
