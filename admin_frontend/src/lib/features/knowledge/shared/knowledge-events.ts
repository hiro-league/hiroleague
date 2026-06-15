import type {
  GraphEdgeEvent,
  GraphIngestProgress,
  GraphNodeEvent,
  KnowledgeJobData
} from '$lib/api/knowledge';
import { knowledgeJobFromEvent } from './knowledge-jobs';
import { knowledgeEventStream } from './knowledge-event-stream.svelte';

const KNOWLEDGE_JOB_EVENT_TYPES = [
  'knowledge.job.started',
  'knowledge.job.progress',
  'knowledge.job.completed',
  'knowledge.job.failed'
] as const;

/** Subscribe to knowledge ingest job SSE updates; returns teardown.
 *  Rides the shared per-tab stream (one connection for all knowledge features). */
export function connectKnowledgeJobEvents(onJob: (job: KnowledgeJobData) => void): () => void {
  const handler = (event: MessageEvent) => {
    const job = knowledgeJobFromEvent(event);
    if (job) onJob(job);
  };
  return knowledgeEventStream.subscribeMany(KNOWLEDGE_JOB_EVENT_TYPES, handler);
}

// ---------------------------------------------------------------------------
// L3 (Phase 5e) — eval batch event subscriber. Same SSE stream as above,
// different event types — the controller dispatches on event.type.
// ---------------------------------------------------------------------------

/** The selectable eval legs (retrieval modes). */
export type EvalLeg = 'flat' | 'graphiti';

/** Payload shape of ``knowledge.eval.started`` events. */
export type EvalStartedPayload = {
  run_id: string;
  total_questions: number;
  filters: Record<string, unknown>;
  // Selected legs — the UI renders one column per leg, in this order.
  modes: string[];
};

/** One recalled memory item — a fact (rich temporal/source metadata) or a widened-scope
 *  entity/episode (text only). The fact table renders these columns. ``memory`` is always the
 *  display text; the rest is best-effort and may be blank/absent depending on ``kind``. */
export type RecalledFact = {
  memory: string; // display text (dated fact / entity summary / episode body)
  kind?: 'fact' | 'entity' | 'episode';
  fact?: string; // raw fact text (without the appended date)
  valid_at?: string; // ISO date the fact became true
  invalid_at?: string; // ISO date the fact was invalidated (superseded)
  superseded?: boolean; // dropped by the 'current' temporal lens
  chunk_id?: string; // supporting episode/chunk id
  name?: string; // fact: relationship / edge type (e.g. WORKS_AT); entity: the entity name
  source_uuid?: string; // subject entity uuid
  target_uuid?: string; // object entity uuid
  uuid?: string; // fact edge / entity / episode uuid
  score?: number | null; // relevance score when the backend exposes it (now also entities/episodes)
  // Entity-only (kind === 'entity'): the ontology type (Person/Org/…) and the raw attribute summary.
  entity_type?: string;
  summary?: string;
};

/** One gold evidence episode for a question (from the LoCoMo sidecar) + whether the recalled
 *  context covered it. ``matched_via`` is the kind of recalled item that covered it
 *  ('episode' | 'fact' | 'entity'), '' when missed. ``text``/``speaker``/``when`` are best-effort
 *  (blank if the corpus episodes file wasn't readable). */
export type EvidenceRecallItem = {
  episode_id: string; // full corpus episode id (e.g. locomo_conv_43_d6_15)
  short_id: string; // corpus prefix trimmed (e.g. d6_15)
  dia_id?: string; // LoCoMo dialogue id (e.g. D6:15) when the sidecar maps one
  speaker?: string;
  text?: string; // the episode body
  when?: string; // ISO timestamp of the episode
  matched: boolean; // recalled context covered this gold episode
  matched_via?: string; // 'episode' | 'fact' | 'entity' — how it matched; '' when missed
  score?: number | null; // best matching recalled item's score
};

/** Per-question evidence recall (LoCoMo calculation): X of Y gold evidence episodes covered by the
 *  recalled context. Absent on non-LoCoMo corpora (no sidecar). */
export type EvidenceRecall = {
  matched: number; // X — gold evidence episodes the recall covered
  total: number; // Y — total gold evidence episodes for the question
  items: EvidenceRecallItem[];
};

