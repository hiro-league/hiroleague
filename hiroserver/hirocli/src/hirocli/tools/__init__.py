from .base import Tool
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
from .logs import LogSearchTool, LogTailTool
from .llm_catalog import (
    LlmCatalogGetModelTool,
    LlmCatalogListModelsTool,
    LlmCatalogListProvidersTool,
)
from .provider import (
    AvailableModelsListTool,
    ProviderAddApiKeyTool,
    ProviderListConfiguredTool,
    ProviderRemoveTool,
)
from .character import (
    CharacterCreateTool,
    CharacterDeleteTool,
    CharacterGetTool,
    CharacterListTool,
    CharacterUpdateTool,
    CharacterUploadPhotoTool,
)
from .channel import (
    ChannelDisableTool,
    ChannelEnableTool,
    ChannelInstallTool,
    ChannelListTool,
    ChannelRemoveTool,
    ChannelSetupTool,
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
from .media import DescribeImageTool, TranscribeTool
from .memory import MemoryClearTool, MemoryListTool
from .knowledge import (
    KnowledgeGetDocumentTool,
    KnowledgeIngestTool,
    KnowledgeJobStatusTool,
    KnowledgeListCategoriesTool,
    KnowledgeListDocumentsTool,
    KnowledgeListTagsTool,
    KnowledgeScanFolderTool,
    KnowledgeSearchTool,
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
from .policy import PolicyGetTool
from .workspace import (
    WorkspaceCreateTool,
    WorkspaceListTool,
    WorkspaceRemoveTool,
    WorkspaceShowTool,
    WorkspaceUpdateTool,
)


def all_tools() -> list[Tool]:
    """Return one fresh instance of every registered tool."""
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
        MemoryListTool(),
        MemoryClearTool(),
        KnowledgeScanFolderTool(),
        KnowledgeIngestTool(),
        KnowledgeJobStatusTool(),
        KnowledgeSearchTool(),
        KnowledgeListDocumentsTool(),
        KnowledgeGetDocumentTool(),
        KnowledgeListTagsTool(),
        KnowledgeListCategoriesTool(),
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
