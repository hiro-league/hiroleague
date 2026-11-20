// A page's problems go to its app's log (problems.ts): batched, the same one counted, under its story, with no query.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$app/paths', () => ({ resolve: () => '/' }));
vi.mock('$hiro-app/app', () => ({ APP: { name: 'TestHiro', api: {} } }));

const { ApiError } = await import('./client');
const { flushProblems, newTraceparent, report, reportError, resetProblems, storyOf } = await import('./problems');

const answer = (status: number) => ({ ok: status < 400, status, json: () => Promise.resolve({}) }) as Response;
const sent = (fetchMock: ReturnType<typeof vi.fn>, n = 0) => JSON.parse(fetchMock.mock.calls[n][1].body).problems;

describe('page problems', () => {
	let fetchMock: ReturnType<typeof vi.fn>;
	beforeEach(() => {
		resetProblems();
		fetchMock = vi.fn().mockResolvedValue(answer(200));
		vi.stubGlobal('fetch', fetchMock);
		vi.stubGlobal('location', { pathname: '/streams' });
	});
	afterEach(() => vi.unstubAllGlobals());

	it('makes a valid W3C traceparent, a new story each time', () => {
		const [a, b] = [newTraceparent(), newTraceparent()];
		expect(a).toMatch(/^00-[0-9a-f]{32}-[0-9a-f]{16}-01$/);
		expect(storyOf(a)).not.toBe(storyOf(b));
	});

	it('sends a batch to the app, the same problem counted once', async () => {
		report({ kind: 'request', level: 'WARNING', message: 'no answer', method: 'GET', path: 'cams?x=1', status: 0 });
		report({ kind: 'request', level: 'WARNING', message: 'no answer', method: 'GET', path: 'cams?x=1', status: 0 });
		await flushProblems();
		expect(fetchMock).toHaveBeenCalledWith('/api/page-problems', expect.objectContaining({ method: 'POST' }));
		const [p] = sent(fetchMock);
		expect(p).toMatchObject({ kind: 'request', count: 2, page: '/streams', path: 'cams', status: 0 });
		expect(p.traceparent).toMatch(/^00-[0-9a-f]{32}-/);
	});

	it("an error from a call keeps the call's story; one the call reported already isn't sent twice", async () => {
		const call = `00-${'c'.repeat(32)}-${'d'.repeat(16)}-01`;
		reportError(new ApiError(403, 'Not yours', call));
		reportError(new ApiError(502, 'Bad gateway', call));
		await flushProblems();
		const problems = sent(fetchMock);
		expect(problems).toHaveLength(1);
		expect(problems[0]).toMatchObject({ kind: 'error', error_type: 'ApiError', message: 'Not yours', traceparent: call });
	});

	it('keeps what failed to send for the next try, and never reports its own failure', async () => {
		fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'));
		reportError(new TypeError('x is undefined'));
		await flushProblems();
		await flushProblems();
		expect(fetchMock).toHaveBeenCalledTimes(2);
		expect(sent(fetchMock, 1)).toEqual(sent(fetchMock, 0));
		expect(sent(fetchMock, 1)[0]).toMatchObject({ kind: 'error', error_type: 'TypeError', page: '/streams' });
	});

	it('drops a batch the app refuses (signed out, or no such route), and sends at most 30 a minute', async () => {
		fetchMock.mockResolvedValueOnce(answer(404));
		for (let i = 0; i < 40; i++) report({ kind: 'error', level: 'ERROR', message: `m${i}` });
		await flushProblems();
		await flushProblems();
		await flushProblems();
		const after = fetchMock.mock.calls.slice(1).flatMap((_, i) => sent(fetchMock, i + 1));
		expect(after).toHaveLength(10); // 30 taken: 20 in the refused batch, the other 10 sent next
	});
});
