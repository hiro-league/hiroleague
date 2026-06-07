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

/** Per-leg result inside a ``knowledge.eval.question_completed`` event (unified across tracks).
 *  ``mode`` is ``flat``/``graphiti`` (knowledge) or ``recall`` (memory). ``mark`` is the LLM-judge
 *  verdict glyph, or ``""`` when the judge was off (answers only). ``recalled`` carries the memory
 *  engine's facts (empty for knowledge legs). */
export type EvalQuestionLeg = {
  mode?: string;
  mark: string; // ✓ / ◐ / ✗ / 🛇 — or "" when not judged
  elapsed_ms: number;
  answer_preview: string;
  answer: string; // the model's answer
  run_id: string | null; // ledger run for drill-in
  reason?: string; // judge's one-line justification
  recalled?: string[]; // memory: the recalled facts (for the fold/detail)
};

/** Payload shape of ``knowledge.eval.question_completed`` events (unified).
 *  Both tracks carry ``legs`` (memory has a single ``recall`` leg), the ideal answer (``gold``)
 *  the judge grades against, and ``delta`` (knowledge Δ). ``stale_hit`` flags a recalled fact
 *  that contained a ``must_not_contain`` value (possible superseded leak). */
export type EvalQuestionPayload = {
  run_id?: string;
  index: number;
  total: number;
  id: string;
  category: string;
  subcategory?: string;
  question: string;
  requires_graph: boolean;
  track?: 'knowledge' | 'memory';
  legs?: Record<string, EvalQuestionLeg>;
  delta?: string; // best graph leg vs flat (knowledge)
  gold?: string; // the ideal answer (judge reference / display)
  stale_hit?: boolean; // memory: a recalled fact contained a must_not_contain value
  must_not_contain?: string[];
};

/** Per-category passing counts, keyed by leg (the per-category results table). */
export type EvalCategoryStat = { total: number; pass: Record<string, number> };

/** Payload shape of ``knowledge.eval.completed`` events (aggregate summary).
 *  Knowledge fields (passing/by_category/gate) and memory fields
 *  (remembered_turns/recalled_for/stale_hits) are mutually exclusive by ``track``. */
export type EvalCompletedPayload = {
  run_id: string;
  track?: 'knowledge' | 'memory';
  total_questions: number;
  modes: string[];
  gate: 'proceed' | 'pivot' | 'n/a';
  judged?: boolean; // whether the LLM judge ran (marks present)
  elapsed_ms: number;
  // Knowledge track.
  passing?: Record<string, number>;
  requires_graph_total?: number;
  requires_graph_passing?: Record<string, number>;
  by_category?: Record<string, EvalCategoryStat>;
  // Memory track.
  remembered_turns?: number;
  recalled_for?: number;
  stale_hits?: number;
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
  phase: 'ingest_synthetic' | 'graph_build' | 'build_graph' | 'remember';
  file_count?: number;
  episode_count?: number;
  // Per-episode granularity (absent on the coarse phase-start events).
  index?: number;
  total?: number;
  title?: string;
  snippet?: string;
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
  onCompleted?: () => void;
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
    'knowledge.graph.ingest_completed': () => {
      handlers.onCompleted?.();
    }
  };

  const offs = KNOWLEDGE_GRAPH_EVENT_TYPES.map((type) =>
    knowledgeEventStream.subscribe(type, dispatch[type])
  );
  return () => offs.forEach((off) => off());
}