/** Per-leg result inside a ``knowledge.eval.question_completed`` event (unified across tracks).
 *  ``mode`` is ``flat``/``graphiti`` (knowledge) or ``recall`` (memory). ``mark`` is the LLM-judge
 *  verdict glyph, or ``""`` when the judge was off (answers only). ``recalled`` carries the memory
 *  engine's facts (empty for knowledge legs). ``cost_usd`` is this leg's LLM+reranker cost. */
export type EvalQuestionLeg = {
  mode?: string;
  mark: string; // ✓ / ◐ / ✗ / 🛇 — or "" when not judged
  elapsed_ms: number;
  answer_preview: string;
  answer: string; // the model's answer
  run_id: string | null; // ledger run for drill-in
  reason?: string; // judge's one-line justification
  recalled?: RecalledFact[]; // memory: the recalled facts (for the fold/detail table)
  cost_usd?: number; // this leg's folded cost (LLM + reranker; embeddings unpriced)
  // Judge extras (shown in the Judge section): answer grounded in the context, whether the recalled
  // context held what was needed (false ⇒ recall-miss not answering-miss), and the verified recalled
  // line(s) the judge quoted as supporting the answer ("" when none / knowledge legs pass no context).
  grounded?: boolean;
  recall_sufficient?: boolean;
  evidence?: string;
};

/** Payload shape of ``knowledge.eval.question_completed`` events (unified).
 *  Both tracks carry ``legs`` (memory has a single ``recall`` leg), the ideal answer (``gold``)
 *  the judge grades against, and ``delta`` (knowledge Δ). */
export type EvalQuestionPayload = {
  run_id?: string;
  index: number;
  total: number;
  id: string;
  category: string;
  subcategory?: string;
  difficulty?: string; // authored difficulty (medium/hard/very_hard); '' when the corpus omits it
  question: string;
  requires_graph: boolean;
  track?: 'knowledge' | 'memory';
  legs?: Record<string, EvalQuestionLeg>;
  delta?: string; // best graph leg vs flat (knowledge)
  gold?: string; // the ideal answer (judge reference / display)
  cost_usd?: number; // whole-question cost (sum of leg runs + judge run)
  // Negative control (expected_kind: abstain) — abstaining is the correct outcome here. Drives
  // the abstain-is-correct rule in the report's Correct %/Score % (an abstain on a normal
  // question is a miss, not a pass).
  is_negative_control?: boolean;
  // ISO-8601 UTC timestamp when this question finished evaluating (for the "Time" column).
  answered_at?: string;
  // Evidence recall (LoCoMo corpora) — read-path enrichment, so present on saved-results reads but
  // not on live question_completed events (which fill it in on the post-run results refresh).
  evidence_recall?: EvidenceRecall | null;
};

/** Per-bucket breakdown, keyed by leg (the per-category / per-difficulty report tables).
 *  ``groups`` is the raw mark distribution; ``correct`` applies the negative-control rule
 *  (pass + correct-abstain); ``score`` gives a partial half a point. */
export type EvalMarkGroups = { pass: number; partial: number; fail: number; abstain: number };
export type EvalCategoryStat = {
  total: number;
  groups: Record<string, EvalMarkGroups>;
  correct: Record<string, number>;
  score: Record<string, number>;
  // Judged rows the judge flagged recall-sufficient (the recalled context held the answer).
  recall_ok: Record<string, number>;
  // Evidence recall (memory / LoCoMo): gold-evidence episodes matched / total, summed over this
  // bucket's rows. Single recall-leg concept (not per-leg). Absent / 0 on the knowledge track and
  // on non-LoCoMo memory corpora.
  evidence_matched?: number;
  evidence_total?: number;
};

/** Payload shape of ``knowledge.eval.completed`` events (aggregate summary).
 *  Knowledge fields (passing/by_category/gate) and memory fields
 *  (remembered_turns/recalled_for) are mutually exclusive by ``track``. */
