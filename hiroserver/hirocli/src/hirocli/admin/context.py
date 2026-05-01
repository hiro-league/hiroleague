"""Runtime context for Hiro Admin."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_runtime: AdminContext | None = None


@dataclass(frozen=True)
class AdminContext:
    """Immutable process context for the admin UI hosting workspace and log paths."""

    hosting_workspace_id: str | None
    hosting_workspace_name: str | None
    workspace_path: Path | None
    log_dir: Path | None
    gateway_log_dir: Path | None


def set_runtime_context(ctx: AdminContext) -> None:
    """Set the process-wide admin context during startup."""
    global _runtime
    _runtime = ctx


def get_runtime_context() -> AdminContext | None:
    """Return the context set at startup, or None if not initialized."""
    return _runtime
