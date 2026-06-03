"""Shared constants for the workspace knowledge service."""

from __future__ import annotations

KNOWLEDGE_DIR = "knowledge"
DB_FILENAME = "knowledge.db"
QDRANT_DIR = "qdrant"
COLLECTION_NAME = "hiro_knowledge"
# Per-workspace embedded graph dir. Backs the Graphiti temporal knowledge graph
# (entities + facts + temporal windows); chunk evidence stays in Qdrant. See
# docs/knowledge-graphiti-pivot-design.md.
GRAPH_DIR = "graph"
# The embedded Kuzu graph DB file that backs Graphiti.
KUZU_DB_FILENAME = "graphiti_kuzu.db"
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_VECTOR_SIZE = 384
# Hybrid retrieval: BM25 sparse vectors fused with the dense vector via RRF. BM25 is
# language-agnostic (FastEmbed ships per-language stopwords incl. Arabic) and ships in the
# already-present ``fastembed`` package — no extra dependency.
DEFAULT_SPARSE_MODEL = "Qdrant/bm25"
# Named-vector keys for the Qdrant collection (dense + sparse live in one collection).
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "bm25"
MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024
PREVIEW_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_FILE_CONCURRENCY = 4
# Shared ingest/search batch size (FastEmbed embed batches, Qdrant upsert batches).
KNOWLEDGE_VECTOR_BATCH_SIZE = 32
DEFAULT_CHUNK_SIZE = 1200
DEFAULT_CHUNK_OVERLAP = 150

KNOWLEDGE_JOB_STARTED = "knowledge.job.started"
KNOWLEDGE_JOB_PROGRESS = "knowledge.job.progress"
KNOWLEDGE_JOB_COMPLETED = "knowledge.job.completed"
KNOWLEDGE_JOB_FAILED = "knowledge.job.failed"
KNOWLEDGE_INGESTED = "knowledge.ingested"
KNOWLEDGE_DELETED = "knowledge.deleted"
# L3 eval — Phase 5c. Streamed by ``services/knowledge/eval_runner.py`` so the
# admin Eval Batch UI can update the per-question table live without polling.
# Same pattern as the ingest job events above (one started, progress per item,
# one completed/failed).
KNOWLEDGE_EVAL_STARTED = "knowledge.eval.started"
KNOWLEDGE_EVAL_SETUP_PROGRESS = "knowledge.eval.setup_progress"   # ingest / graph-build steps
KNOWLEDGE_EVAL_QUESTION_COMPLETED = "knowledge.eval.question_completed"
KNOWLEDGE_EVAL_COMPLETED = "knowledge.eval.completed"
KNOWLEDGE_EVAL_FAILED = "knowledge.eval.failed"
# Terminal cancel (user pressed Cancel in the admin Eval panel). Distinct from
# FAILED so the UI reads it as neutral, not an error.
KNOWLEDGE_EVAL_CANCELLED = "knowledge.eval.cancelled"
# Graph viz — live updates for the admin "Graph" tab. Emitted by Graphiti ingest
# (``GraphitiMemoryService.ingest_chunks``) as episodes are processed so the view can
# pop new elements in real time over the existing ``/knowledge/events`` SSE
# stream (no new transport). ``ingest_completed`` lets the UI run one reconciling
# full export to heal any deltas dropped under the SSE queue cap.
# See docs/knowledge-graph-viz-design.md.
KNOWLEDGE_GRAPH_NODE_UPSERTED = "knowledge.graph.node_upserted"
KNOWLEDGE_GRAPH_EDGE_UPSERTED = "knowledge.graph.edge_upserted"
KNOWLEDGE_GRAPH_INGEST_PROGRESS = "knowledge.graph.ingest_progress"
KNOWLEDGE_GRAPH_INGEST_COMPLETED = "knowledge.graph.ingest_completed"
