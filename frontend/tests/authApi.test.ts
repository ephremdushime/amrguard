import { describe, it, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { apiFetch, getCsrfToken, setCsrfToken } from '../src/authApi';

describe('authApi session cookie & CSRF enforcement', () => {
  const originalFetch = globalThis.fetch;
  let lastRequest: { input: string; init: RequestInit } | null = null;

  beforeEach(() => {
    lastRequest = null;
    setCsrfToken('');
    globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
      lastRequest = { input: String(input), init: init || {} };
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    }) as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    setCsrfToken('');
  });

  it('always includes credentials and omits X-CSRF-Token on safe GET requests', async () => {
    setCsrfToken('csrf-test-token-123');
    await apiFetch('http://localhost:8000/api/v1/auth/me');

    assert.ok(lastRequest);
    assert.equal(lastRequest.init.credentials, 'include');
    const headers = new Headers(lastRequest.init.headers);
    assert.equal(headers.get('X-CSRF-Token'), null);
  });

  it('automatically attaches X-CSRF-Token on POST, PATCH, PUT, and DELETE mutations', async () => {
    setCsrfToken('csrf-mutation-token-xyz');
    assert.equal(getCsrfToken(), 'csrf-mutation-token-xyz');

    for (const method of ['POST', 'PATCH', 'PUT', 'DELETE']) {
      await apiFetch('http://localhost:8000/api/v1/admin/users', { method });
      assert.ok(lastRequest);
      assert.equal(lastRequest.init.credentials, 'include');
      const headers = new Headers(lastRequest.init.headers);
      assert.equal(headers.get('X-CSRF-Token'), 'csrf-mutation-token-xyz');
    }
  });
});
