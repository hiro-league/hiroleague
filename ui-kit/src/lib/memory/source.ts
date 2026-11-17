// Where the graph viewer and the memories table get their data: a `MemorySource` the app hands each piece as a
// prop. The pieces call nothing themselves, so each app keeps its own way of reaching its backend (the core's
// admin sends its selected workspace; another app uses the kit's client). The backend is the memory library's
// router (hiro_memory.routes): the shapes below are its answers. Optional parts are left out by an app that
// lacks them; the pieces then hide what needs them.

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
