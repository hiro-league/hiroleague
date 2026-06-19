/**
 * Core eval value types + the pure question-row mapper. Kept in a leaf module (no runtime imports
 * from the model/controllers) so both the corpus/data model and the run-lifecycle controller can
 * share them without a circular `*.svelte.ts` import (see svelte-best-practice §11.6).
 */
import type {
  EvalQuestionLeg,
  EvalQuestionPayload,
  EvidenceRecall
} from '$lib/features/eval/shared/eval-events';

/** Eval track — knowledge (document corpus) or memory (turn corpus). */
export type EvalTrack = 'knowledge' | 'memory';

export type EvalStatus =
  | 'idle' // nothing has run yet (or the last run was cleared)
  | 'starting' // POST sent, waiting for the started event
  | 'running' // started event received, question events streaming
  | 'completed' // completed event received
  | 'failed' // failed event received OR transport error
  | 'cancelled'; // user cancelled the run

/** What we render per question (unified across tracks). ``legs`` is keyed by leg name —
 *  flat/graphiti (knowledge) or a single ``recall`` (memory); each leg has the model answer,
 *  the judge mark (or ""), the judge reason, and (memory) the recalled facts. */
export type EvalRow = {
  index: number;
  total: number;
  id: string;
  category: string;
  subcategory: string;
  difficulty: string; // authored difficulty (medium/hard/very_hard); '' when omitted
  question: string;
  requires_graph: boolean;
  track: EvalTrack;
  legs: Record<string, EvalQuestionLeg>;
  delta: string;
  gold: string; // the ideal answer (shown as "Ideal")
  cost_usd: number; // whole-question cost (LLM + reranker), for the live running total
  is_negative_control: boolean; // abstaining is the correct outcome (drives abstain-is-correct)
  answered_at: string; // ISO-8601 UTC timestamp this question finished evaluating ('' if unknown)
  // Evidence recall (LoCoMo corpora) — null on non-LoCoMo corpora and on live rows until the
  // post-run results refresh (it's computed on the read path, not emitted by live events).
  evidence_recall: EvidenceRecall | null;
};

export function rowFromPayload(p: EvalQuestionPayload): EvalRow {
  return {
    index: p.index,
    total: p.total,
    id: p.id,
    category: p.category,
    subcategory: p.subcategory ?? '',
    difficulty: p.difficulty ?? '',
    question: p.question,
    requires_graph: p.requires_graph,
    track: p.track ?? 'knowledge',
    legs: p.legs ?? {},
    delta: p.delta ?? '0',
    gold: p.gold ?? '',
    cost_usd: p.cost_usd ?? 0,
    is_negative_control: p.is_negative_control ?? false,
    answered_at: p.answered_at ?? '',
    evidence_recall: p.evidence_recall ?? null
  };
}