export type EvalCompletedPayload = {
  run_id: string;
  track?: 'knowledge' | 'memory';
  total_questions: number;
  modes: string[];
  gate: 'proceed' | 'pivot' | 'n/a';
  judged?: boolean; // whether the LLM judge ran (marks present)
  elapsed_ms: number;
  // Knowledge track.
  passing?: Record<string, number>; // CORRECT count per leg (pass + correct-abstain)
  requires_graph_total?: number;
  requires_graph_passing?: Record<string, number>;
  by_category?: Record<string, EvalCategoryStat>;
  // Same shape as by_category, bucketed by authored difficulty (medium/hard/very_hard/unspecified).
  by_difficulty?: Record<string, EvalCategoryStat>;
  // Overall per-leg mark distribution + graded score (partial = ½ pt) — the summary card metrics.
  groups?: Record<string, EvalMarkGroups>;
  scoring?: Record<string, number>;
  // Memory track.
  remembered_turns?: number;
  recalled_for?: number;
  // Cost (LLM + reranker; embeddings unpriced). ``ingest_cost_usd`` is 0 for knowledge
  // (multi-run ingest cost deferred); ``questions_cost_usd`` = sum of per-question costs.
  questions_cost_usd?: number;
  ingest_cost_usd?: number;
  total_cost_usd?: number;
  // Memory track: the remember-phase ingest Graph Run id (null on a subset re-run that didn't
  // re-ingest). Lets the panel open the ingest pipeline trace for the corpus build.
  ingest_run_id?: string | null;
};

/** Payload shape of ``knowledge.eval.failed`` events. */
export type EvalFailedPayload = {
  run_id: string;
  error: string;
};

/** Payload shape of ``knowledge.eval.cancelled`` events (user pressed Cancel). */
export type EvalCancelledPayload = {
  run_id: string;
};

/** Payload shape of ``knowledge.eval.setup_progress`` events.
 *  Fires once per phase AND once per episode (index/total set on the per-episode
 *  events) so the live terminal can show fine-grained ingest/graph-build progress. */
export type EvalSetupProgressPayload = {
  run_id?: string;
  phase: 'ingest_synthetic' | 'graph_build' | 'build_graph' | 'remember' | 'remember_done';
  file_count?: number;
  episode_count?: number;
  // Per-episode granularity (absent on the coarse phase-start events).
  index?: number;
  total?: number;
  // Memory remember phase — ABSOLUTE 1-based episode numbers so the activity shows the real
  // episode ("episode 11"), not a window-relative counter. ``episode_no`` is the current turn;
  // ``from``/``to`` are the batch's first/last episode (on the phase-start line).
  episode_no?: number;
  from?: number;
  to?: number;
  title?: string;
  snippet?: string;
  // Folded ingest (graph-build) cost in USD — set on the 'remember_done' line so the panel
  // shows ingestion cost LIVE, before the terminal `completed` summary arrives.
  ingest_cost_usd?: number;
  // The remember-phase ingest Graph Run id (on the 'remember_done' line) — lets the panel open
  // the ingest pipeline trace even before the terminal summary lands.
  ingest_run_id?: string;
};

export type EvalEventHandlers = {
  onStarted?: (p: EvalStartedPayload) => void;
  onSetupProgress?: (p: EvalSetupProgressPayload) => void;
  onQuestion?: (p: EvalQuestionPayload) => void;
  onCompleted?: (p: EvalCompletedPayload) => void;
  onFailed?: (p: EvalFailedPayload) => void;
  onCancelled?: (p: EvalCancelledPayload) => void;
};

const KNOWLEDGE_EVAL_EVENT_TYPES = [
  'knowledge.eval.started',
  'knowledge.eval.setup_progress',
  'knowledge.eval.question_completed',
  'knowledge.eval.completed',
  'knowledge.eval.failed',
  'knowledge.eval.cancelled'
] as const;

/** Subscribe to L3 eval batch SSE events; returns teardown.
 *  Rides the shared per-tab stream (one connection for all knowledge features). */
