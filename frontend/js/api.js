export class ApiError extends Error {
  constructor(status) { super('Не удалось получить ответ сервера'); this.status = status; }
}
export async function requestJson(path, { signal, method = 'GET', body, headers = {} } = {}) {
  if (typeof path !== 'string' || !/^\/api\/[a-z0-9/_-]+$/.test(path)) throw new TypeError('Local API path required');
  if (!['GET','POST'].includes(method)) throw new TypeError('Unsupported method');
  const response = await fetch(path, { method, credentials: 'same-origin', cache: 'no-store',
    redirect: 'error', headers: { Accept: 'application/json', ...(method === 'POST' ? {'Content-Type':'application/json'} : {}), ...headers }, signal,
    ...(method === 'POST' ? {body: JSON.stringify(body ?? {})} : {}) });
  if (!response.ok) throw new ApiError(response.status);
  return response.status === 204 ? null : response.json();
}
export const getJson = (path, options) => requestJson(path, options);
