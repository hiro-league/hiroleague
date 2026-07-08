"""Entry point for the hiro-channel-whatsapp plugin process.

Invoked by Hiro's ChannelManager as:
    hiro-channel-whatsapp --hiro-ws ws://127.0.0.1:18081

Mirrors hiro-channel-echo's entry point — the ChannelManager spawns any channel
plugin the same way (see channels/hiro-channel-echo/src/.../main.py).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from hiro_channel_sdk import log_setup
from hiro_channel_sdk.transport import PluginTransport
from hiro_commons.constants.network import DEFAULT_LOCALHOST, PORT_OFFSET_PLUGIN, PORT_RANGE_START
from hiro_commons.constants.storage import LOGS_DIR

from .plugin import WhatsAppChannel

_DEFAULT_LOG_DIR = str(Path.home() / ".hiro" / LOGS_DIR)
_DEFAULT_PLUGIN_WS = f"ws://{DEFAULT_LOCALHOST}:{PORT_RANGE_START + PORT_OFFSET_PLUGIN}"

app = typer.Typer(
    name="hiro-channel-whatsapp",
    help="Hiro WhatsApp channel plugin.",
    add_completion=False,
)


@app.command()
def run(
    hiro_ws: str = typer.Option(
        _DEFAULT_PLUGIN_WS,
        "--hiro-ws",
        help="WebSocket URL of Hiro's plugin server.",
        envvar="HIRO_WS",
    ),
    log_dir: str = typer.Option(
        _DEFAULT_LOG_DIR,
        "--log-dir",
        help="Directory for rotating log files.",
    ),
    log_level: str = typer.Option(
        "INFO",
        "--log-level",
        help="Root log level (DEBUG, INFO, WARNING, ERROR).",
    ),
) -> None:
    """Connect to Hiro and start the WhatsApp channel."""
    plugin = WhatsAppChannel()
    log_setup.init(f"channel-{plugin.info.name}", Path(log_dir), level=log_level)
    transport = PluginTransport(plugin, hiro_ws)
    asyncio.run(transport.run())


if __name__ == "__main__":
    app()
