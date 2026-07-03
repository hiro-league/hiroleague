"""AgentServices — mutable DI container for agent graph node groups."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Checkpointer

from .ledger import LedgerSink

if TYPE_CHECKING:
    from ...domain.credential_store import CredentialStore
    from ...domain.memory import MemoryService
    from ...runtime.preferences_runtime import WorkspacePreferencesRuntime
    from ...services.memory.models import MemoryRetrievalModelCache
    from ...services.stt import STTService
    from ...services.tts import TTSService
    from ...services.vision_service import VisionService


@dataclass
class AgentServices:
    """Mutable service container — preference reactors hot-swap fields in place."""

    workspace_path: Path
    ledger_sink: LedgerSink
    preferences: "WorkspacePreferencesRuntime | None" = None
    checkpointer: Checkpointer | None = None
    stt: "STTService | None" = None
    vision: "VisionService | None" = None
    tts: "TTSService | None" = None
    memory: "MemoryService | None" = None
    credentials: "CredentialStore | None" = None
    knowledge_subgraph: CompiledStateGraph | None = None
    # Cross-turn cache for the memory-recall retrieval model (review C2): the recall model is rebuilt
    # only when its resolved spec changes, not once per turn. Shared here (not per compiled graph)
    # because the recall model is independent of the chat model/character. Lazily created by
    # ``MemoryNodes`` when absent; cleared on memory/providers reload (``_attach_new_memory_service``).
    memory_retrieval_models: "MemoryRetrievalModelCache | None" = None
