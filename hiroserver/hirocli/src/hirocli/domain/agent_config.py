"""Agent configuration — system prompt backed by the default character's prompt.md.

The default character (``is_default = 1`` in workspace.db, usually ``hiro``) owns
the system prompt file under ``<workspace>/characters/<id>/prompt.md``.
Seeding and index rows are handled by domain/character.py (Phase 1).

LLM selection (provider, model, temperature, max_tokens) lives in
preferences.json — see domain/preferences.py.
"""

from __future__ import annotations

from pathlib import Path

from .character import load_default_character_prompt, save_default_character_prompt


def load_system_prompt(workspace_path: Path) -> str:
    """Load the system prompt from the default character's prompt.md."""
    return load_default_character_prompt(workspace_path)


def save_system_prompt(workspace_path: Path, prompt: str) -> None:
    """Persist a new system prompt to the default character's prompt.md."""
    save_default_character_prompt(workspace_path, prompt)
