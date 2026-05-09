"""Runtime workspace selection for the Svelte admin API (header + hosting fallback).

Kept separate from FastAPI so logic stays importable without HTTP dependencies.
"""

from __future__ import annotations

from importlib import metadata
from typing import Any

from hirocli.admin.context import get_runtime_context
from hirocli.domain.workspace import resolve_workspace


def _hosting_workspace_id() -> str | None:
    ctx = get_runtime_context()
    return ctx.hosting_workspace_id if ctx else None


def _selected_workspace_id(header_workspace_id: str | None) -> str | None:
    selected = (header_workspace_id or "").strip()
    return selected or _hosting_workspace_id()


def _workspace_name(workspace_id: str | None) -> str | None:
    try:
        entry, _ = resolve_workspace(workspace_id)
        return entry.name
    except Exception:
        ctx = get_runtime_context()
        return ctx.hosting_workspace_name if ctx else None


def _package_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "unknown"


def _hiro_package_version() -> str:
    version = _package_version("hiroleague")
    return version if version != "unknown" else _package_version("hirocli")
