/** Field hints lifted out of section markup for readability and copy review. */

export const GRAPH_EXTRACTION_COPY = {
  entityOntology:
    'Which entity types extraction may use. Open = no predefined types; the model extracts freely (everything becomes a generic Entity) — broadest recall, captures activities, interests, media, and preferences. Typed = pin the 5-type vocabulary (Person / Place / Organization / Event / Object) — more precise, but drops first-person facts that don\'t fit those types. Changing this rebuilds the graph at the next ingest, so a re-ingest is required to take effect.',
  customInstructions:
    'Optional domain-generic guidance injected verbatim into Graphiti\'s entity + fact extraction prompts. Use it to steer what gets captured — e.g. capture first-person preferences, goals, habits and activities as facts even when only the speaker is named, treating the activity / topic / object as the second entity. Keep it generic (no dataset-specific rules). Blank = none. Applied at ingest, so a re-ingest is required to take effect.',
  extractionModel:
    'The heavy LLM Graphiti uses to read each chunk/turn and pull out entities + facts. Must be structured-output-capable. Null falls back to the answering model, then default chat.',
  extractionProfile:
    'Tuning profile (temperature / max-tokens / thinking) for the extraction model. Ships deterministic so extraction stays repeatable across runs.',
  smallModel:
    'Cheaper model for Graphiti\'s sub-steps — node dedupe, entity summaries, timestamps. Null falls back to the extraction model.',
  smallProfile: 'Tuning profile for the cheaper sub-step model (dedupe / summaries / timestamps).',
  embedderModel:
    'Embeds entity names + facts into the graph. Null shares the knowledge embedding model. Shared across memory + knowledge graph data — changing it re-indexes everything.'
} as const;

export const GRAPH_SEARCH_INDEXING_COPY = {
  temporalDefault:
    'Default time lens at retrieval. Current = only facts valid now (superseded facts hidden). Include historical = also surface invalidated facts. Overridable per query.',
  kHop:
    'Relationship hops out from matched entities when gathering related facts. 1 = direct neighbors only (precise); higher reaches further at more noise/cost.',
  searchRecipe:
    'How candidates are ranked/fused WITHIN each leg (orthogonal to Search scope below). RRF = fast reciprocal-rank fusion (default). MMR = favors diversity. Cross-encoder = highest quality, slowest/most costly. MMR is not compatible with the episodes leg (BM25-only) — disabled when scope includes episodes.',
  searchScope:
    'Which graph elements memory recall and knowledge retrieval READ from (orthogonal to Search recipe above). Edges = facts between entities (relations). Nodes = per-entity summaries (attribute-style memories, e.g. age, role, mood). Episodes = the raw conversation text of each saved turn — BM25 keyword match only (paraphrases may miss), useful as last-resort recall. "Edges + Episodes" keeps the raw turns but drops entity summaries (to test whether entity summaries are redundant with episodes).',
  simMinScore:
    'Minimum cosine similarity (0–1) for a fact to even become a search candidate. Keep low (≈0.3) for recall — too high and paraphrased questions (e.g. asking \'wife\' when the stored fact says \'married to\') return no facts at all. Graphiti\'s own default is a strict 0.6. Precision belongs in the reranker\'s Min relevance below, not here.',
  queryTimeout:
    'Hard ceiling on any single graph (Kuzu) query — writes, index rebuilds, and Graph-tab reads. Protects the server from a stuck index-rebuild checkpoint that can otherwise freeze the whole admin UI for minutes; a bounded failure is retried and logged instead. Keep above your slowest legitimate operation (index rebuilds take seconds). 0 = unlimited.',
  observability:
    'How much the graph engine records to Graph Runs (ingest + retrieval). Off = nothing — no ledger rows, tracer, or usage sinks (spares CPU; graph cost is NOT tracked). Ledger = one priced roll-up row per episode (ingest) and per search (rerank), so token cost still folds into the run total — the production default. Trace = Ledger plus a deep per-stage sidecar (the ⌗ retrieval/ingest trace dialogs) for debugging. Replaces the old Rich/Compact detail and the trace env vars.'
} as const;

export const GRAPH_EVAL_MODELS_COPY = {
  answerModel:
    'Model the memory-eval answer step uses to answer from recalled context. Null falls back to the knowledge answering model, then default chat. (Knowledge-track answers always use the production answering pipeline, not this.)',
  answerProfile: 'Tuning profile (temperature / max-tokens / thinking) for the eval answer model.',
  judgeModel:
    'Model the LLM judge uses to grade answers against the ideal (both tracks). Null falls back to the knowledge answering model, then default chat.',
  judgeProfile: 'Tuning profile for the judge model. Lower temperature = more repeatable grading.',
  retrievalModel:
    'Model the agentic retrieval loop uses to plan searches and call the search_memory tool (memory track). Null falls back to the eval answer model, then the knowledge answering model → default chat.',
  retrievalProfile:
    'Tuning profile (temperature / max-tokens / thinking) for the retrieval-agent model.'
} as const;

export const GRAPH_RERANKER_COPY = {
  model:
    'Cross-encoder used to rerank fact candidates. Empty = reuse the knowledge Reranker model (one model to manage). Local models must be downloaded first.',
  minRelevance: 'Drop facts whose cross-encoder relevance is below this (0–1). 0 = keep all. Ignored by RRF/MMR.',
  device:
    'Torch device for local sentence-transformers rerankers (e.g. cpu, cuda). Blank = auto. Ignored by cloud + ONNX models.'
} as const;

export const GRAPH_VIEW_COPY = {
  largeTypeThreshold:
    'In the Graph tab\'s per-type node filter, a type with more instances than this shows a \'many instances\' performance heads-up in its dropdown. The dropdown still lists and searches every instance — this only flags very large types. Display-only.'
} as const;

export const KNOWLEDGE_COPY = {
  graphBackend:
    'Master switch for knowledge retrieval. Off = today\'s flat Qdrant retrieval (graph untouched). Graphiti = answer from the graph\'s facts.'
} as const;

export const TUNING_PROFILES_COPY = {
  contextWindow:
    'Local providers only (Ollama num_ctx). Blank = provider default (Ollama: 2048). Don\'t set to the full model window — large values use a lot of memory.'
} as const;
