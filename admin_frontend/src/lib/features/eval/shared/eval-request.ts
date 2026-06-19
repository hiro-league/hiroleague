/**
 * Pure builder for the `POST /eval/run` request body. Extracted from the model's `start`
 * so the per-track field split — and especially the 1-based-inclusive → 0-based offset/limit
 * episode-window math — is isolated and unit-testable, separate from the run lifecycle's `$state`.
 */
import type { EvalCorpus, EvalRunRequest } from '$lib/api/eval';
import type { EvalLeg } from '$lib/features/eval/shared/eval-events';
import type { EvalTrack } from '$lib/features/eval/state/eval-model.svelte';

export type BuildEvalRunRequestParams = {
  track: EvalTrack;
  corpus: Pick<EvalCorpus, 'id' | 'corpus_path' | 'questions_path'>;
  /** Ingest run (setup-only, no questions) vs a questions run against the existing graph. */
  ingesting: boolean;
  judge: boolean;
  /** Explicit, non-empty selection for a questions run; ignored on an ingest run. */
  selectedIds: string[];
  // Knowledge track
  buildGraph: boolean;
  selectedModes: EvalLeg[];
  // Memory track
  clearBefore: boolean;
  /** Remember-phase episode window, 1-based INCLUSIVE (`episodeFrom` ≥ 1; `episodeTo` 0 = to end). */
  episodeFrom: number;
  episodeTo: number;
  questionConcurrency: number;
  answerPromptId: string;
};

export function buildEvalRunRequest(p: BuildEvalRunRequestParams): EvalRunRequest {
  const req: EvalRunRequest = {
    track: p.track,
    corpus_id: p.corpus.id,
    corpus_path: p.corpus.corpus_path,
    questions_path: p.corpus.questions_path,
    // The Ingest button drives ingestion; the Eval button reuses the existing graph.
    ingest_synthetic: p.ingesting,
    judge: p.judge,
    // Ingest is a setup-only batch (no questions); Eval runs the selected questions.
    question_ids: p.ingesting ? [] : [...p.selectedIds]
  };
  if (p.track === 'knowledge') {
    // Rebuild the entity graph only on an ingest run (the "Rebuild graph" option).
    req.build_graph = p.ingesting ? p.buildGraph : false;
    req.modes = [...p.selectedModes];
  } else {
    // Memory track — explicit wipe + remember-phase episode window apply to ingest only. Convert
    // the user-facing 1-based INCLUSIVE from/to to the backend's 0-based offset + count:
    // offset = from-1; count = to-from+1 (≥0). `to` of 0 = "to the end" → null count.
    req.clear_before = p.ingesting ? p.clearBefore : false;
    req.episode_offset = Math.max(0, p.episodeFrom - 1);
    req.episode_limit = p.episodeTo > 0 ? Math.max(0, p.episodeTo - p.episodeFrom + 1) : null;
    req.question_concurrency = p.questionConcurrency;
    // Which named answer-prompt profile drives the answer step ('' ⇒ default profile).
    req.answer_prompt_id = p.answerPromptId;
  }
  return req;
}
