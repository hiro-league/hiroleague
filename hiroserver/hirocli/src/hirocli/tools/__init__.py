from .base import Tool
from .conversation import (
    ConversationChannelCreateTool,
    ConversationChannelDeleteTool,
    ConversationChannelGetTool,
    ConversationChannelListTool,
    ConversationChannelUpdateTool,
    MessageHistoryTool,
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
from .gateway import (
    GatewaySetupTool,
    GatewayStartTool,
    GatewayStatusTool,
    GatewayStopTool,
    GatewayTeardownTool,
)
from .media import DescribeImageTool, TranscribeTool
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
        ConversationChannelGetTool(),
        MessageHistoryTool(),
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
        GatewayStatusTool(),
        GatewayStartTool(),
        GatewayStopTool(),
        GatewaySetupTool(),
        GatewayTeardownTool(),
        TranscribeTool(),
        DescribeImageTool(),
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
