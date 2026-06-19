import { describe, it, expect, beforeEach, vi } from 'vitest';

// The storage helpers no-op unless `browser` is true; force it on for these unit tests.
vi.mock('$app/environment', () => ({ browser: true }));

// Minimal in-memory localStorage stub (node has none).
beforeEach(() => {
  const store = new Map<string, string>();
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    setItem: (k: string, v: string) => void store.set(k, String(v)),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear()
  });
});

import { PREF_KEYS } from '$lib/preferences/keys';
import {
  readEvalInt,
  readCorpusPref,
  writeCorpusPref,
  readAnswerPromptPref,
  writeAnswerPromptPref,
  readCorpusMarkdownPref,
  writeCorpusMarkdownPref
} from './eval-prefs';

describe('readEvalInt', () => {
  it('falls back when unset or invalid, and rejects negatives', () => {
    expect(readEvalInt('missing', 7)).toBe(7);
    localStorage.setItem('k', 'abc');
    expect(readEvalInt('k', 7)).toBe(7);
    localStorage.setItem('k', '-3');
    expect(readEvalInt('k', 7)).toBe(7);
  });

  it('reads a stored non-negative integer', () => {
    localStorage.setItem('k', '42');
    expect(readEvalInt('k', 7)).toBe(42);
  });
});

describe('per-track corpus pref', () => {
  it('round-trips independently per track', () => {
    writeCorpusPref('memory', 'mem-corpus');
    writeCorpusPref('knowledge', 'kn-corpus');
    expect(readCorpusPref('memory')).toBe('mem-corpus');
    expect(readCorpusPref('knowledge')).toBe('kn-corpus');
  });

  it('an empty id removes only that track', () => {
    writeCorpusPref('memory', 'mem-corpus');
    writeCorpusPref('knowledge', 'kn-corpus');
    writeCorpusPref('memory', '');
    expect(readCorpusPref('memory')).toBe('');
    expect(readCorpusPref('knowledge')).toBe('kn-corpus');
  });

  it('survives corrupt JSON by returning empty', () => {
    localStorage.setItem(PREF_KEYS.evalCorpus, '{not json');
    expect(readCorpusPref('memory')).toBe('');
  });
});

describe('per-corpus answer-prompt pref', () => {
  it('round-trips independently per corpus', () => {
    writeAnswerPromptPref('c1', 'terse');
    writeAnswerPromptPref('c2', 'verbose');
    expect(readAnswerPromptPref('c1')).toBe('terse');
    expect(readAnswerPromptPref('c2')).toBe('verbose');
  });

  it('ignores a blank corpus id', () => {
    writeAnswerPromptPref('', 'terse');
    expect(readAnswerPromptPref('')).toBe('');
  });

  it('an empty profile removes only that corpus', () => {
    writeAnswerPromptPref('c1', 'terse');
    writeAnswerPromptPref('c1', '');
    expect(readAnswerPromptPref('c1')).toBe('');
  });
});

describe('corpus markdown pref', () => {
  it('round-trips enabled/disabled', () => {
    expect(readCorpusMarkdownPref()).toBe(false);
    writeCorpusMarkdownPref(true);
    expect(readCorpusMarkdownPref()).toBe(true);
    writeCorpusMarkdownPref(false);
    expect(readCorpusMarkdownPref()).toBe(false);
  });
});
