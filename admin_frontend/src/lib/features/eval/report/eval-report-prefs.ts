/**
 * Eval Reports tab — persisted expand/collapse for each collapsible report section.
 *
 * The Reports tab re-mounts on every sub-tab switch and rebuilds its breakdown tables on every
 * corpus change, so each table's local collapse state reset to "expanded" every time. This stores
 * one collapsed flag per *stable* section id (localStorage) so the tab reopens the way the user
 * left it — independent of the tables' dynamic, benchmark-/corpus-derived titles. Mirrors the
 * Graph-options sections prefs (`knowledge-graph-prefs.ts`).
 */
import { PREF_KEYS } from '$lib/preferences/keys';
import { readLocalString, writeLocalString } from '$lib/preferences/storage';

/** Stable ids for the collapsible report sections on the Reports tab. */
export type EvalReportSection =
  | 'benchCategory' // benchmark overview · Total Results by Category
  | 'benchDifficulty' // benchmark overview · Total Results by Difficulty
  | 'benchByCorpus' // benchmark overview · per-corpus summary table
  | 'detailCategory' // selected corpus · Results by category
  | 'detailDifficulty'; // selected corpus · Results by difficulty

/** `true` ⇒ the section is collapsed. */
export type EvalReportSections = Record<EvalReportSection, boolean>;

/** Every section starts expanded (matches the previous always-open-on-mount behaviour). */
const DEFAULTS: EvalReportSections = {
  benchCategory: false,
  benchDifficulty: false,
  benchByCorpus: false,
  detailCategory: false,
  detailDifficulty: false
};

export function readEvalReportSections(): EvalReportSections {
  const raw = readLocalString(PREF_KEYS.evalReportSections);
  if (!raw) return { ...DEFAULTS };
  try {
    const p = JSON.parse(raw) as Partial<EvalReportSections>;
    const out = { ...DEFAULTS };
    for (const key of Object.keys(DEFAULTS) as EvalReportSection[]) {
      if (typeof p[key] === 'boolean') out[key] = p[key] as boolean;
    }
    return out;
  } catch {
    return { ...DEFAULTS };
  }
}

export function writeEvalReportSections(s: EvalReportSections): void {
  writeLocalString(PREF_KEYS.evalReportSections, JSON.stringify(s));
}
