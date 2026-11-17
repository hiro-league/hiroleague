// Where the graph viewer, the memories table and the trace dialogs get their data: a `MemorySource` (a `TraceSource`
// for the trace dialogs' controller) the app hands each piece as a prop. The pieces call nothing themselves, so each
// app keeps its own way of reaching its backend (the core's admin sends its selected workspace; another app uses the
// kit's client). The backend is the memory library's routers (hiro_memory.routes): the shapes below are their
// answers. Optional parts are left out by an app that lacks them; the pieces then hide what needs them.

// ---- The graph ------------------------------------------------------------------------------------------------

/** An entity. Shapes mirror hiro_memory/graph/graphiti_serialize.py; edges use source/target so they drop
 *  straight into force-graph's link model. */
export type GraphNodeDTO = {
	id: string;
	name: string;
	type: string;
	aliases: string[];
	chunk_ids: string[];
	document_ids: string[];
	/** Graphiti's generated entity description (EntityNode.summary). */
	summary: string;
};

/** A fact between two entities. */
export type GraphEdgeDTO = {
	id: string;
	source: string;
	target: string;
	rel_type: string;
	fact: string;
	chunk_ids: string[];
	document_ids: string[];
	/** Temporal window: valid_at = became true, invalid_at = stopped being true, expired_at = when the system
	 *  learned it was superseded (set → retired fact). */
	valid_at: string | null;
	invalid_at: string | null;
	expired_at: string | null;
	/** When the fact row was written (transaction time, distinct from valid_at); the "Creation Date" filter. */
	created_at: string | null;
};

export type GraphExport = {
	nodes: GraphNodeDTO[];
	edges: GraphEdgeDTO[];
	truncated: boolean;
	counts: { nodes: number; edges: number };
};

export type GraphGroupKind = 'knowledge' | 'memory' | 'eval' | 'other';
/** A partition of the graph (the knowledge base, one conversation's memory, an eval corpus). */
export type GraphGroup = { id: string; label: string; kind: GraphGroupKind };
export type GraphGroups = { default_group_id: string | null; groups: GraphGroup[] };

/** One episode (a citable chunk). `id` IS the chunk_id node/edge `chunk_ids` carry, so selecting episodes filters
 *  the graph to the entities/facts they produced. In corpus order. */
export type GraphEpisode = {
	id: string;
	snippet: string;
	/** De-stamped multi-line transcript (speaker turns, no inline "[ts]"), the picker's hover tooltip. */
	preview: string;
	valid_at: string | null;
	document_id: string;
};

/** The text behind a chunk a node or fact came from, and its source. */
export type GraphChunkDetail = {
	id: string;
	text: string;
	document_id: string;
	document_title: string;
	ord: number | null;
	heading_path: string | null;
	/** The episode's event time (ISO): the chunk's semantic date, not its ingest time. */
	valid_at: string | null;
};

// Live updates while a graph builds. `group_id` names the partition so the viewer applies only what belongs to
// the group it shows (absent: the knowledge group).
export type GraphNodeEvent = { node: GraphNodeDTO; is_new: boolean; document_id: string; group_id?: string | null };
export type GraphEdgeEvent = { edge: GraphEdgeDTO; is_new: boolean; document_id: string; group_id?: string | null };
export type GraphIngestProgress = { document_id: string; chunk_index: number; chunk_total: number; group_id?: string | null };

export type GraphLiveHandlers = {
	onNode?: (p: GraphNodeEvent) => void;
	onEdge?: (p: GraphEdgeEvent) => void;
	onProgress?: (p: GraphIngestProgress) => void;
	/** A build finished (for `group_id`, or for all when absent): the viewer reloads to heal dropped deltas. */
	onCompleted?: (groupId?: string | null) => void;
};

// ---- The memories table ---------------------------------------------------------------------------------------

/** One memory row as the backend lists it (a Graphiti fact or entity summary; extra fields vary by kind). */
export type MemoryRow = Record<string, unknown>;
export type MemoryList = { memory_enabled: boolean; memories: MemoryRow[] };

/** A name to show for an id the rows carry (a character, a chat channel). A channel also names its character,
 *  shown when the row names no character of its own. */
export type NamedItem = { id: string; name: string; photo?: string | null; characterName?: string | null };

// ---- Run traces -----------------------------------------------------------------------------------------------
// What the trace dialogs show (memory/trace): a ledger run's per-stage traces, which the memory library writes beside
// its run ledger when graph observability is `trace` (hiro_memory/graph/retrieval_trace.py, ingest_trace.py) and serves
// with its trace routes (hiro_memory.routes.trace_routes).

// A fact search, per stage (candidate legs, hop, rank, temporal).
/**
 * One item flowing out of a stage. The populated fields depend on the stage `lane`:
 *   - `edge` (facts): `fact`, `name` (relation), `episodes`, `valid_at`/`invalid_at`/`expired_at`.
 *   - `node` (entities): `name`, `entity_type`, `summary`.
 *   - `episode` (turns): `content`, `source`, `valid_at`.
 * `uuid` and `score` are common. Lane-foreign fields are simply absent.
 */
