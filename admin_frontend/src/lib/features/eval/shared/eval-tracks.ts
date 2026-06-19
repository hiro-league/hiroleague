import type { EvalTrack } from '$lib/features/eval/state/eval-model.svelte';

/**
 * Declarative per-track capability table. The Eval page renders one panel driven by a `track`
 * discriminator (memory vs knowledge); historically every divergence was a scattered inline
 * `isMemory` ternary, so the meaning of each branch was opaque and adding a 3rd track meant
 * hunting them down. This object is the single catalog of what differs per track — each field is
 * a NAMED capability the panel reads (`cfg.showDelta`, `cfg.hasCorpusReview`, …) instead of
 * re-deciding `isMemory` at the call site.
 *
 * Pure data: every value is a function of the track alone (no model/run state). State-dependent
 * branches (which model field arms a wipe, what the live summary's own track is) stay inline.
 */
export type EvalTrackConfig = {
  /** The track this config describes. Use `cfg.track === 'memory'` for the few state-coupled spots. */
  track: EvalTrack;
  /** Human label for the track. */
  label: string;

  // --- Results table columns ----------------------------------------------------------------
  /** Knowledge only: Δ column (best graph leg vs flat) — memory is a single recall leg. */
  showDelta: boolean;
  /** Memory only: sortable recall-sufficiency flag column + the matching answers-filter dropdown. */
  showRecallColumn: boolean;
  /** Memory only: evidence-recall column (gold evidence episodes covered, X/Y; LoCoMo corpora). */
  showEvidenceColumn: boolean;
  /** Memory only: verdict ("answer type") column, split out of the recall-answer cell. */
  showAnswerTypeColumn: boolean;

  // --- Sub-tabs / report sections -----------------------------------------------------------
  /** Memory only: the Corpus transcript sub-tab. */
  hasCorpusReview: boolean;
  /** Memory only: benchmark grouping + the by-benchmark report (totals + per-corpus drill-in). */
  hasBenchmarks: boolean;

  // --- Setup options ------------------------------------------------------------------------
  /** Memory only: episode From..To window + Clear Graph (knowledge shows the Rebuild-graph toggle). */
  hasEpisodeWindow: boolean;
  /** Knowledge only: the flat/graphiti leg selector. */
  hasLegSelector: boolean;
  /** Memory only: the parallel-question concurrency cap. */
  hasQuestionConcurrency: boolean;
  /** Memory only: the named answer-prompt profile picker. */
  hasAnswerPrompt: boolean;

  // --- Ingestion / persistence / actions ----------------------------------------------------
  /** Memory only: per-episode ingest status (corpus-dropdown dot, cumulative ingest cost, pipeline). */
  tracksIngestion: boolean;
  /** Memory only: results persist to disk, so Clear is a destructive on-disk delete (gated by confirm). */
  persistsResults: boolean;
  /** Memory only: export saved results as a LoCoMo-compatible QA JSON file. */
  canExportLocomo: boolean;

  // --- Labels -------------------------------------------------------------------------------
  /** Ingest button tooltip (the action differs: remember an episode window vs ingest + rebuild). */
  ingestHint: string;
  /** Clear button label (memory deletes saved results; knowledge resets the in-view run). */
  clearLabel: string;
};

const MEMORY: EvalTrackConfig = {
  track: 'memory',
  label: 'Memory',
  showDelta: false,
  showRecallColumn: true,
  showEvidenceColumn: true,
  showAnswerTypeColumn: true,
  hasCorpusReview: true,
  hasBenchmarks: true,
  hasEpisodeWindow: true,
  hasLegSelector: false,
  hasQuestionConcurrency: true,
  hasAnswerPrompt: true,
  tracksIngestion: true,
  persistsResults: true,
  canExportLocomo: true,
  ingestHint: 'Remember the chosen episode window into the graph (no questions)',
  clearLabel: 'Clear results'
};

const KNOWLEDGE: EvalTrackConfig = {
  track: 'knowledge',
  label: 'Knowledge',
  showDelta: true,
  showRecallColumn: false,
  showEvidenceColumn: false,
  showAnswerTypeColumn: false,
  hasCorpusReview: false,
  hasBenchmarks: false,
  hasEpisodeWindow: false,
  hasLegSelector: true,
  hasQuestionConcurrency: false,
  hasAnswerPrompt: false,
  tracksIngestion: false,
  persistsResults: false,
  canExportLocomo: false,
  ingestHint: 'Ingest the corpus (+ rebuild the graph if checked)',
  clearLabel: 'Clear'
};

const EVAL_TRACK_CONFIG: Record<EvalTrack, EvalTrackConfig> = {
  memory: MEMORY,
  knowledge: KNOWLEDGE
};

/** The capability config for a track. */
export function trackConfig(track: EvalTrack): EvalTrackConfig {
  return EVAL_TRACK_CONFIG[track];
}
