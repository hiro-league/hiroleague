"""Network and port constants shared across all Hiro packages."""

from __future__ import annotations

DEFAULT_GATEWAY_PORT: int = 8765
DEFAULT_GATEWAY_HOST: str = "0.0.0.0"
DEFAULT_LOCALHOST: str = "127.0.0.1"

# Workspace port allocation — 4 ports per slot, starting at PORT_RANGE_START.
#   http_port    = PORT_RANGE_START + slot * PORTS_PER_SLOT + PORT_OFFSET_HTTP
#   plugin_port     = PORT_RANGE_START + slot * PORTS_PER_SLOT + PORT_OFFSET_PLUGIN
#   extension_port  = PORT_RANGE_START + slot * PORTS_PER_SLOT + PORT_OFFSET_EXTENSION
#   admin_port      = PORT_RANGE_START + slot * PORTS_PER_SLOT + PORT_OFFSET_ADMIN
#
# Example (slot 0): http=18080, plugin=18081, extension=18082, admin=18083
PORT_RANGE_START: int = 18080
PORTS_PER_SLOT: int = 4
PORT_OFFSET_HTTP: int = 0
PORT_OFFSET_PLUGIN: int = 1
# Offset 2 was reserved (once a local gateway port); extensions connect there now:
# one socket per workspace that every extension (HomeHiro first) signs in to.
PORT_OFFSET_EXTENSION: int = 2
PORT_OFFSET_ADMIN: int = 3
