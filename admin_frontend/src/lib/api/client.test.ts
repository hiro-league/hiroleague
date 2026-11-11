import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// UI kit step 1d: the answer contract apiRequest reads (the data itself; a failure is an HTTP status
// with FastAPI's {"detail": ...}).
const h = vi.hoisted(() => ({ signedOut: vi.fn(), stale: vi.fn() }));

vi.mock('$app/paths', () => ({ base: '' }));
vi.mock('$lib/runtime/sign-in-signal', () => ({ signalSignedOut: h.signedOut }));
vi.mock('$lib/runtime/server-stale-signal', () => ({ signalServerMaybeUnavailable: h.stale }));

import { apiRequest } from './client';

function answer(status: number, body: unknown): Response {
  return new Response(typeof body === 'string' ? body : JSON.stringify(body), { status });
}

const fetchMock = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal('window', { setTimeout, clearTimeout });
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('apiRequest', () => {
  it('returns the body itself', async () => {
    fetchMock.mockResolvedValue(answer(200, { people: [], roles: [] }));
    await expect(apiRequest('/people')).resolves.toEqual({ people: [], roles: [] });

    fetchMock.mockResolvedValue(answer(200, null));
    await expect(apiRequest('/eval/state')).resolves.toBeNull();
  });

  it("throws a failure's detail", async () => {
    fetchMock.mockResolvedValue(answer(400, { detail: 'Name is required.' }));
    await expect(apiRequest('/people', { method: 'POST', body: {} })).rejects.toThrow('Name is required.');
    expect(h.signedOut).not.toHaveBeenCalled();
    expect(h.stale).not.toHaveBeenCalled();
  });

  it('joins a list of validation errors as "where: what"', async () => {
    fetchMock.mockResolvedValue(
      answer(422, {
        detail: [
          { loc: ['body', 'name'], msg: 'Field required', type: 'missing' },
          { loc: ['body', 'limits', 'max'], msg: 'Input should be a valid integer', type: 'int_parsing' }
        ]
      })
    );
    await expect(apiRequest('/people', { method: 'POST', body: {} })).rejects.toThrow(
      'name: Field required; limits.max: Input should be a valid integer'
    );
  });

  it('falls back to the HTTP status when the body says nothing', async () => {
    fetchMock.mockResolvedValue(answer(404, {}));
    await expect(apiRequest('/nowhere')).rejects.toThrow('HTTP 404');

    fetchMock.mockResolvedValue(answer(502, '<html>Bad gateway</html>'));
    await expect(apiRequest('/people')).rejects.toThrow('HTTP 502');
    expect(h.stale).toHaveBeenCalledTimes(1);
  });

  it('signals signed out on a 401, but not from the sign-in routes', async () => {
    fetchMock.mockResolvedValue(answer(401, { detail: 'Sign in to the admin first.' }));
    await expect(apiRequest('/people')).rejects.toThrow('Sign in to the admin first.');
    expect(h.signedOut).toHaveBeenCalledTimes(1);

    fetchMock.mockResolvedValue(answer(401, { detail: 'Wrong name or password.' }));
    await expect(apiRequest('/auth/sign-in', { method: 'POST', body: {} })).rejects.toThrow(
      'Wrong name or password.'
    );
    expect(h.signedOut).toHaveBeenCalledTimes(1);
  });

  it('marks the server maybe unavailable on a 5xx and on a network failure', async () => {
    fetchMock.mockResolvedValue(answer(500, { detail: 'Boom.' }));
    await expect(apiRequest('/people')).rejects.toThrow('Boom.');
    expect(h.stale).toHaveBeenCalledTimes(1);

    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(apiRequest('/people')).rejects.toThrow('Failed to fetch');
    expect(h.stale).toHaveBeenCalledTimes(2);
  });
});
