"""Shared constants for the workspace knowledge service."""

from __future__ import annotations

KNOWLEDGE_DIR = "knowledge"
DB_FILENAME = "knowledge.db"
QDRANT_DIR = "qdrant"
COLLECTION_NAME = "hiro_knowledge"
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
