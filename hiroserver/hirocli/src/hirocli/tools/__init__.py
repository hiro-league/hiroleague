"""Tool registry — lazily loaded.

Importing this package (``hirocli.tools``) must stay cheap so that the CLI's
fast paths (``hiro start``, ``hiro stop``, ``hiro status``…) don't pay the
~12-second cost of pulling in the knowledge stack (langchain_text_splitters →
sentence_transformers → torch + transformers + sklearn).

Two mechanisms make that work:

1. PEP 562 ``__getattr__`` — ``from hirocli.tools import KnowledgeIngestTool``
   only imports ``hirocli.tools.knowledge`` (not every tool module).
2. ``all_tools()`` imports happen inside the function body, so listing the
   registry is the only thing that triggers the full load.

Callers should still prefer importing from the specific submodule
(``from hirocli.tools.server import StartTool``) when they only need one tool —
that keeps the import graph minimal and self-documenting.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Tool

# Map exported symbol -> submodule it lives in. Keep in sync with the tool
# modules under hirocli/tools/. Static type-checkers see the names via the
# TYPE_CHECKING block below; runtime resolution goes through __getattr__.
_LAZY_EXPORTS: dict[str, str] = {
    # conversation
    "ConversationChannelClearMessagesTool": ".conversation",
    "ConversationChannelCreateTool": ".conversation",
    "ConversationChannelDeleteTool": ".conversation",
    "ConversationChannelGetTool": ".conversation",
    "ConversationChannelListTool": ".conversation",
    "ConversationChannelUpdateTool": ".conversation",
    "MessageHistoryTool": ".conversation",
    "MessageSendTool": ".conversation",
    # logs
    "LogSearchTool": ".logs",
    "LogTailTool": ".logs",
    # llm catalog
    "LlmCatalogGetModelTool": ".llm_catalog",
    "LlmCatalogListModelsTool": ".llm_catalog",
    "LlmCatalogListProvidersTool": ".llm_catalog",
    # provider
    "AvailableModelsListTool": ".provider",
    "ProviderAddApiKeyTool": ".provider",
    "ProviderListConfiguredTool": ".provider",
    "ProviderRemoveTool": ".provider",
    # character
    "CharacterCreateTool": ".character",
    "CharacterDeleteTool": ".character",
    "CharacterGetTool": ".character",
    "CharacterListTool": ".character",
    "CharacterUpdateTool": ".character",
    "CharacterUploadPhotoTool": ".character",
    # channel
    "ChannelDisableTool": ".channel",
    "ChannelEnableTool": ".channel",
    "ChannelInstallTool": ".channel",
    "ChannelListTool": ".channel",
    "ChannelRemoveTool": ".channel",
    "ChannelSetupTool": ".channel",
    # device
    "DeviceAddTool": ".device",
    "DeviceListTool": ".device",
    "DeviceRevokeTool": ".device",
    # files
    "FilesHeadTool": ".files",
    # gateway
    "GatewaySetupTool": ".gateway",
    "GatewayStartTool": ".gateway",
    "GatewayStatusTool": ".gateway",
    "GatewayStopTool": ".gateway",
    "GatewayTeardownTool": ".gateway",
    # media
    "DescribeImageTool": ".media",
    "TranscribeTool": ".media",
    # image generation
    "GenerateImageTool": ".image_gen",
    # memory
    "MemoryClearTool": ".memory",
    "MemoryListTool": ".memory",
    # knowledge (heavy: pulls torch + transformers; do NOT touch on fast paths)
    "KnowledgeAnswerTool": ".knowledge",
    "KnowledgeCreateCategoryTool": ".knowledge",
    "KnowledgeCreateTagTool": ".knowledge",
    "KnowledgeDeleteDocumentTool": ".knowledge",
    "KnowledgeGetDocumentTool": ".knowledge",
    "KnowledgeIngestTool": ".knowledge",
    "KnowledgeJobStatusTool": ".knowledge",
    "KnowledgeListCategoriesTool": ".knowledge",
    "KnowledgeListDocumentsTool": ".knowledge",
    "KnowledgeListTagsTool": ".knowledge",
    "KnowledgeScanFolderTool": ".knowledge",
    "KnowledgeSearchTool": ".knowledge",
    "KnowledgeReingestDocumentTool": ".knowledge",
    "KnowledgeUpdateDocumentMetadataTool": ".knowledge",
    # knowledge_graph
    "KnowledgeGraphExportTool": ".knowledge_graph",
    "KnowledgeGraphIngestBatchTool": ".knowledge_graph",
    "KnowledgeGraphIngestTool": ".knowledge_graph",
    # knowledge_eval
    "KnowledgeL3EvalRunTool": ".knowledge_eval",
    # server
    "RestartTool": ".server",
    "SetupTool": ".server",
    "StartTool": ".server",
    "StatusTool": ".server",
    "StopTool": ".server",
    "TeardownTool": ".server",
    "UninstallTool": ".server",
    "UpgradeTool": ".server",
    # policy
    "PolicyGetTool": ".policy",
    # workspace
    "WorkspaceCreateTool": ".workspace",
    "WorkspaceListTool": ".workspace",
    "WorkspaceRemoveTool": ".workspace",
    "WorkspaceShowTool": ".workspace",
    "WorkspaceUpdateTool": ".workspace",
}


def __getattr__(name: str):
    """PEP 562 lazy loader for ``from hirocli.tools import X``.

    Only the submodule containing ``X`` is imported, so callers that ask for a
    cheap tool don't drag in the knowledge / agent-graph stack.
    """
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module 'hirocli.tools' has no attribute {name!r}")
    import importlib

    module = importlib.import_module(module_path, __name__)
    value = getattr(module, name)
    globals()[name] = value  # cache for subsequent accesses
    return value


def __dir__() -> list[str]:
    return sorted({"Tool", "all_tools", *_LAZY_EXPORTS.keys()})


def all_tools() -> list[Tool]:
    """Return one fresh instance of every registered tool.

    Imports happen inside the function so listing the registry is the only
    code path that pays the full transitive import cost.
    """
    from .channel import (
        ChannelDisableTool,
        ChannelEnableTool,
        ChannelInstallTool,
        ChannelListTool,
        ChannelRemoveTool,
        ChannelSetupTool,
    )
    from .character import (
        CharacterCreateTool,
        CharacterDeleteTool,
        CharacterGetTool,
        CharacterListTool,
        CharacterUpdateTool,
        CharacterUploadPhotoTool,
    )
    from .conversation import (
        ConversationChannelClearMessagesTool,
        ConversationChannelCreateTool,
        ConversationChannelDeleteTool,
        ConversationChannelGetTool,
        ConversationChannelListTool,
        ConversationChannelUpdateTool,
        MessageHistoryTool,
        MessageSendTool,
    )
    from .device import DeviceAddTool, DeviceListTool, DeviceRevokeTool
    from .files import FilesHeadTool
    from .gateway import (
        GatewaySetupTool,
        GatewayStartTool,
        GatewayStatusTool,
        GatewayStopTool,
        GatewayTeardownTool,
    )
    from .image_gen import GenerateImageTool
    from .knowledge import (
        KnowledgeAnswerTool,
        KnowledgeCreateCategoryTool,
        KnowledgeCreateTagTool,
        KnowledgeDeleteDocumentTool,
        KnowledgeGetDocumentTool,
        KnowledgeIngestTool,
        KnowledgeJobStatusTool,
        KnowledgeListCategoriesTool,
        KnowledgeListDocumentsTool,
        KnowledgeListTagsTool,
        KnowledgeReingestDocumentTool,
        KnowledgeScanFolderTool,
        KnowledgeSearchTool,
        KnowledgeUpdateDocumentMetadataTool,
    )
    from .knowledge_eval import KnowledgeL3EvalRunTool
    from .knowledge_graph import (
        KnowledgeGraphExportTool,
        KnowledgeGraphIngestBatchTool,
        KnowledgeGraphIngestTool,
    )
    from .llm_catalog import (
        LlmCatalogGetModelTool,
        LlmCatalogListModelsTool,
        LlmCatalogListProvidersTool,
    )
    from .logs import LogSearchTool, LogTailTool
    from .media import DescribeImageTool, TranscribeTool
    from .memory import MemoryClearTool, MemoryListTool
    from .policy import PolicyGetTool
    from .provider import (
        AvailableModelsListTool,
        ProviderAddApiKeyTool,
        ProviderListConfiguredTool,
        ProviderRemoveTool,
    )
    from .server import (
        RestartTool,
        SetupTool,
        StartTool,
        StatusTool,
        StopTool,
        TeardownTool,
        UninstallTool,
        UpgradeTool,
    )
    from .workspace import (
        WorkspaceCreateTool,
        WorkspaceListTool,
        WorkspaceRemoveTool,
        WorkspaceShowTool,
        WorkspaceUpdateTool,
    )

    return [
        CharacterListTool(),
        CharacterGetTool(),
        CharacterCreateTool(),
        CharacterUpdateTool(),
        CharacterDeleteTool(),
        CharacterUploadPhotoTool(),
        DeviceAddTool(),
        DeviceListTool(),
        DeviceRevokeTool(),
        FilesHeadTool(),
        ChannelListTool(),
        ChannelInstallTool(),
        ChannelSetupTool(),
        ChannelEnableTool(),
        ChannelDisableTool(),
        ChannelRemoveTool(),
        ConversationChannelListTool(),
        ConversationChannelCreateTool(),
        ConversationChannelUpdateTool(),
        ConversationChannelDeleteTool(),
        ConversationChannelClearMessagesTool(),
        ConversationChannelGetTool(),
        MessageHistoryTool(),
        MessageSendTool(),
        WorkspaceListTool(),
        WorkspaceCreateTool(),
        WorkspaceRemoveTool(),
        WorkspaceUpdateTool(),
        WorkspaceShowTool(),
        SetupTool(),
        StartTool(),
        StopTool(),
        RestartTool(),
        StatusTool(),
        TeardownTool(),
        UninstallTool(),
        UpgradeTool(),
        PolicyGetTool(),
        GatewayStatusTool(),
        GatewayStartTool(),
        GatewayStopTool(),
        GatewaySetupTool(),
        GatewayTeardownTool(),
        TranscribeTool(),
        DescribeImageTool(),
        GenerateImageTool(),
        MemoryListTool(),
        MemoryClearTool(),
        KnowledgeScanFolderTool(),
        KnowledgeIngestTool(),
        KnowledgeJobStatusTool(),
        KnowledgeSearchTool(),
        KnowledgeAnswerTool(),
        KnowledgeListDocumentsTool(),
        KnowledgeGetDocumentTool(),
        KnowledgeDeleteDocumentTool(),
        KnowledgeReingestDocumentTool(),
        KnowledgeUpdateDocumentMetadataTool(),
        KnowledgeListTagsTool(),
        KnowledgeListCategoriesTool(),
        KnowledgeCreateCategoryTool(),
        KnowledgeCreateTagTool(),
        KnowledgeGraphIngestTool(),
        KnowledgeGraphIngestBatchTool(),
        KnowledgeGraphExportTool(),
        KnowledgeL3EvalRunTool(),
        LogSearchTool(),
        LogTailTool(),
        LlmCatalogListProvidersTool(),
        LlmCatalogListModelsTool(),
        LlmCatalogGetModelTool(),
        ProviderAddApiKeyTool(),
        ProviderRemoveTool(),
        ProviderListConfiguredTool(),
        AvailableModelsListTool(),
    ]


# Static type-checkers / IDE autocomplete see the real names here without
# making them runtime-imported. The actual runtime resolution is __getattr__.
if TYPE_CHECKING:  # pragma: no cover
    from .channel import (  # noqa: F401
        ChannelDisableTool,
        ChannelEnableTool,
        ChannelInstallTool,
        ChannelListTool,
        ChannelRemoveTool,
        ChannelSetupTool,
    )
    from .character import (  # noqa: F401
        CharacterCreateTool,
        CharacterDeleteTool,
        CharacterGetTool,
        CharacterListTool,
        CharacterUpdateTool,
        CharacterUploadPhotoTool,
    )
    from .conversation import (  # noqa: F401
        ConversationChannelClearMessagesTool,
        ConversationChannelCreateTool,
        ConversationChannelDeleteTool,
        ConversationChannelGetTool,
        ConversationChannelListTool,
        ConversationChannelUpdateTool,
        MessageHistoryTool,
        MessageSendTool,
    )
    from .device import (  # noqa: F401
        DeviceAddTool,
        DeviceListTool,
        DeviceRevokeTool,
    )
    from .files import FilesHeadTool  # noqa: F401
    from .gateway import (  # noqa: F401
        GatewaySetupTool,
        GatewayStartTool,
        GatewayStatusTool,
        GatewayStopTool,
        GatewayTeardownTool,
    )
    from .knowledge import (  # noqa: F401
        KnowledgeAnswerTool,
        KnowledgeCreateCategoryTool,
        KnowledgeCreateTagTool,
        KnowledgeDeleteDocumentTool,
        KnowledgeGetDocumentTool,
        KnowledgeIngestTool,
        KnowledgeJobStatusTool,
        KnowledgeListCategoriesTool,
        KnowledgeListDocumentsTool,
        KnowledgeListTagsTool,
        KnowledgeReingestDocumentTool,
        KnowledgeScanFolderTool,
        KnowledgeSearchTool,
        KnowledgeUpdateDocumentMetadataTool,
    )
    from .image_gen import GenerateImageTool  # noqa: F401
    from .knowledge_eval import KnowledgeL3EvalRunTool  # noqa: F401
    from .knowledge_graph import (  # noqa: F401
        KnowledgeGraphExportTool,
        KnowledgeGraphIngestBatchTool,
        KnowledgeGraphIngestTool,
    )
    from .llm_catalog import (  # noqa: F401
        LlmCatalogGetModelTool,
        LlmCatalogListModelsTool,
        LlmCatalogListProvidersTool,
    )
    from .logs import LogSearchTool, LogTailTool  # noqa: F401
    from .media import DescribeImageTool, TranscribeTool  # noqa: F401
    from .memory import MemoryClearTool, MemoryListTool  # noqa: F401
    from .policy import PolicyGetTool  # noqa: F401
    from .provider import (  # noqa: F401
        AvailableModelsListTool,
        ProviderAddApiKeyTool,
        ProviderListConfiguredTool,
        ProviderRemoveTool,
    )
    from .server import (  # noqa: F401
        RestartTool,
        SetupTool,
        StartTool,
        StatusTool,
        StopTool,
        TeardownTool,
        UninstallTool,
        UpgradeTool,
    )
    from .workspace import (  # noqa: F401
        WorkspaceCreateTool,
        WorkspaceListTool,
        WorkspaceRemoveTool,
        WorkspaceShowTool,
        WorkspaceUpdateTool,
    )