export function connectKnowledgeEvalEvents(handlers: EvalEventHandlers): () => void {
  const parse = <T>(event: MessageEvent): T | null => {
    try {
      return JSON.parse(event.data) as T;
    } catch {
      // Malformed payload — drop it rather than crashing the table render.
      return null;
    }
  };

  const dispatch: Record<string, (e: MessageEvent) => void> = {
    'knowledge.eval.started': (e) => {
      const p = parse<EvalStartedPayload>(e);
      if (p && handlers.onStarted) handlers.onStarted(p);
    },
    'knowledge.eval.setup_progress': (e) => {
      const p = parse<EvalSetupProgressPayload>(e);
      if (p && handlers.onSetupProgress) handlers.onSetupProgress(p);
    },
    'knowledge.eval.question_completed': (e) => {
      const p = parse<EvalQuestionPayload>(e);
      if (p && handlers.onQuestion) handlers.onQuestion(p);
    },
    'knowledge.eval.completed': (e) => {
      const p = parse<EvalCompletedPayload>(e);
      if (p && handlers.onCompleted) handlers.onCompleted(p);
    },
    'knowledge.eval.failed': (e) => {
      const p = parse<EvalFailedPayload>(e);
      if (p && handlers.onFailed) handlers.onFailed(p);
    },
    'knowledge.eval.cancelled': (e) => {
      const p = parse<EvalCancelledPayload>(e);
      if (p && handlers.onCancelled) handlers.onCancelled(p);
    }
  };

  const offs = KNOWLEDGE_EVAL_EVENT_TYPES.map((type) =>
    knowledgeEventStream.subscribe(type, dispatch[type])
  );
  return () => offs.forEach((off) => off());
}

/** Replay snapshot from ``GET /knowledge/eval/state`` — the server-side run
 *  store the panel hydrates from on mount (mid-run replay + cross-origin
 *  consistency between the Vite and packaged UIs). ``null`` = no run / idle. */
export type EvalRunStateData = {
  run_id: string;
  corpus_source: string;
  track?: 'knowledge' | 'memory';
  status: 'starting' | 'running' | 'completed' | 'failed' | 'cancelled';
  total_questions: number;
  modes: string[];
  filters: Record<string, unknown>;
  setup_events: EvalSetupProgressPayload[];
  rows: EvalQuestionPayload[];
  summary: EvalCompletedPayload | null;
  failure_message: string | null;
  cancel_requested: boolean;
};

// ---------------------------------------------------------------------------
// Graph viz (MVP) — live node/edge updates for the admin "Graph" tab. Same
// SSE stream, separate event types — the panel pops new nodes/edges as the
// graph builds. See docs/knowledge-graph-viz-design.md.
// ---------------------------------------------------------------------------

export type KnowledgeGraphEventHandlers = {
  onNode?: (p: GraphNodeEvent) => void;
  onEdge?: (p: GraphEdgeEvent) => void;
  onProgress?: (p: GraphIngestProgress) => void;
  // ``group_id`` scopes the completion to a partition (mirrors ingest_progress) so the panel
  // only clears its "ingesting…" status / reconciles when it's viewing that group. Absent on
  // legacy emits ⇒ treat as global (clear unconditionally).
  onCompleted?: (group_id?: string | null) => void;
};

const KNOWLEDGE_GRAPH_EVENT_TYPES = [
  'knowledge.graph.node_upserted',
  'knowledge.graph.edge_upserted',
  'knowledge.graph.ingest_progress',
  'knowledge.graph.ingest_completed'
] as const;

/** Subscribe to L3 graph-viz SSE events; returns teardown.
 *  Rides the shared per-tab stream (one connection for all knowledge features). */
export function connectKnowledgeGraphEvents(handlers: KnowledgeGraphEventHandlers): () => void {
  const parse = <T>(event: MessageEvent): T | null => {
    try {
      return JSON.parse(event.data) as T;
    } catch {
      // Malformed payload — drop it; keep the stream alive.
      return null;
    }
  };

  const dispatch: Record<string, (e: MessageEvent) => void> = {
    'knowledge.graph.node_upserted': (e) => {
      const p = parse<GraphNodeEvent>(e);
      if (p && handlers.onNode) handlers.onNode(p);
    },
    'knowledge.graph.edge_upserted': (e) => {
      const p = parse<GraphEdgeEvent>(e);
      if (p && handlers.onEdge) handlers.onEdge(p);
    },
    'knowledge.graph.ingest_progress': (e) => {
      const p = parse<GraphIngestProgress>(e);
      if (p && handlers.onProgress) handlers.onProgress(p);
    },
    'knowledge.graph.ingest_completed': (e) => {
      const p = parse<{ group_id?: string | null }>(e);
      handlers.onCompleted?.(p?.group_id ?? null);
    }
  };

  const offs = KNOWLEDGE_GRAPH_EVENT_TYPES.map((type) =>
    knowledgeEventStream.subscribe(type, dispatch[type])
  );
  return () => offs.forEach((off) => off());
}
