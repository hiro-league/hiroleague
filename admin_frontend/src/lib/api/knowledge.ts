import { apiRequest, type ApiResponse } from './client';
import type { EvalRunStateData } from '$lib/features/knowledge/shared/knowledge-events';

export type KnowledgeScannedFile = {
  path: string;
  relative_path: string;
  ext: string;
  size_bytes: number;
  supported: boolean;
  already_ingested: boolean;
  disabled_reason: string | null;
};

export type KnowledgeCategory = {
  id: number;
  name: string;
  parent_id: number | null;
};

export type KnowledgeTag = {
  id: number;
  name: string;
};

export type KnowledgeOwnerOption = {
  id: string | number;
  name: string;
};

export type KnowledgeOptionsData = {
  categories: KnowledgeCategory[];
  tags: KnowledgeTag[];
  characters: KnowledgeOwnerOption[];
  users: KnowledgeOwnerOption[];
  // Workspace default for the Ask-tab query-rewrite toggle (knowledge.rewrite.default_on).
  rewrite_default_on?: boolean;
};

export type KnowledgeScanData = {
  root: string;
  files: KnowledgeScannedFile[];
};

export type KnowledgeJobData = {
  job_id: string;
  status: string;
  totals: Record<string, number>;
  errors: Record<string, string>;
  in_flight?: string[];
};

export type KnowledgeJobRecord = {
  id: string;
  created_at: string;
  finished_at: string | null;
  status: string;
  totals: Record<string, number>;
  errors: Record<string, string>;
  params: Record<string, unknown>;
};

export type KnowledgeListJobsData = {
  jobs: KnowledgeJobRecord[];
};

export type KnowledgeDocument = {
  id: string;
  source_uri: string;
  source_type: string;
  mime: string;
  ext: string;
  owner_kind: string;
  owner_id: string;
  category_id: number | null;
  subcategory_id: number | null;
  title: string;
  content_hash: string | null;
  size_bytes: number;
  chunk_count: number | null;
  status: string;
  error: string | null;
  ingested_at: string | null;
  updated_at: string;
  tags: string[];
};

export type KnowledgeListDocumentsData = {
  documents: KnowledgeDocument[];
  total: number;
};

export type KnowledgeChunk = {
  point_id: string;
  document_id: string;
  ord: number;
  text: string;
  heading_path: string | null;
  title: string;
  source_uri: string;
  score?: number;
  [key: string]: unknown;
};

export type KnowledgeDocumentDetailData = {
  document: KnowledgeDocument | null;
  chunks: KnowledgeChunk[];
  chunk_next_offset?: string | null;
};

export type KnowledgeSearchHit = {
  document_id: string;
  point_id: string;
  score: number;
  ord: number;
  text: string;
  heading_path: string | null;
  title: string;
  source_uri: string;
  owner_kind: string;
  owner_id: string;
  category_id: number | null;
  subcategory_id: number | null;
  tags: string[];
};

export type KnowledgeSearchData = {
  query: string;
  hits: KnowledgeSearchHit[];
};

export type KnowledgeSource = {
  ref: number;
  document_id: string;
  point_id: string;
  title: string;
  heading_path: string | null;
  source_uri: string;
  score: number;
  text: string;
  owner_kind: string;
  owner_id: string;
  category_id: number | null;
  subcategory_id: number | null;
  tags: string[];
  // Explain mode (opt-in): per-branch scores + matched terms. Absent/empty in the default path.
  dense_score?: number | null;
  sparse_score?: number | null;
  matched_terms?: string[];
  // Score contract (always present). rerank_score = the reranker's native score (null when no
  // reranker ran); relevance = normalized [0,1]; score_source = 'reranker' | 'rrf' | 'cosine'.
  rerank_score?: number | null;
  relevance?: number | null;
  score_source?: string;
};

export type KnowledgeAnswerData = {
  query: string;
  answer: string;
  sources: KnowledgeSource[];
  elapsed_ms: number;
  model_id: string | null;
  usage: Record<string, number | string | boolean | null>;
  no_results: boolean;
  run_id?: string | null;
  // Query rewrite (opt-in): null/absent when rewrite was off or skipped.
  rewritten_query?: string | null;
  keywords?: string[];
};

/** L3 (Phase 5d) — compare-mode response: both legs side-by-side. The
 *  frontend's discriminator is the presence of `flat`/`graph` on the payload. */
