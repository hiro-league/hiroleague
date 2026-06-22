/**
 * Pure presentational mappers for the eval results UI — verdict glyph → badge variant / label /
 * tooltip, evidence + delta variants, difficulty chip metadata, leg labels, and the corpus-picker
 * ingestion-status dot. Side-effect-free (value in → display value out) so they can be unit-tested
 * and shared across the eval panels without pulling in component state.
 */
import type { EvalCorpus } from '$lib/api/eval';
import type { EvalCategoryStat } from '$lib/features/eval/shared/eval-events';
import { EVAL_LEG_LABEL } from '$lib/features/eval/shared/eval-legs';

/** Corpus-picker ingestion status (memory track) — a colored dot + word before each option:
 *  ⚪ not ingested · 🟡 partially · 🟢 fully ingested. Based on distinct episodes ingested
 *  (`ingested_count`) vs the corpus's episode total; `has_graph` is the fallback "graph exists
 *  but ranges weren't recorded" → treat as fully ingested. */
export function ingestState(c: EvalCorpus): { dot: string; word: string } {
  const total = c.item_count ?? 0;
  const ing = c.ingested_count ?? 0;
  if (total > 0 && ing >= total) return { dot: '🟢', word: 'fully ingested' };
  if (ing > 0) return { dot: '🟡', word: 'partially ingested' };
  if (c.has_graph) return { dot: '🟢', word: 'fully ingested' };
  return { dot: '⚪', word: 'not ingested' };
}

// Difficulty buckets render as a fixed curve (easiest→hardest), not summary-dict order, so the
// by-difficulty table reads top-to-bottom as a difficulty ramp.
export const DIFFICULTY_ORDER = ['medium', 'hard', 'very_hard', 'unspecified'];

export function orderedDifficulty(
  bd: Record<string, EvalCategoryStat>
): Record<string, EvalCategoryStat> {
  const rank = (k: string) => {
    const i = DIFFICULTY_ORDER.indexOf(k);
    return i === -1 ? DIFFICULTY_ORDER.length : i;
  };
  return Object.fromEntries(Object.entries(bd).sort((a, b) => rank(a[0]) - rank(b[0])));
}

/** Difficulty chip shown next to each question. Returns null for unspecified/empty so unlabeled
 *  corpora render no chip. */
export function difficultyMeta(d: string): { label: string; cls: string } | null {
  switch (d) {
    case 'medium':
      return { label: 'medium', cls: 'bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300' };
    case 'hard':
      return { label: 'hard', cls: 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300' };
    case 'very_hard':
      return { label: 'very hard', cls: 'bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300' };
    default:
      return null;
  }
}

/** A correct abstention: 🛇 on a negative-control row, where declining IS the right outcome.
 *  It presents as a Pass (✓ glyph, green, "Pass"); callers render a CircleSlash marker beside the
 *  badge so it still reads as "declined". A plain abstain (non-control) is an answering miss. */
export function isCorrectAbstention(mark: string, negControl = false): boolean {
  return mark === '🛇' && negControl;
}

/** Glyph shown inside the verdict badge. A correct abstention shows ✓ (it scored as a pass); the
 *  abstain marker icon beside the badge carries the "actually declined" nuance. */
export function markGlyph(mark: string, negControl = false): string {
  return isCorrectAbstention(mark, negControl) ? '✓' : mark;
}

/** Color the mark chip. A correct abstention reads green (matches the report's correct-count);
 *  a plain abstain stays neutral. */
export function markVariant(
  mark: string,
  negControl = false
): 'success' | 'warning' | 'destructive' | 'secondary' {
  if (mark === '✓') return 'success';
  if (mark === '◐') return 'warning';
  if (mark === '✗') return 'destructive';
  if (isCorrectAbstention(mark, negControl)) return 'success';
  return 'secondary'; // 🛇 abstain (non-control → a recall/answering miss)
}

/** Tooltip for the judge-mark glyph — the icons aren't self-explanatory (esp. the 🛇 abstain
 *  "stop sign"), so every mark badge carries this as its title. */
export function markTitle(mark: string, negControl = false): string {
  if (mark === '✓') return 'Pass — the answer matches the ideal';
  if (mark === '◐') return 'Partial — partially correct or incomplete';
  if (mark === '✗') return 'Fail — the answer is wrong';
  if (mark === '🛇')
    return negControl
      ? 'Pass — correctly declined on a negative-control question'
      : 'Abstain — declined / “I don’t know” (a recall/answering miss on a normal question)';
  return 'Not judged (judge was off)';
}

/** Short verdict word for the judge line badge. */
export function markLabel(mark: string, negControl = false): string {
  if (mark === '✓') return 'Pass';
  if (mark === '◐') return 'Partial';
  if (mark === '✗') return 'Fail';
  if (mark === '🛇') return negControl ? 'Pass' : 'Abstain';
  return 'Not judged';
}

/** Color the evidence-recall X/Y chip: all gold episodes recalled → green, some → amber, none →
 *  red. ``total === 0`` shouldn't reach a badge (caller renders a dash), but is neutral if it does. */
export function evidenceVariant(
  matched: number,
  total: number
): 'success' | 'warning' | 'destructive' | 'secondary' {
  if (total <= 0) return 'secondary';
  if (matched >= total) return 'success';
  if (matched > 0) return 'warning';
  return 'destructive';
}

export function deltaVariant(delta: string): 'success' | 'warning' | 'secondary' {
  if (delta.startsWith('+')) return 'success';
  if (delta.startsWith('-')) return 'warning';
  return 'secondary';
}

export function legLabel(mode: string): string {
  return EVAL_LEG_LABEL[mode] ?? mode.charAt(0).toUpperCase() + mode.slice(1);
}

/** A leg whose recall went through the graph (memory `recall`, knowledge `graphiti`) has a
 *  retrieval pipeline trace; the flat leg has no graph search, so it has none. */
export function traceableLeg(mode: string): boolean {
  return mode === 'recall' || mode === 'graphiti';
}
