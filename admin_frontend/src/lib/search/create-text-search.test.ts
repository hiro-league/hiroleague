import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$app/environment', () => ({ browser: false }));

import { createTextSearch } from './create-text-search.svelte';

describe('createTextSearch', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('commits immediately when debounceMs is 0', () => {
    const onCommit = vi.fn();
    const search = createTextSearch({ debounceMs: 0, onCommit });

    search.set('alpha');
    expect(search.query).toBe('alpha');
    expect(search.debounced).toBe('alpha');
    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith('alpha');
  });

  it('debounces commits', () => {
    const onCommit = vi.fn();
    const search = createTextSearch({ debounceMs: 250, onCommit });

    search.set('a');
    search.set('ab');
    expect(onCommit).not.toHaveBeenCalled();
    expect(search.debounced).toBe('');

    vi.advanceTimersByTime(249);
    expect(onCommit).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1);
    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith('ab');
    expect(search.debounced).toBe('ab');
  });

  it('clear resets query and commits an empty string', () => {
    const onCommit = vi.fn();
    const search = createTextSearch({ debounceMs: 250, onCommit });

    search.set('keep');
    vi.advanceTimersByTime(250);
    onCommit.mockClear();

    search.clear();
    expect(search.query).toBe('');
    expect(search.debounced).toBe('');
    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith('');
  });

  it('sync updates state without onCommit', () => {
    const onCommit = vi.fn();
    const search = createTextSearch({ debounceMs: 250, onCommit });

    search.set('pending');
    search.sync('applied');
    expect(search.query).toBe('applied');
    expect(search.debounced).toBe('applied');
    expect(onCommit).not.toHaveBeenCalled();

    vi.advanceTimersByTime(250);
    expect(onCommit).not.toHaveBeenCalled();
  });

  it('teardown cancels a pending debounced commit', () => {
    const onCommit = vi.fn();
    const search = createTextSearch({ debounceMs: 250, onCommit });

    search.set('wait');
    search.teardown();
    vi.advanceTimersByTime(250);
    expect(onCommit).not.toHaveBeenCalled();
  });
});
