"""Bridge graph-viz deltas onto the process-wide ``DomainEventBus``.

A single home for "publish a ``knowledge.graph.*`` event for this workspace" so both the
admin knowledge routes (document/eval graph ingest) and the conversation-memory facade
(runtime ``memory_out``) emit live node/edge deltas the same way. The admin Graph tab's SSE
endpoint subscribes to these event types and filters by ``workspace_path`` — so any producer
in the process can light up the live viz just by publishing here.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from hirocli.domain.events import DomainEvent, get_domain_event_bus

if TYPE_CHECKING:
    from hirocli.services.knowledge.graph.graphiti_ingest import GraphEventSink


def publish_graph_event(
    workspace_path: Path, event_type: str, payload: dict[str, Any]
) -> None:
    """Publish one workspace-scoped graph-viz Domain Event."""
    get_domain_event_bus().publish(
        DomainEvent(type=event_type, workspace_path=workspace_path, payload=payload)
    )


def graph_event_bus_sink(workspace_path: Path) -> GraphEventSink:
    """A :data:`GraphEventSink` that republishes each node/edge upsert onto the bus.

    Hand this to ``ingest_chunks(..., event_sink=...)`` (knowledge OR conversation memory)
    to stream live deltas to the admin Graph tab. Cheap when no SSE consumer is attached —
    the bus simply drops the event.
    """

    def sink(event_type: str, payload: dict[str, Any]) -> None:
        publish_graph_event(workspace_path, event_type, payload)

    return sink
