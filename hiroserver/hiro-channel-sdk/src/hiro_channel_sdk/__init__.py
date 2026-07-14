"""hiro-channel-sdk — shared contract for Hiro channel plugins.

Exports the key building blocks every plugin author needs:
  - UnifiedMessage   — canonical cross-channel message model (v0.1)
  - MessageRouting   — routing/identification envelope within UnifiedMessage
  - ContentItem      — single content piece within UnifiedMessage
  - EventPayload     — event payload for message_type "event"
  - ChannelPlugin    — abstract base class to implement
  - PluginTransport  — handles WS connection to the Hiro server, JSON-RPC dispatch
  - rpc              — JSON-RPC 2.0 helpers (build / parse)
  - constants        — protocol constants (RPC methods, WS close codes, etc.)
"""

from . import constants, log_setup
from .base import ChannelPlugin
from .capabilities import (
    ACTION_LOGOUT,
    ACTION_RECONNECT,
    PAIRING_NONE,
    PAIRING_OAUTH,
    PAIRING_QR,
    PAIRING_TOKEN,
    ChannelCapabilities,
)
from .log_scope_fields import (
    METADATA_LOG_REPLY_TO_MSG_ID,
    METADATA_LOG_RPC_METHOD,
    METADATA_LOG_TEXT_PREVIEW,
    unified_message_log_scope,
)
from hiro_commons.version import package_version

from .models import ChannelInfo, ContentItem, EventPayload, MessageRouting, RpcRequest, RpcResponse, UnifiedMessage
from .transport import PluginTransport

# Read from installed metadata so it can never drift from pyproject.toml.
__version__ = package_version("hiro-channel-sdk")
__all__ = [
    "log_setup",
    "constants",
    "METADATA_LOG_REPLY_TO_MSG_ID",
    "METADATA_LOG_RPC_METHOD",
    "METADATA_LOG_TEXT_PREVIEW",
    "unified_message_log_scope",
    "ChannelPlugin",
    "ChannelInfo",
    "ChannelCapabilities",
    "PAIRING_NONE",
    "PAIRING_QR",
    "PAIRING_TOKEN",
    "PAIRING_OAUTH",
    "ACTION_LOGOUT",
    "ACTION_RECONNECT",
    "ContentItem",
    "EventPayload",
    "MessageRouting",
    "RpcRequest",
    "RpcResponse",
    "UnifiedMessage",
    "PluginTransport",
]
