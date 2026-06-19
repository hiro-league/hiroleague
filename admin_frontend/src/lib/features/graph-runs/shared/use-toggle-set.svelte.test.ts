import { describe, expect, it } from 'vitest';
import { createToggleSet } from './use-toggle-set.svelte';

describe('createToggleSet', () => {
  it('seeds from the initial iterable', () => {
    const s = createToggleSet<number>([1, 2]);
    expect(s.has(1)).toBe(true);
    expect(s.has(3)).toBe(false);
    expect([...s.value]).toEqual([1, 2]);
  });

  it('toggles a key in and back out', () => {
    const s = createToggleSet<number>();
    s.toggle(5);
    expect(s.has(5)).toBe(true);
    s.toggle(5);
    expect(s.has(5)).toBe(false);
  });

  it('adds and removes batches (collapse-all / expand-all)', () => {
    const s = createToggleSet<number>([0]);
    s.add([1, 2, 3]);
    expect([...s.value].sort()).toEqual([0, 1, 2, 3]);
    s.remove([0, 2]);
    expect([...s.value].sort()).toEqual([1, 3]);
  });

  it('clears and replaces the whole set', () => {
    const s = createToggleSet<string>(['a', 'b']);
    s.clear();
    expect(s.value.size).toBe(0);
    s.replace(['x', 'y']);
    expect([...s.value]).toEqual(['x', 'y']);
  });

  it('replaces the Set instance on every mutation (so reactivity tracks it)', () => {
    const s = createToggleSet<number>();
    const before = s.value;
    s.toggle(1);
    expect(s.value).not.toBe(before);
  });
});
