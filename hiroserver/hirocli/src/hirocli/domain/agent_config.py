"""Agent configuration management for hirocli.

All functions are workspace-scoped — they accept workspace_path: Path.
Data is stored in the agents table of workspace.db.

A workspace has exactly one default agent (is_default = 1).  On first access
the row is created with built-in defaults; subsequent reads/writes update that
single row.  The multi-agent schema is in place for the future — callers that
only know about one agent continue to work unchanged.

The agents table stores agent identity and system prompt.
LLM selection (provider, model, temperature, max_tokens) lives in
preferences.json — see domain/preferences.py.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from pathlib import Path

from hiro_commons.timestamps import utc_iso, utc_now

from .db import db_path, ensure_db

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = """\
You are a helpful home assistant running on Hiro.
Answer questions concisely and helpfully.
"""

_DEFAULT_AGENT_NAME = "default"


# ---------------------------------------------------------------------------
# System prompt I/O
# ---------------------------------------------------------------------------

def load_system_prompt(workspace_path: Path) -> str:
    """Load the system prompt for the default agent, seeding defaults if absent."""
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT system_prompt FROM agents WHERE is_default = 1 LIMIT 1"
        ).fetchone()
        if row is None:
            _insert_default_agent(conn)
            return _DEFAULT_SYSTEM_PROMPT.strip()
        prompt = row["system_prompt"] or ""
        return (prompt if prompt else _DEFAULT_SYSTEM_PROMPT).strip()


def save_system_prompt(workspace_path: Path, prompt: str) -> None:
    """Persist a new system prompt for the default agent."""
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        if not conn.execute(
            "SELECT 1 FROM agents WHERE is_default = 1"
        ).fetchone():
            _insert_default_agent(conn)
        conn.execute(
            "UPDATE agents SET system_prompt = ? WHERE is_default = 1",
            (prompt.strip(),),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _insert_default_agent(conn: sqlite3.Connection) -> None:
    """Insert the default agent row with identity and system prompt only."""
    conn.execute(
        """
        INSERT INTO agents (id, name, is_default, system_prompt, created_at)
        VALUES (?, ?, 1, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            _DEFAULT_AGENT_NAME,
            _DEFAULT_SYSTEM_PROMPT.strip(),
            utc_iso(utc_now()),
        ),
    )
    conn.commit()
    logger.info("Created default agent row in workspace.db")
