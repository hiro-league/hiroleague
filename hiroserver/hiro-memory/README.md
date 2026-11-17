# hiro-memory

Hiro's memory engine, shared by the HiroLeague core and EvalHiro: the Graphiti temporal graph on Kuzu,
conversation memory and its recall agent, the knowledge base, and the run ledger that prices and traces every step.

The library never imports the core. Whoever uses it hands in what it needs: the model clients (a
`model_builder`), the embedder and reranker, the settings values, and the callbacks for events and AI usage.

## The knowledge base (`hiro_memory.knowledge`)

- **The collection:** `vector_store.KnowledgeVectorStore`, embedded Qdrant with two named vectors per chunk (`dense`,
  and `bm25` with IDF), dense-only or RRF hybrid search; `catalog_store.CatalogStore`, the SQLite catalog of
  documents, jobs, categories and tags.
- **The index:** `index.KnowledgeIndex`, the catalog, the collection, the dense and BM25 embedders and the loaders as
  one: `ingest_file` (load → chunk → embed both → upsert vectors and catalog row; `settings.KnowledgeChunkingSettings`
  says how to chunk), `remove_document`, `get_document`, and the retrieval the answer graph drives. The core's
  `KnowledgeService` is one; EvalHiro holds one per corpus.
- **Ingest pieces:** `loaders` (Markdown), `chunker` (heading-aware chunks, the embedded breadcrumb), `scanner`,
  `embedding_backends` (`FastEmbedBackend` dense, `SparseFastEmbedBackend` = FastEmbed `Qdrant/bm25`, and the
  backend protocols).
- **The knowledge graph:** `graph_build.build_document_graph(service, index, document_ids, ...)` (one Graphiti
  episode per chunk, its uuid the chunk's point id, into the service's group) and `remove_document_episodes`. The owner
  builds and closes the `GraphitiMemoryService`.
- **Reranking:** `rerank.rerank_hits(compressor, query, hits, scores_calibrated=, top_n=)` over a LangChain
  `BaseDocumentCompressor` the owner picked.
- **The retrieval/answer graph:** `agent.KnowledgeAgentGraph(sinks).build(config)` (retrieve and answer) or
  `.build_retrieval(config)` (retrieval only). `config` is an `agent.KnowledgeGraphConfig` of what the owner hands
  in: the retrieval engine (`KnowledgeRetriever`), the settings values (`settings.KnowledgeSettings`), the answering
  and rewrite models (`KnowledgeModel`), the reranker (`KnowledgeReranker`), the graph leg (`KnowledgeGraphLeg`, with
  `graph_session.open_graphiti_session`), and the usage emitter. `answer` runs one answer as the core always has:
  `answer_state` (the initial state), `run_answer` (in its own ledger run, or nested under an open one; `ledger_runner`
  opens it) and `answer_result`.

The owner keeps where the files live, its preferences, its model catalog and credentials, and local model downloads:
the library depends on neither torch, sentence-transformers nor flashrank.
