import { afterAll, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$app/environment', () => ({ browser: true }));

import { boolCodec, jsonBoolField, jsonRecordCodec, jsonStringField } from './codecs';
import { createPersistentRecord, createPersistentState } from './create-persistent-state.svelte';

// The suite runs in a node env (no DOM); back the storage the primitives use with a Map.
function makeStorage(): Storage {
  const map = new Map<string, string>();
  return {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    getItem: (k: string) => (map.has(k) ? map.get(k)! : null),
    key: (i: number) => [...map.keys()][i] ?? null,
    removeItem: (k: string) => void map.delete(k),
    setItem: (k: string, v: string) => void map.set(k, String(v))
  } satisfies Storage;
}

vi.stubGlobal('localStorage', makeStorage());
afterAll(() => vi.unstubAllGlobals());

describe('createPersistentState', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.useRealTimers();
  });

  it('persists on set and reads back on construction', () => {
    const a = createPersistentState({ key: 'k1', tier: 'local', codec: boolCodec(false, 'bool01') });
    a.value = true;
    expect(localStorage.getItem('k1')).toBe('1');
    const b = createPersistentState({ key: 'k1', tier: 'local', codec: boolCodec(false, 'bool01') });
    expect(b.value).toBe(true);
  });

  it('reset cancels a pending debounced write', () => {
    vi.useFakeTimers();
    const s = createPersistentState({ key: 'k2', tier: 'local', codec: boolCodec(false), debounceMs: 100 });
    s.value = true; // scheduled, not yet flushed
    s.reset(); // must drop the pending write
    vi.advanceTimersByTime(200);
    // reset wrote the default (false) immediately and the stale `true` never lands.
    expect(s.value).toBe(false);
    expect(localStorage.getItem('k2')).toBe('false');
  });
});

describe('createPersistentRecord', () => {
  type Rec = { name: string; on: boolean };
  const codec = jsonRecordCodec<Rec>(
    { name: jsonStringField(''), on: jsonBoolField(false) },
    { name: '', on: false }
  );
  const defaults: Rec = { name: '', on: false };

  beforeEach(() => localStorage.clear());

  // Guards the doc's "no internal $effect" rule: a record created OUTSIDE any component-init
  // context (as here, in a plain test) must not throw effect_orphan and must still persist.
  it('persists field writes without a component/effect context', () => {
    const rec = createPersistentRecord({ key: 'r1', tier: 'local', codec, defaults });
    rec.name = 'alpha';
    rec.on = true;
    expect(codec.decode(localStorage.getItem('r1'))).toEqual({ name: 'alpha', on: true });
  });

  it('reset restores defaults and persists them', () => {
    const rec = createPersistentRecord({ key: 'r2', tier: 'local', codec, defaults });
    rec.name = 'beta';
    rec.reset();
    expect(rec.name).toBe('');
    expect(codec.decode(localStorage.getItem('r2'))).toEqual(defaults);
  });

  // Regression: wrapping a record and overriding `reset` via Object.assign (as
  // createGraphOptionsState does) must not self-recurse into a stack overflow.
  it('a wrapped reset that captures the original does not recurse', () => {
    const rec = createPersistentRecord({ key: 'r3', tier: 'local', codec, defaults });
    const resetOriginal = rec.reset;
    let extra = 0;
    const wrapped = Object.assign(rec, {
      reset() {
        resetOriginal();
        extra += 1;
      }
    });
    rec.name = 'gamma';
    expect(() => wrapped.reset()).not.toThrow();
    expect(extra).toBe(1);
    expect(wrapped.name).toBe('');
  });
});
