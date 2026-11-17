"""Names the graph engine owns: its Kuzu file and the live-update events its ingest emits."""

from __future__ import annotations

# The embedded Kuzu graph DB file that backs Graphiti (entities + facts + temporal
# windows; chunk evidence stays in Qdrant). Lives in the consolidated db/ folder.
KUZU_DB_FILENAME = "graphiti_kuzu.db"

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
