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