export type KnowledgeAnswerCompareData = {
  query: string;
  flat: KnowledgeAnswerData;   // graph_mode='off' leg
  graph: KnowledgeAnswerData;  // graph_mode='on' leg
  elapsed_ms: number;          // wall-clock for both (legs run concurrently)
  sources_delta: number;       // graph.sources.length - flat.sources.length
  both_no_results: boolean;    // true when neither leg surfaced anything
};

export type KnowledgeGraphMode = 'off' | 'on' | 'compare';

// Per-query temporal lens override for graph_mode 'on'/'compare'. 'default' defers
// to the admin pref (knowledge.graph.temporal_default) and sends no override.
export type KnowledgeGraphTemporal = 'default' | 'current' | 'all';

/** Type guard — distinguish a compare-mode response from a single-leg response. */
export function isAnswerCompareData(
  data: KnowledgeAnswerData | KnowledgeAnswerCompareData
): data is KnowledgeAnswerCompareData {
  return (data as KnowledgeAnswerCompareData).flat !== undefined
    && (data as KnowledgeAnswerCompareData).graph !== undefined;
}

export type KnowledgeFilters = {
  owner_kind?: string | null;
  owner_id?: string | null;
  category_id?: number | null;
  subcategory_id?: number | null;
  document_id?: string | null;
  tags?: string[];
};

export type KnowledgeFilePreviewData = {
  path: string;
  relative_path: string;
  ext: string;
  mime: string | null;
  format: 'markdown' | 'plain-text' | 'unsupported';
  supported: boolean;
  content: string | null;
  disabled_reason: string | null;
  truncated: boolean;
  line_count: number;
  character_count: number;
  estimated_tokens: number;
};

export function scanKnowledgeFolder(folder: string, recursive = true): Promise<ApiResponse<KnowledgeScanData>> {
  return apiRequest<KnowledgeScanData>('/knowledge/scan-folder', {
    method: 'POST',
    body: { folder, recursive },
    timeoutMs: 60000
  });
}

export function pickKnowledgeFolder(initialFolder?: string): Promise<ApiResponse<{ folder: string | null }>> {
  return apiRequest<{ folder: string | null }>('/knowledge/pick-folder', {
    method: 'POST',
    body: { initial_folder: initialFolder ?? null },
    timeoutMs: 300000
  });
}

export function previewKnowledgeFile(path: string): Promise<ApiResponse<KnowledgeFilePreviewData>> {
  return apiRequest<KnowledgeFilePreviewData>('/knowledge/preview-file', {
    method: 'POST',
    body: { path },
    timeoutMs: 60000
  });
}

export function getKnowledgeOptions(): Promise<ApiResponse<KnowledgeOptionsData>> {
  return apiRequest<KnowledgeOptionsData>('/knowledge/options', {
    timeoutMs: 60000
  });
}

export type RerankerDownloadStatus = 'available' | 'downloading' | 'ready' | 'error';

export type LocalRerankerRow = {
  id: string;
  display_name: string;
  backend: string;
  size_label: string;
  languages: string;
  multilingual: boolean;
  description: string;
  downloaded: boolean;
  status: RerankerDownloadStatus;
  error: string | null;
  // Download progress (only while status === 'downloading'). percent is 0–99 then ready→100.
  percent: number | null;
  downloaded_bytes: number | null;
  total_bytes: number | null;
};

export function listKnowledgeRerankers(): Promise<ApiResponse<{ local: LocalRerankerRow[] }>> {
  return apiRequest<{ local: LocalRerankerRow[] }>('/knowledge/rerankers', {
    timeoutMs: 60000
  });
}

export function downloadKnowledgeReranker(
  modelId: string
): Promise<ApiResponse<{ model_id: string; status: RerankerDownloadStatus }>> {
  // Non-blocking on the live workspace: returns immediately with status "downloading"; the
  // caller polls listKnowledgeRerankers for byte progress and the ready/error transition.
  return apiRequest<{ model_id: string; status: RerankerDownloadStatus }>(
    '/knowledge/rerankers/download',
    {
      method: 'POST',
      body: { model_id: modelId },
      timeoutMs: 60000
    }
  );
}

export function cancelKnowledgeReranker(
  modelId: string
): Promise<ApiResponse<{ model_id: string; status: RerankerDownloadStatus }>> {
  return apiRequest<{ model_id: string; status: RerankerDownloadStatus }>(
    '/knowledge/rerankers/cancel',
    {
      method: 'POST',
      body: { model_id: modelId },
      timeoutMs: 60000
    }
  );
}

