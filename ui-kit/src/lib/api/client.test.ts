// The one client every Hiro app calls its backend with: the answer is the data, a failure is an ApiError with
// FastAPI's words, and an app's hooks hear what its backend needs to know.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$app/paths', () => ({ resolve: () => '/' }));
vi.mock('$hiro-app/app', () => ({ APP: { name: 'TestHiro', api: {} } }));
// What goes to the app's log (problems.ts), heard here instead of sent.
const reported = vi.fn();
vi.mock('./problems', () => ({ newTraceparent: () => `00-${'a'.repeat(32)}-${'b'.repeat(16)}-01`, report: (p: unknown) => reported(p) }));
const TRACEPARENT = `00-${'a'.repeat(32)}-${'b'.repeat(16)}-01`;

const { ApiError, createApi } = await import('./client');

const answer = (status: number, body: unknown) =>
	({ ok: status < 400, status, statusText: 'Status', json: () => Promise.resolve(body) }) as Response;

describe('createApi', () => {
	let fetchMock: ReturnType<typeof vi.fn>;
	beforeEach(() => {
		fetchMock = vi.fn();
		vi.stubGlobal('fetch', fetchMock);
		reported.mockClear();
	});
	afterEach(() => {
		vi.unstubAllGlobals();
		vi.useRealTimers();
	});

	it('answers with the data itself', async () => {
		fetchMock.mockResolvedValue(answer(200, { n: 1 }));
		await expect(createApi()<{ n: number }>('things')).resolves.toEqual({ n: 1 });
		expect(fetchMock).toHaveBeenCalledWith('/api/things', expect.objectContaining({ method: 'GET', headers: { traceparent: TRACEPARENT } }));
	});

	it("sends the app's headers with every call, beside the JSON one", async () => {
		fetchMock.mockResolvedValue(answer(200, {}));
		let picked = 'a';
		const api = createApi({ headers: () => ({ 'x-hiro-workspace': picked }) });
		await api('things', { method: 'PUT', body: { n: 1 } });
		picked = 'b';
		await api('things');
		expect(fetchMock.mock.calls[0][1].headers).toEqual({ 'x-hiro-workspace': 'a', traceparent: TRACEPARENT, 'Content-Type': 'application/json' });
		expect(fetchMock.mock.calls[1][1].headers).toEqual({ 'x-hiro-workspace': 'b', traceparent: TRACEPARENT });
	});

	it("says FastAPI's words for a failure, and tells the app its session is gone", async () => {
		const onSignedOut = vi.fn();
		const onUnreachable = vi.fn();
		const api = createApi({ onSignedOut, onUnreachable });
		fetchMock.mockResolvedValue(answer(422, { detail: [{ loc: ['body', 'count'], msg: 'Input should be greater than 0' }] }));
		await expect(api('things')).rejects.toMatchObject({ status: 422, message: 'count: Input should be greater than 0' });
		fetchMock.mockResolvedValue(answer(401, { detail: 'Sign in first.' }));
		await expect(api('things')).rejects.toMatchObject({ status: 401, message: 'Sign in first.' });
		expect(onSignedOut).toHaveBeenCalledWith('things');
		expect(onUnreachable).not.toHaveBeenCalled();
		// The backend's own answers, shown to the person: not problems for the log.
		expect(reported).not.toHaveBeenCalled();
	});

	it('tells the app when the backend is unreachable or failing', async () => {
		const onUnreachable = vi.fn();
		const api = createApi({ onUnreachable });
		fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
		await expect(api('things')).rejects.toMatchObject({ status: 0, message: "The TestHiro backend can't be reached. Is it restarting?" });
		fetchMock.mockResolvedValue(answer(502, {}));
		await expect(api('things')).rejects.toMatchObject({ status: 502, traceparent: TRACEPARENT });
		expect(onUnreachable).toHaveBeenCalledTimes(2);
		// Both go to the app's log under the call's own story
		expect(reported.mock.calls.map(([p]) => [p.kind, p.level, p.status, p.method, p.path, p.traceparent])).toEqual([
			['request', 'WARNING', 0, 'GET', 'things', TRACEPARENT],
			['request', 'ERROR', 502, 'GET', 'things', TRACEPARENT]
		]);
		expect(new ApiError(1, 'x')).toBeInstanceOf(Error);
	});

	it('gives up after the time limit without calling the backend unreachable', async () => {
		vi.useFakeTimers();
		const onUnreachable = vi.fn();
		// a call that only ends when it is stopped
		fetchMock.mockImplementation(
			(_url: string, init: RequestInit) =>
				new Promise((_, reject) => init.signal!.addEventListener('abort', () => reject(new DOMException('stopped', 'AbortError'))))
		);
		const call = createApi({ timeoutMs: 20_000, onUnreachable })('things');
		const failed = expect(call).rejects.toMatchObject({ status: 0, message: 'TestHiro took more than 20 s to answer. It may be busy: try again.' });
		await vi.advanceTimersByTimeAsync(20_000);
		await failed;
		expect(onUnreachable).not.toHaveBeenCalled();
	});

	it("a call the caller cancels ends as cancelled, not as a failure", async () => {
		fetchMock.mockImplementation(
			(_url: string, init: RequestInit) =>
				new Promise((_, reject) => init.signal!.addEventListener('abort', () => reject(new DOMException('stopped', 'AbortError'))))
		);
		const stop = new AbortController();
		const call = createApi({ timeoutMs: 20_000 })('things', { signal: stop.signal });
		stop.abort();
		await expect(call).rejects.toMatchObject({ name: 'AbortError' });
	});
});
