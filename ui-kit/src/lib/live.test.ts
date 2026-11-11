import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// A stand-in for the browser's EventSource: records every stream opened, and lets a test send
// messages, pings and errors into it.
class FakeSource {
	static readonly CLOSED = 2;
	static all: FakeSource[] = [];
	onmessage: ((e: { data: string }) => void) | null = null;
	onerror: (() => void) | null = null;
	readyState = 1;
	closed = false;
	private pings: (() => void)[] = [];
	constructor(public url: string) {
		FakeSource.all.push(this);
	}
	addEventListener(type: string, fn: () => void) {
		if (type === 'ping') this.pings.push(fn);
	}
	close() {
		this.closed = true;
		this.readyState = FakeSource.CLOSED;
	}
	send(data: unknown) {
		this.onmessage?.({ data: typeof data === 'string' ? data : JSON.stringify(data) });
	}
	ping() {
		for (const fn of this.pings) fn();
	}
	/** A drop the browser reconnects from by itself (a network error). */
	fail() {
		this.readyState = 0;
		this.onerror?.();
	}
	/** An error the browser does not retry (an HTTP error, e.g. a proxy's 502 while the backend is down). */
	giveUp() {
		this.readyState = FakeSource.CLOSED;
		this.onerror?.();
	}
}

const hello = { type: 'hello', live: { connected: true, since: null, last_event: null, error: null } };

// live.ts keeps its one stream in module state: every test starts from a fresh copy.
async function freshLive() {
	vi.resetModules();
	return import('./live');
}

beforeEach(() => {
	FakeSource.all = [];
	vi.stubGlobal('EventSource', FakeSource);
	vi.useFakeTimers();
});
afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
});

describe('listen', () => {
	it('shares one stream between all listeners', async () => {
		const { listen } = await freshLive();
		const a = vi.fn();
		const b = vi.fn();
		listen(a);
		listen(b);
		expect(FakeSource.all).toHaveLength(1);
		FakeSource.all[0].send({ type: 'devices' });
		expect(a).toHaveBeenCalledWith({ type: 'devices' });
		expect(b).toHaveBeenCalledWith({ type: 'devices' });
	});

	it('closes the stream a moment after the last listener leaves', async () => {
		const { listen } = await freshLive();
		const stopA = listen(() => {});
		const stopB = listen(() => {});
		stopA();
		vi.advanceTimersByTime(5000);
		expect(FakeSource.all[0].closed).toBe(false); // B still listens
		stopB();
		vi.advanceTimersByTime(1000);
		expect(FakeSource.all[0].closed).toBe(false);
		vi.advanceTimersByTime(1500);
		expect(FakeSource.all[0].closed).toBe(true);
	});

	it('keeps the stream when a new listener comes before it closes (moving between pages)', async () => {
		const { listen } = await freshLive();
		const stop = listen(() => {});
		stop();
		vi.advanceTimersByTime(500);
		listen(() => {});
		vi.advanceTimersByTime(5000);
		expect(FakeSource.all).toHaveLength(1);
		expect(FakeSource.all[0].closed).toBe(false);
	});

	it('opens a new stream after the old one closed', async () => {
		const { listen } = await freshLive();
		listen(() => {})();
		vi.advanceTimersByTime(3000);
		listen(() => {});
		expect(FakeSource.all).toHaveLength(2);
	});

	it('does not pass on the first hello, but does after a drop', async () => {
		const { listen } = await freshLive();
		const heard = vi.fn();
		listen(heard);
		const es = FakeSource.all[0];
		es.send(hello);
		expect(heard).not.toHaveBeenCalled();
		es.fail(); // the backend restarted; EventSource reconnects by itself
		es.send(hello);
		expect(heard).toHaveBeenCalledWith(hello);
	});

	it('passes on a first hello that came after failed tries (the backend was down at first)', async () => {
		const { listen } = await freshLive();
		const heard = vi.fn();
		listen(heard);
		FakeSource.all[0].fail();
		FakeSource.all[0].send(hello);
		expect(heard).toHaveBeenCalledWith(hello);
	});

	it('opens a new stream when the browser gives one up, and passes on its first hello', async () => {
		const { listen } = await freshLive();
		const heard = vi.fn();
		listen(heard);
		const lost = FakeSource.all[0];
		lost.send(hello);
		lost.giveUp();
		vi.advanceTimersByTime(4999);
		expect(FakeSource.all).toHaveLength(1);
		vi.advanceTimersByTime(1);
		expect(FakeSource.all).toHaveLength(2);
		expect(lost.closed).toBe(true);
		FakeSource.all[1].send(hello); // the next backend: notices may have been missed, so pages reload
		expect(heard).toHaveBeenCalledWith(hello);
	});

	it('leaves reconnecting to the browser after a network error', async () => {
		const { listen } = await freshLive();
		listen(() => {});
		FakeSource.all[0].fail();
		vi.advanceTimersByTime(10_000);
		expect(FakeSource.all).toHaveLength(1);
	});

	it('replaces a stream that stays silent (dead without saying so), but not one that pings', async () => {
		const { listen } = await freshLive();
		const heard = vi.fn();
		listen(heard);
		const es = FakeSource.all[0];
		for (let i = 0; i < 5; i++) {
			vi.advanceTimersByTime(15_000);
			es.ping();
		}
		expect(FakeSource.all).toHaveLength(1);
		vi.advanceTimersByTime(45_000);
		expect(FakeSource.all).toHaveLength(2);
		expect(es.closed).toBe(true);
		FakeSource.all[1].send(hello);
		expect(heard).toHaveBeenCalledWith(hello);
	});

	it('opens nothing more once the last listener has left', async () => {
		const { listen } = await freshLive();
		const stop = listen(() => {});
		FakeSource.all[0].giveUp();
		stop();
		vi.advanceTimersByTime(60_000);
		expect(FakeSource.all).toHaveLength(1);
	});

	it('ignores malformed and unknown notices', async () => {
		const { listen } = await freshLive();
		const heard = vi.fn();
		listen(heard);
		FakeSource.all[0].send('not json');
		FakeSource.all[0].send({ type: 'something-new' });
		FakeSource.all[0].send(42);
		expect(heard).not.toHaveBeenCalled();
	});
});

describe('onNotices', () => {
	it('runs once per burst of the chosen types', async () => {
		const { onNotices } = await freshLive();
		const run = vi.fn();
		onNotices(['devices', 'sync'], run, 250);
		const es = FakeSource.all[0];
		es.send({ type: 'devices' });
		es.send({ type: 'states' }); // not chosen
		es.send({ type: 'sync' });
		vi.advanceTimersByTime(249);
		expect(run).not.toHaveBeenCalled();
		vi.advanceTimersByTime(1);
		expect(run).toHaveBeenCalledTimes(1);
	});

	it('ignores other types', async () => {
		const { onNotices } = await freshLive();
		const run = vi.fn();
		onNotices(['streams'], run);
		FakeSource.all[0].send({ type: 'states' });
		vi.advanceTimersByTime(1000);
		expect(run).not.toHaveBeenCalled();
	});

	it('stopping also drops a run still waiting', async () => {
		const { onNotices } = await freshLive();
		const run = vi.fn();
		const stop = onNotices(['streams'], run);
		FakeSource.all[0].send({ type: 'streams' });
		stop();
		vi.advanceTimersByTime(1000);
		expect(run).not.toHaveBeenCalled();
	});
});