export function createKnowledgeCategory(
  name: string,
  parentId: number | null = null
): Promise<ApiResponse<KnowledgeCategory>> {
  return apiRequest<KnowledgeCategory>('/knowledge/categories', {
    method: 'POST',
    body: { name, parent_id: parentId },
    timeoutMs: 60000
  });
}

export function createKnowledgeTag(name: string): Promise<ApiResponse<KnowledgeTag>> {
  return apiRequest<KnowledgeTag>('/knowledge/tags', {
    method: 'POST',
    body: { name },
    timeoutMs: 60000
  });
}

export type KnowledgeIngestMetadata = {
  owner_kind: 'system' | 'character' | 'user';
  owner_id: string;
  category_id: number | null;
  subcategory_id: number | null;
  tags: string[];
};

export function ingestKnowledge(
  paths: string[],
  metadata: KnowledgeIngestMetadata
): Promise<ApiResponse<KnowledgeJobData>> {
  return apiRequest<KnowledgeJobData>('/knowledge/ingest', {
    method: 'POST',
    body: { paths, ...metadata, wait: false },
    timeoutMs: 60000
  });
}

export function getKnowledgeJob(jobId: string): Promise<ApiResponse<KnowledgeJobData>> {
  return apiRequest<KnowledgeJobData>(`/knowledge/jobs/${encodeURIComponent(jobId)}`, {
    timeoutMs: 60000
  });
}

export function listKnowledgeJobs(limit = 20): Promise<ApiResponse<KnowledgeListJobsData>> {
  return apiRequest<KnowledgeListJobsData>(`/knowledge/jobs?limit=${encodeURIComponent(String(limit))}`);
}

export function searchKnowledge(
  query: string,
  topK = 10,
  minScore = 0,
  filters: KnowledgeFilters = {}
): Promise<ApiResponse<KnowledgeSearchData>> {
  return apiRequest<KnowledgeSearchData>('/knowledge/search', {
    method: 'POST',
    body: { query, top_k: topK, min_score: minScore, filters },
    timeoutMs: 120000
  });
}

/** L3 (Phase 5e) — kick the synthetic eval batch. Returns the run_id
 *  immediately; progress streams on /api/knowledge/events. */
export type EvalRunRequest = {
  ingest_synthetic?: boolean;
  build_graph?: boolean;
  // 'synthetic' (default .md L3 corpus) | 'adam' (temporal JSONL episode corpus).
  corpus_source?: 'synthetic' | 'adam';
  // Adam path: run only this subset of question ids (empty/undefined = all).
  question_ids?: string[];
  // Legs to compare: any subset of ['flat','graphiti','mix'] (one is fine).
  // Empty/undefined = all three.
  modes?: string[];
  run_id?: string;
};

export function runKnowledgeEval(req: EvalRunRequest = {}): Promise<ApiResponse<{ run_id: string }>> {
  return apiRequest<{ run_id: string }>('/knowledge/eval/run', {
    method: 'POST',
    body: req,
    timeoutMs: 30000  // setup can take a few seconds; the eval itself runs in the background
  });
}

/** L3 — replay the latest eval run's live state for the workspace (server-side
 *  store). The panel calls this on mount so navigation + cross-origin (Vite vs
 *  packaged UI) both show the same run. ``data`` is null when no run exists. */
export function getKnowledgeEvalState(): Promise<ApiResponse<EvalRunStateData | null>> {
  return apiRequest<EvalRunStateData | null>('/knowledge/eval/state', {
    method: 'GET',
    timeoutMs: 15000
  });
}

/** L3 — request cancellation of the in-flight eval run. The runner emits a
 *  terminal ``knowledge.eval.cancelled`` event once it stops. */
export function cancelKnowledgeEval(
  runId?: string | null
): Promise<ApiResponse<{ cancelled: boolean; run_id: string | null }>> {
  return apiRequest<{ cancelled: boolean; run_id: string | null }>('/knowledge/eval/cancel', {
    method: 'POST',
    body: { run_id: runId ?? null },
    timeoutMs: 15000
  });
}

/** One row in the eval question bank (for the checklist). */
export type EvalQuestionItem = {
  id: string;
  category: string;
  subcategory: string;
  question: string;
  requires_graph: boolean;
};

