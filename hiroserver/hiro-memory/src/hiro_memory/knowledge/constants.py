"""The knowledge engine's constants: the Qdrant collection's shape, the default models, batch and chunk sizes."""

from __future__ import annotations

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
DEFAULT_FILE_CONCURRENCY = 4
# Shared ingest/search batch size (FastEmbed embed batches, Qdrant upsert batches).
KNOWLEDGE_VECTOR_BATCH_SIZE = 32
DEFAULT_CHUNK_SIZE = 1200
DEFAULT_CHUNK_OVERLAP = 150