export type RetrievalTraceItem = {
	uuid: string;
	// edge lane
	fact?: string;
	name?: string;
	source_node_uuid?: string;
	target_node_uuid?: string;
	episodes?: string[];
	valid_at?: string | null;
	invalid_at?: string | null;
	expired_at?: string | null;
	// node lane
	entity_type?: string;
	summary?: string;
	// episode lane
	content?: string;
	source?: string;
	source_description?: string;
	/** Stage score when one exists (fused / reranked); null on raw bm25/cosine legs. */
	score: number | null;
};

/** One pipeline stage: `embed` | `candidate` (per leg) | `hop` | `rank` | `temporal`. */
export type RetrievalTraceStage = {
	kind: string;
	label: string;
	/** Entity type the stage belongs to: `edge` | `node` | `episode` | `query` (embed). */
	lane: string;
	elapsed_ms: number;
	meta: Record<string, unknown>;
	items: RetrievalTraceItem[];
};

/** One full fact search, tagged with the `step_index` of its `graph_expand` row. */
export type RetrievalTraceRecord = {
	run_id: string;
	step_index: number | '';
	/** Agentic-retrieval sub-query id this trace belongs to; null/absent for non-agentic recall. */
	sid?: number | null;
	schema_version: number;
	query: string;
	group_id: string;
	recipe: string;
	temporal: string;
	num_results: number;
	sim_min_score: number;
	k_hop: number;
	started_at: number;
	stages: RetrievalTraceStage[];
};

// An episode's ingest (Graphiti add_episode), per stage: extract entities, resolve them, extract facts, date them,
// resolve or invalidate them, summarize; with what it wrote to the graph.
/** One prompt message of a stage's input (the model context the step ran on). */
export type IngestTraceMessage = { role: string; content: string };

/** A persisted entity node (what add_episode wrote to the graph). */
export type IngestTraceNode = {
	uuid: string;
	name: string;
	entity_type: string;
	summary: string;
	score: number | null;
};

/** A persisted fact edge (relationship triple) with its bi-temporal window. */
export type IngestTraceEdge = {
	uuid: string;
	fact: string;
	name: string;
	source_node_uuid: string;
	target_node_uuid: string;
	episodes: string[];
	valid_at: string | null;
	invalid_at: string | null;
	expired_at: string | null;
	score: number | null;
};

/**
 * One `add_episode` stage. `source` is `llm` for a captured model call (the common
 * case) or `dedup` for a non-LLM auto-merge. `input` is the prompt messages for an
 * LLM stage; `output` is the structured result (parsed model dump / dedup decision).
 */
export type IngestTraceStage = {
	node: string;
	label: string;
	operation: string;
	source: string;
	elapsed_ms: number;
	input_tokens: number;
	output_tokens: number;
	model_id: string;
	meta: Record<string, unknown>;
	input: IngestTraceMessage[] | unknown;
	output: unknown;
};

/** Active ontology legend: `entity_type_id` → type name + description (graphiti's id ordering,
 *  id 0 = base `Entity`). Lets the dialog resolve `extract_entities`' numeric ids to real types. */
export type IngestEntityType = {
	id: number;
	name: string;
	description: string;
};

/** One episode's full ingest trace, tagged with the `step_index` of its episode row. */
export type IngestTraceRecord = {
	run_id: string;
	step_index: number | '';
	schema_version: number;
	chunk_id: string;
	episode_index: number;
	total: number;
	name: string;
	text: string;
	group_id: string;
	reference_time: string;
	started_at: number;
	invalidated_count: number;
	/** Ontology legend for resolving `extract_entities` type ids (absent on pre-legend sidecars). */
	entity_types?: IngestEntityType[];
	persisted_nodes: IngestTraceNode[];
	persisted_edges: IngestTraceEdge[];
	stages: IngestTraceStage[];
};

/** Where the trace dialogs' controllers get a run's traces (empty when the run was not traced). */
export interface TraceSource {
	/** A run's fact searches, one record each (an agentic recall's sub-queries carry their `sid`). */
	retrievalTrace(runId: string): Promise<RetrievalTraceRecord[]>;
	/** A run's ingested episodes, one record each, in the order they were ingested. */
	ingestTrace(runId: string): Promise<IngestTraceRecord[]>;
}

// ---- The source -----------------------------------------------------------------------------------------------

export interface MemorySource {
	exportGraph(opts: { groupIds?: string[]; nodeLimit?: number; edgeLimit?: number }): Promise<GraphExport>;
	listGroups(): Promise<GraphGroups>;
	listEpisodes(groupId: string): Promise<GraphEpisode[]>;
	chunkDetails(chunkIds: string[], signal?: AbortSignal): Promise<GraphChunkDetail[]>;
	/** Chunk ids whose text matches; left out when the app has no text search. */
	searchChunks?(text: string, signal?: AbortSignal): Promise<string[]>;
	/** Without `groupId`: the default user's conversation memory. */
	listMemories(groupId?: string): Promise<MemoryList>;
	/** Answers how many were deleted. */
	deleteMemories(ids: string[]): Promise<number>;
	clearGroup(groupId: string): Promise<number>;
	/** Names for the character and channel ids memory rows carry; left out, the ids show. */
	characters?(): Promise<NamedItem[]>;
	channels?(): Promise<NamedItem[]>;
	/** Live graph updates; answers a function that stops them. Left out, the viewer reloads by hand only. */
	live?(handlers: GraphLiveHandlers): () => void;
	/** Above this many nodes of one type, the filter bar suggests search over browsing (the app's setting);
	 *  left out, it never does. */
	largeTypeThreshold?(): Promise<number | null>;
}
