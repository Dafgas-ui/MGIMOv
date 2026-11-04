import test from 'node:test';
import assert from 'node:assert/strict';
import {getJson, ApiError} from '../frontend/js/api.js';
test('client only accepts local API paths', async () => {
  for (const path of ['https://example.invalid/api/health','//example.invalid/api/health','/api/../data','/api/health?url=x']) await assert.rejects(getJson(path), TypeError);
});
test('client uses same-origin no-store and safe error', async () => {
  const previous = globalThis.fetch;
  try {
    globalThis.fetch = async (path, options) => {
      assert.equal(path, '/api/health');
      assert.equal(options.credentials, 'same-origin');
      assert.equal(options.cache, 'no-store');
      assert.equal(options.redirect, 'error');
      return {ok:true,json:async()=>({status:'ok'})};
    };
    assert.deepEqual(await getJson('/api/health'), {status:'ok'});
    globalThis.fetch = async () => ({ok:false,status:503});
    await assert.rejects(getJson('/api/health'), error => error instanceof ApiError && error.status === 503);
  } finally { globalThis.fetch = previous; }
});
