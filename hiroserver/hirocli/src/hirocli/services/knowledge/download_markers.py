"""Unified download-marker tracking for local in-process models (rerankers + embedder).

One mechanism for "is this local model downloaded?": a marker file written only on a successful
download/load, under ``<cache_dir>/.downloaded/<slug>``. Backend-agnostic and deterministic —
replaces the earlier split of marker-files (rerankers) vs. heuristic cache scan (embedder).

Each local model type passes its own ``cache_dir`` (rerankers → ``reranker_cache``; the FastEmbed
embedder → ``fastembed_cache``); the marker scheme is identical across them.
"""

from __future__ import annotations

import re
from pathlib import Path

from hiro_commons.log import Logger

log = Logger.get("SVC.KNOWLEDGE.DOWNLOAD")

MARKER_DIR = ".downloaded"
_SIZE_UNITS = {"KB": 1_000, "MB": 1_000_000, "GB": 1_000_000_000}
_SIZE_RE = re.compile(r"([\d.]+)\s*(KB|MB|GB)", re.IGNORECASE)


def dir_size_bytes(path: Path) -> int:
    """Total size on disk of ``path`` (recursive). Best-effort — used for download progress."""
    if not path.exists():
        return 0
    total = 0
    try:
        for child in path.rglob("*"):
            try:
                if child.is_file():
                    total += child.stat().st_size
            except OSError:
                continue
    except OSError:
        return total
    return total


def parse_size_label(label: str) -> int:
    """Parse a curated size label (e.g. ``"~150 MB"``, ``"~2.3 GB"``) into approximate bytes.

    Returns 0 when unparseable — progress then falls back to indeterminate.
    """
    match = _SIZE_RE.search(label or "")
    if not match:
        return 0
    value, unit = match.group(1), match.group(2).upper()
    try:
        return int(float(value) * _SIZE_UNITS[unit])
    except (ValueError, KeyError):
        return 0


def _slug(model_id: str) -> str:
    return model_id.replace(":", "__").replace("/", "_")


def marker_path(cache_dir: Path, model_id: str) -> Path:
    return cache_dir / MARKER_DIR / _slug(model_id)


def is_marked(cache_dir: Path, model_id: str) -> bool:
    """True when a successful download/load marker exists for ``model_id`` in ``cache_dir``."""
    try:
        return marker_path(cache_dir, model_id).exists()
    except OSError:
        return False


def write_marker(cache_dir: Path, model_id: str, *, content: str = "") -> None:
    """Record a successful download/load. Best-effort — a failed write must not break the model."""
    try:
        marker = marker_path(cache_dir, model_id)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(content or model_id, encoding="utf-8")
    except OSError:
        log.warning("⚠️ Could not write download marker — %s", model_id, exc_info=True)
