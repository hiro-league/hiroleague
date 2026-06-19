/**
 * Pure corpus-list derivations for the Eval picker. The model owns the reactive `corpuses` array
 * and `selectedCorpusId`; these helpers turn that raw list into the benchmark grouping + the
 * filtered dropdown source, with no state of their own (easy to unit-test).
 */
import type { EvalCorpus } from '$lib/api/knowledge';

/** Distinct benchmarks present in the scanned corpuses, in manifest order (first-seen). Knowledge
 *  corpuses carry no benchmark, so this is empty there and the picker shows the flat corpus list. */
export function listBenchmarks(corpuses: EvalCorpus[]): { id: string; label: string }[] {
  const seen = new Map<string, string>();
  for (const c of corpuses) {
    if (c.benchmark && !seen.has(c.benchmark))
      seen.set(c.benchmark, c.benchmark_label || c.benchmark);
  }
  return [...seen].map(([id, label]) => ({ id, label }));
}

/** Corpuses to show in the dropdown — filtered to the given benchmark when set, else the full flat
 *  list (knowledge track, where there's no benchmark grouping). */
export function visibleCorpusesFor(corpuses: EvalCorpus[], benchmarkId: string): EvalCorpus[] {
  return benchmarkId ? corpuses.filter((c) => c.benchmark === benchmarkId) : corpuses;
}
