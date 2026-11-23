"""Entry point for the hiro-channel-whatsapp plugin process.

Started by the core's extension manager as:
    hiro-channel-whatsapp --hiro-ws ws://127.0.0.1:18082 --key-dir <workspace>/channels/whatsapp --log-dir ... --log-level ...
with its pairing code in HIRO_PAIRING_CODE.

Mirrors hiro-channel-echo's entry point — the extension manager starts any channel
plugin the same way (see channels/hiro-channel-echo/src/.../main.py).
"""

from __future__ import annotations

from pathlib import Path

import typer

from hiro_channel_sdk import PluginRunner, log_setup
from hiro_commons.constants.network import DEFAULT_LOCALHOST, PORT_OFFSET_EXTENSION, PORT_RANGE_START
from hiro_commons.constants.storage import LOGS_DIR

from .plugin import WhatsAppChannel

_DEFAULT_LOG_DIR = str(Path.home() / ".hiro" / LOGS_DIR)
_DEFAULT_EXTENSION_WS = f"ws://{DEFAULT_LOCALHOST}:{PORT_RANGE_START + PORT_OFFSET_EXTENSION}"
_DEFAULT_KEY_DIR = str(Path.home() / ".hiro" / "channels" / "whatsapp")

app = typer.Typer(
    name="hiro-channel-whatsapp",
    help="Hiro WhatsApp channel plugin.",
    add_completion=False,
)


@app.command()
def run(
    hiro_ws: str = typer.Option(
        _DEFAULT_EXTENSION_WS,
        "--hiro-ws",
        help="WebSocket URL of the core's extension socket.",
        envvar="HIRO_WS",
    ),
    key_dir: str = typer.Option(
        _DEFAULT_KEY_DIR,
        "--key-dir",
        help="Folder for the plugin's own key and the id the core gave it.",
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
    plugin = WhatsAppChannel(log_dir=log_dir)
    log_setup.init(f"channel-{plugin.info.name}", Path(log_dir), level=log_level)
    # The pairing code, the first time or after a lost key, comes in the environment (ENV_PAIRING_CODE).
    log_setup.run(PluginRunner(plugin, hiro_ws, Path(key_dir)).run())


if __name__ == "__main__":
    app()