/** List the eval question bank for a corpus (the checklist's source). */
export function listEvalQuestions(
  corpus: 'synthetic' | 'adam' = 'adam'
): Promise<ApiResponse<{ corpus: string; questions: EvalQuestionItem[] }>> {
  return apiRequest<{ corpus: string; questions: EvalQuestionItem[] }>(
    `/knowledge/eval/questions?corpus=${encodeURIComponent(corpus)}`,
    { method: 'GET', timeoutMs: 15000 }
  );
}

/** L3 (Phase 5f) — per-document result inside a batch graph-ingest response. */
export type KnowledgeGraphIngestDocResult = {
  index: number;
  total: number;
  document_id: string;
  document_title: string;
  ok: boolean;
  error: string;
  stats: Record<string, number> | null;
};

/** L3 (Phase 5f) — batch graph-ingest response shape. */
export type KnowledgeGraphIngestBatchData = {
  document_count: number;
  documents: KnowledgeGraphIngestDocResult[];
  totals: Record<string, number>;
};

/** L3 (Phase 5f) — graph-ingest N already-Qdrant-ingested documents.
 *  Synchronous: response returns when the whole batch finishes (or all docs
 *  fail with isolation). Wired into Tab 1's "Also build entity graph" path
 *  so newly ingested docs get auto-graphed in one round-trip. */
export function runKnowledgeGraphIngestBatch(
  documentIds: string[],
  sourceRole: string = 'user_document'
): Promise<ApiResponse<KnowledgeGraphIngestBatchData>> {
  return apiRequest<KnowledgeGraphIngestBatchData>('/knowledge/graph/ingest_batch', {
    method: 'POST',
    body: { document_ids: documentIds, source_role: sourceRole },
    // One LLM extraction call per chunk; a 10-chunk batch is ~10-30s; give it room.
    timeoutMs: 600000
  });
}


export function answerKnowledge(
  query: string,
  topK = 20,
  minScore = 0,
  filters: KnowledgeFilters = {},
  explain = false,
  rewrite = false,
  graphMode: KnowledgeGraphMode = 'off',
  graphTemporal: KnowledgeGraphTemporal = 'default'
): Promise<ApiResponse<KnowledgeAnswerData | KnowledgeAnswerCompareData>> {
  // graph_mode='compare' makes the server run both legs (use_graph=False/True)
  // concurrently and return a compare shape. The route response type is a
  // union; callers use isAnswerCompareData() to discriminate.
  // graph_temporal overrides the admin temporal default for THIS query only;
  // 'default' sends no override so the server uses the pref.
  return apiRequest<KnowledgeAnswerData | KnowledgeAnswerCompareData>('/knowledge/answer', {
    method: 'POST',
    body: {
      query,
      top_k: topK,
      min_score: minScore,
      filters,
      explain,
      rewrite,
      graph_mode: graphMode,
      ...(graphTemporal === 'default' ? {} : { graph_temporal: graphTemporal })
    },
    // Compare runs two legs (still concurrent), so allow a bit more headroom.
    timeoutMs: graphMode === 'compare' ? 240000 : 180000
  });
}

export function listKnowledgeDocuments(filters: {
  status?: string;
  owner_kind?: string;
  owner_id?: string;
  category_id?: number | null;
  subcategory_id?: number | null;
  tag?: string;
  source_type?: string;
  title?: string;
  limit?: number;
  offset?: number;
} = {}): Promise<ApiResponse<KnowledgeListDocumentsData>> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null && String(value).trim() !== '') {
      params.set(key, String(value));
    }
  }
  const suffix = params.toString() ? `?${params.toString()}` : '';
  return apiRequest<KnowledgeListDocumentsData>(`/knowledge/documents${suffix}`);
}

export function getKnowledgeDocument(
  documentId: string,
  options?: { chunkLimit?: number; chunkOffset?: string | null }
): Promise<ApiResponse<KnowledgeDocumentDetailData>> {
  const params = new URLSearchParams();
  if (options?.chunkLimit != null) params.set('chunk_limit', String(options.chunkLimit));
  if (options?.chunkOffset) params.set('chunk_offset', options.chunkOffset);
  const suffix = params.toString() ? `?${params.toString()}` : '';
  return apiRequest<KnowledgeDocumentDetailData>(
    `/knowledge/documents/${encodeURIComponent(documentId)}${suffix}`
  );
}

export function deleteKnowledgeDocument(documentId: string): Promise<ApiResponse<{ document_id: string; deleted: boolean }>> {
  return apiRequest<{ document_id: string; deleted: boolean }>(`/knowledge/documents/${encodeURIComponent(documentId)}`, {
    method: 'DELETE',
    timeoutMs: 60000
  });
}

