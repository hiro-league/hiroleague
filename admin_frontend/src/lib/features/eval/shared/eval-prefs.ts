/**
 * Eval setup/run preferences — pure localStorage read/write helpers, extracted from the model so
 * the persistence plumbing (JSON-map parsing + per-track / per-corpus keying) lives in one tested
 * place. No Svelte runes here: these are plain functions the model calls when reading initial
 * state or writing through a setter.
 */
import { PREF_KEYS } from '$lib/preferences/keys';
import { readLocalString, writeLocalString } from '$lib/preferences/storage';
import type { EvalTrack } from '$lib/features/eval/state/eval-model.svelte';

/** Read a persisted non-negative integer setting, falling back when unset/invalid. */
export function readEvalInt(key: string, fallback: number): number {
  const n = parseInt(readLocalString(key) ?? '', 10);
  return Number.isFinite(n) && n >= 0 ? n : fallback;
}

/**
 * Per-track last-selected corpus (localStorage JSON map `{ track: corpusId }`). Survives a fresh
 * page load so the user lands back on the corpus they were working with — if it's still in the
 * scanned list; otherwise the caller falls back to the first corpus.
 */
export function readCorpusPref(track: EvalTrack): string {
  try {
    const raw = readLocalString(PREF_KEYS.evalCorpus);
    if (!raw) return '';
    return (JSON.parse(raw) as Partial<Record<EvalTrack, string>>)[track] ?? '';
  } catch {
    return '';
  }
}

export function writeCorpusPref(track: EvalTrack, id: string): void {
  let map: Partial<Record<EvalTrack, string>> = {};
  try {
    const raw = readLocalString(PREF_KEYS.evalCorpus);
    if (raw) map = JSON.parse(raw) as Partial<Record<EvalTrack, string>>;
  } catch {
    map = {};
  }
  if (id) map[track] = id;
  else delete map[track];
  writeLocalString(PREF_KEYS.evalCorpus, JSON.stringify(map));
}

/**
 * Per-corpus last-used answer-prompt profile (localStorage JSON map `{ corpusId: profileId }`).
 * Keyed by corpus id (not track) so each corpus remembers the prompt it was last evaluated with.
 */
export function readAnswerPromptPref(corpusId: string): string {
  if (!corpusId) return '';
  try {
    const raw = readLocalString(PREF_KEYS.evalAnswerPrompt);
    if (!raw) return '';
    return (JSON.parse(raw) as Record<string, string>)[corpusId] ?? '';
  } catch {
    return '';
  }
}

export function writeAnswerPromptPref(corpusId: string, id: string): void {
  if (!corpusId) return;
  let map: Record<string, string> = {};
  try {
    const raw = readLocalString(PREF_KEYS.evalAnswerPrompt);
    if (raw) map = JSON.parse(raw) as Record<string, string>;
  } catch {
    map = {};
  }
  if (id) map[corpusId] = id;
  else delete map[corpusId];
  writeLocalString(PREF_KEYS.evalAnswerPrompt, JSON.stringify(map));
}

/** Corpus tab: Markdown rendering mode for episode bodies (persisted across reloads). */
export function readCorpusMarkdownPref(): boolean {
  return readLocalString(PREF_KEYS.evalCorpusMarkdown) === '1';
}

export function writeCorpusMarkdownPref(enabled: boolean): void {
  writeLocalString(PREF_KEYS.evalCorpusMarkdown, enabled ? '1' : '0');
}
