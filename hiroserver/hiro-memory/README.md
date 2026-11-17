# hiro-memory

Hiro's memory engine, shared by the HiroLeague core and EvalHiro: the Graphiti temporal graph on Kuzu,
conversation memory and its recall agent, the knowledge base, and the run ledger that prices and traces every step.

The library never imports the core. Whoever uses it hands in what it needs: the model clients (a
`model_builder`), the embedder and reranker, the settings values, and the callbacks for events and AI usage.

## The knowledge base (`hiro_memory.knowledge`)

- **The collection:** `vector_store.KnowledgeVectorStore`, embedded Qdrant with two named vectors per chunk (`dense`,
  and `bm25` with IDF), dense-only or RRF hybrid search; `catalog_store.CatalogStore`, the SQLite catalog of
  documents, jobs, categories and tags.
- **Ingest pieces:** `loaders` (Markdown), `chunker` (heading-aware chunks, the embedded breadcrumb), `scanner`,
  `embedding_backends` (`FastEmbedBackend` dense, `SparseFastEmbedBackend` = FastEmbed `Qdrant/bm25`, and the
  backend protocols).
- **Reranking:** `rerank.rerank_hits(compressor, query, hits, scores_calibrated=, top_n=)` over a LangChain
  `BaseDocumentCompressor` the owner picked.
- **The retrieval/answer graph:** `agent.KnowledgeAgentGraph(sinks).build(config)` (retrieve and answer) or
  `.build_retrieval(config)` (retrieval only). `config` is an `agent.KnowledgeGraphConfig` of what the owner hands
  in: the retrieval engine (`KnowledgeRetriever`), the settings values (`settings.KnowledgeSettings`), the answering
  and rewrite models (`KnowledgeModel`), the reranker (`KnowledgeReranker`), the graph leg (`KnowledgeGraphLeg`, with
  `graph_session.open_graphiti_session`), and the usage emitter. `ledger_runner` opens the ledger run of a
  standalone answer.

The owner keeps where the files live, its preferences, its model catalog and credentials, and local model downloads:
the library depends on neither torch, sentence-transformers nor flashrank.
