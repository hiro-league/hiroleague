"""The knowledge-base engine, shared by the core and EvalHiro.

The Qdrant collection (dense + BM25 named vectors, RRF hybrid search) and its SQLite catalog, Markdown loading and
chunking, the FastEmbed backends, reranking over a handed-in compressor, and the retrieval/answer graph
(``agent``). Import from the submodules; this package imports nothing heavy on its own.
"""
