"""Channel plugin configuration management: what the core needs to start a channel plugin, and its settings.

All functions are workspace-scoped — they accept workspace_path: Path.
A channel plugin is an extension the core starts: its row in workspace.db's
extension_records (domain/extensions.py, started_by_core = 1) holds these too.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


from .db import db_path, ensure_db

logger = logging.getLogger(__name__)


@dataclass
class ChannelConfig:
    """Persisted configuration for one channel plugin."""

    name: str
    enabled: bool = True
    # Shell command used to start the plugin process.
    # Hiro appends ["--hiro-ws", <url>, "--key-dir", <folder>, ...] automatically.
    # Defaults to ["hiro-channel-<name>"] if empty.
    command: list[str] = field(default_factory=list)
    # Arbitrary channel-specific settings (API keys, etc.).
    # Pushed to the plugin with extension.configure after it signs in.
    config: dict[str, Any] = field(default_factory=dict)
    # If set, the command is run via `uv run --directory <workspace_dir>`.
    # Populated automatically by `hiro channel setup` when it detects
    # a uv workspace in the current directory tree.  Leave empty for
    # plugins installed as uv tools (they are already on PATH).
    workspace_dir: str = ""

    def effective_command(self) -> list[str]:
        base = self.command if self.command else [f"hiro-channel-{self.name}"]
        if self.workspace_dir:
            if self._should_use_module_launcher(base):
                module_name = f"hiro_channel_{self.name.replace('-', '_')}.main"
                return [
                    "uv", "run", "--directory", self.workspace_dir,
                    "python", "-m", module_name,
                ]
            return ["uv", "run", "--directory", self.workspace_dir] + base
        return base

    def _should_use_module_launcher(self, base: list[str]) -> bool:
        if sys.platform != "win32":
            return False
        return base == [f"hiro-channel-{self.name}"]


# ---------------------------------------------------------------------------
# CRUD — the started extensions' rows of workspace.db's extension_records
# ---------------------------------------------------------------------------

_TABLE = "extension_records"
_STARTED = "started_by_core = 1"


def load_channel_config(workspace_path: Path, name: str) -> ChannelConfig | None:
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(f"SELECT * FROM {_TABLE} WHERE name = ? AND {_STARTED}", (name,)).fetchone()
        if row is None:
            return None
        try:
            return _row_to_config(row)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.warning("Corrupt channel row (name=%r): %s", name, exc)
            return None


def save_channel_config(workspace_path: Path, cfg: ChannelConfig) -> None:
    """Add a channel plugin (a new id, no key: it pairs at its first start), or change its settings."""
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.execute(
            f"""
            INSERT INTO {_TABLE} (extension_id, name, kind, relays_chat, started_by_core,
                                  enabled, command, config, workspace_dir)
            VALUES (?, ?, 'channel', 1, 1, ?, ?, ?, ?)
            ON CONFLICT(name) WHERE {_STARTED} DO UPDATE SET
                enabled       = excluded.enabled,
                command       = excluded.command,
                config        = excluded.config,
                workspace_dir = excluded.workspace_dir
            """,
            (
                uuid.uuid4().hex,
                cfg.name,
                int(cfg.enabled),
                json.dumps(cfg.command),
                json.dumps(cfg.config),
                cfg.workspace_dir,
            ),
        )
        conn.commit()


def list_channel_configs(workspace_path: Path) -> list[ChannelConfig]:
    return _list(workspace_path, enabled_only=False)


def list_enabled_channels(workspace_path: Path) -> list[ChannelConfig]:
    return _list(workspace_path, enabled_only=True)


def delete_channel_config(workspace_path: Path, name: str) -> bool:
    """Remove a channel plugin's row (its key with it). Returns True if a row was removed."""
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        cursor = conn.execute(f"DELETE FROM {_TABLE} WHERE name = ? AND {_STARTED}", (name,))
        conn.commit()
        return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _list(workspace_path: Path, *, enabled_only: bool) -> list[ChannelConfig]:
    ensure_db(workspace_path)
    where = f"{_STARTED} AND enabled = 1" if enabled_only else _STARTED
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(f"SELECT * FROM {_TABLE} WHERE {where} ORDER BY name").fetchall()
    configs: list[ChannelConfig] = []
    for row in rows:
        try:
            configs.append(_row_to_config(row))
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.warning("Skipping corrupt channel row (name=%r): %s", row["name"], exc)
    return configs


def _row_to_config(row: sqlite3.Row) -> ChannelConfig:
    return ChannelConfig(
        name=row["name"],
        enabled=bool(row["enabled"]),
        command=json.loads(row["command"] or "[]"),
        config=json.loads(row["config"] or "{}"),
        workspace_dir=row["workspace_dir"] or "",
    )
