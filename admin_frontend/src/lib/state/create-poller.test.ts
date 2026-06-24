import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$app/environment', () => ({ browser: true }));

import { createPoller } from './create-poller.svelte';

describe('createPoller', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('does not overlap slow ticks', async () => {
    let concurrent = 0;
    let maxConcurrent = 0;
    let release!: () => void;
    const blocked = new Promise<void>((resolve) => {
      release = resolve;
    });

    const poller = createPoller(
      async () => {
        concurrent += 1;
        maxConcurrent = Math.max(maxConcurrent, concurrent);
        await blocked;
        concurrent -= 1;
      },
      { intervalMs: 100 }
    );

    poller.start();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(100);
    await vi.advanceTimersByTimeAsync(100);
    expect(maxConcurrent).toBe(1);

    release();
    await blocked;
    poller.stop();
  });

  it('stop disposer is idempotent', () => {
    const fn = vi.fn();
    const poller = createPoller(fn, { intervalMs: 50 });
    const stop = poller.start();
    stop();
    stop();
    vi.advanceTimersByTime(200);
    expect(fn).not.toHaveBeenCalled();
  });

  it('skips ticks while document is hidden', async () => {
    vi.stubGlobal('document', { hidden: true });
    const fn = vi.fn();
    const poller = createPoller(fn, { intervalMs: 50, pauseWhenHidden: true, immediate: true });
    poller.start();
    await vi.advanceTimersByTimeAsync(200);
    expect(fn).not.toHaveBeenCalled();
    poller.stop();
    vi.unstubAllGlobals();
  });
});
