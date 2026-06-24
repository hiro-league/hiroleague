import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createDegradedDetector, DEGRADE_GRACE_MS } from './degraded.svelte';

describe('createDegradedDetector', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('stays healthy through a brief disconnect', () => {
    const detector = createDegradedDetector(100);
    detector.onDisconnected();
    vi.advanceTimersByTime(99);
    expect(detector.degraded).toBe(false);
    detector.onConnected();
    expect(detector.degraded).toBe(false);
  });

  it('flips degraded after the grace window', () => {
    const detector = createDegradedDetector(100);
    detector.onDisconnected();
    vi.advanceTimersByTime(100);
    expect(detector.degraded).toBe(true);
  });

  it('clears degraded on reconnect', () => {
    const detector = createDegradedDetector(100);
    detector.onDisconnected();
    vi.advanceTimersByTime(100);
    detector.onConnected();
    expect(detector.degraded).toBe(false);
  });

  it('resets without marking degraded', () => {
    const detector = createDegradedDetector(100);
    detector.onDisconnected();
    detector.onReset();
    vi.advanceTimersByTime(DEGRADE_GRACE_MS);
    expect(detector.degraded).toBe(false);
  });
});
