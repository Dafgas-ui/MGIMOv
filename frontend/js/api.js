export class ApiError extends Error {
  constructor(status, code) { super('Не удалось получить ответ сервера'); this.status = status; this.code = code; }
}
export async function requestJson(path, { signal, method = 'GET', body, headers = {}, query } = {}) {
  if (typeof path !== 'string' || !/^\/api\/[a-z0-9/_-]+$/.test(path)) throw new TypeError('Local API path required');
  if (!['GET','POST','PATCH'].includes(method)) throw new TypeError('Unsupported method');
  const write = method !== 'GET';
  const parameters = query ? new URLSearchParams(query).toString() : '';
  const target = path + (parameters ? '?'+parameters : '');
  const response = await fetch(target, { method, credentials: 'same-origin', cache: 'no-store',
    redirect: 'error', headers: { Accept: 'application/json', ...(write ? {'Content-Type':'application/json'} : {}), ...headers }, signal,
    ...(write ? {body: JSON.stringify(body ?? {})} : {}) });
  if (!response.ok) {
    const code = path.includes('/coursework') && response.status === 409
      ? (await response.json().catch(() => null))?.code : undefined;
    throw new ApiError(response.status, code === 'coursework_brs_result_already_published' ? code : undefined);
  }
  return response.status === 204 ? null : response.json();
}
export const getJson = (path, options) => requestJson(path, options);