export function reingestKnowledgeDocument(documentId: string): Promise<ApiResponse<KnowledgeJobData>> {
  return apiRequest<KnowledgeJobData>(`/knowledge/documents/${encodeURIComponent(documentId)}/reingest`, {
    method: 'POST'
  });
}

export function updateKnowledgeDocumentMetadata(
  documentId: string,
  metadata: KnowledgeIngestMetadata
): Promise<ApiResponse<KnowledgeDocument>> {
  return apiRequest<KnowledgeDocument>(`/knowledge/documents/${encodeURIComponent(documentId)}/metadata`, {
    method: 'PATCH',
    body: metadata,
    timeoutMs: 60000
  });
}

// ---------------------------------------------------------------------------
// Graph viz (MVP) — whole-graph export + live event payload shapes.
// Shapes mirror services/knowledge/graph/serialize.py. Edges use source/target
// (not source_id/target_id) so they drop straight into force-graph's link model.
// ---------------------------------------------------------------------------

export type GraphNodeDTO = {
  id: string;
  name: string;
  type: string;
  aliases: string[];
  chunk_ids: string[];
  document_ids: string[];
  // Graphiti's generated entity description (EntityNode.summary). Already serialized by
  // the backend; surfaced in the node detail pane (#5).
  summary: string;
};

export type GraphEdgeDTO = {
  id: string;
  source: string;
  target: string;
  rel_type: string;
  fact: string;
  chunk_ids: string[];
  document_ids: string[];
  // Temporal window: valid_at = became true, invalid_at = stopped being true,
  // expired_at = when the system learned it was superseded (set → retired fact).
  valid_at: string | null;
  invalid_at: string | null;
  expired_at: string | null;
};

export type KnowledgeGraphExportData = {
  nodes: GraphNodeDTO[];
  edges: GraphEdgeDTO[];
  truncated: boolean;
  counts: { nodes: number; edges: number };
};

// Live SSE payloads (knowledge.graph.*).
export type GraphNodeEvent = { node: GraphNodeDTO; is_new: boolean; document_id: string };
export type GraphEdgeEvent = { edge: GraphEdgeDTO; is_new: boolean; document_id: string };
export type GraphIngestProgress = {
  document_id: string;
  chunk_index: number;
  chunk_total: number;
};

export function exportKnowledgeGraph(
  opts: { nodeLimit?: number; edgeLimit?: number } = {}
): Promise<ApiResponse<KnowledgeGraphExportData>> {
  return apiRequest<KnowledgeGraphExportData>('/knowledge/graph/export', {
    method: 'POST',
    body: { node_limit: opts.nodeLimit ?? null, edge_limit: opts.edgeLimit ?? null },
    timeoutMs: 60000
  });
}

// One provenance chunk for a selected node/edge: the real text + its owning document.
export type GraphChunkDetail = {
  id: string;
  text: string;
  document_id: string;
  document_title: string;
  ord: number;
  heading_path: string | null;
  // Episode event time (ISO) — the chunk's semantic `valid_at` (reference/corpus date),
  // not the Qdrant ingest time. Null when there's no episode or no temporal date.
  valid_at: string | null;
};

export type GraphChunksDetailData = { chunks: GraphChunkDetail[] };

/** Resolve a node/edge's chunk_ids → chunk text + document titles (graph detail panel). */
export function fetchGraphChunksDetail(
  chunkIds: string[],
  signal?: AbortSignal
): Promise<ApiResponse<GraphChunksDetailData>> {
  return apiRequest<GraphChunksDetailData>('/knowledge/graph/chunks-detail', {
    method: 'POST',
    body: { chunk_ids: chunkIds },
    timeoutMs: 20000,
    signal
  });
}

export type GraphSearchChunksData = { point_ids: string[] };

/** Graph chunk-text search → point_ids (== chunk_ids) of chunks whose text matches.
 *  The Graph tab maps these onto nodes/edges (via chunk_ids) to highlight matches. */
export function searchGraphChunks(
  text: string,
  signal?: AbortSignal
): Promise<ApiResponse<GraphSearchChunksData>> {
  return apiRequest<GraphSearchChunksData>('/knowledge/graph/search-chunks', {
    method: 'POST',
    body: { text },
    timeoutMs: 20000,
    signal
  });
}
