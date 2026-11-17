"""One-time conversion of ``preferences.json`` v4 → v5: embedding and reranker profiles (``models_search``).

v4 picked a model per search: a workspace default (``llm.default_embedder``, ``llm.default_reranker``) and an
override per leg (``graph.embedder_model``, ``knowledge.default_embedding_model``, ``graph.reranker.model_id``
and ``device``, ``knowledge.retrieval.reranker.model_id`` and ``device``; its ``batch_size`` was never read). v5 keeps the models in
profiles (``embedding.profiles``, ``rerank.profiles``) and points each of Hiro's four searching uses at one
(``graph.embedder_profile``, ``knowledge.embedder_profile``, ``graph.reranker.profile``,
``knowledge.retrieval.reranker.profile``). Runs from ``load_preferences`` on the RAW JSON, before validation,
when ``version < 5`` (after ``convert_v4`` for an older file); a v5 file is never touched.

Every leg keeps the model it used (its override, else the default), so search and the embedder locks behave as
before:

1. Copies ``preferences.json`` to ``preferences.v4.json`` (only when that copy doesn't exist yet).
2. The default model becomes "Default embedder" / "Default reranker" (``default-embedder`` /
   ``default-reranker``), even when no leg uses it, so the choice isn't lost.
3. Each leg points at the profile with its exact settings (model; for a reranker also its device), made
   for it when none has them: "Memory embedder" (``graph-embedder``), "Knowledge embedder",
   "Memory reranker", "Knowledge reranker". A leg with no model anywhere gets no profile (as before: no
   embedder blocks indexing, no reranker keeps the search order).
4. A model in a form the profile refuses is skipped with a WARNING naming the leg; the load never fails
   because of it.

The caller validates the result, saves it as version 5 and logs one summary line.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hiro_commons.constants.storage import PREFERENCES_FILENAME
from pydantic import ValidationError

from .convert_v4 import _get_path, _pop_path, _set_path
from .models_search import EmbeddingProfile, RerankProfile

logger = logging.getLogger(__name__)

PREFERENCES_V4_BACKUP = "preferences.v4.json"
V5 = 5


@dataclass(frozen=True)
class _EmbedLeg:
    name: str
    old_path: str
    pick_path: str
    profile_id: str
    label: str


@dataclass(frozen=True)
class _RerankLeg:
    name: str
    old_model: str
    old_device: str
    pick_path: str
    profile_id: str
    label: str


EMBED_LEGS = (
    _EmbedLeg("graph", "graph.embedder_model", "graph.embedder_profile", "graph-embedder", "Memory embedder"),
    _EmbedLeg(
        "knowledge", "knowledge.default_embedding_model", "knowledge.embedder_profile", "knowledge-embedder",
        "Knowledge embedder",
    ),
)
RERANK_LEGS = (
    _RerankLeg(
        "graph", "graph.reranker.model_id", "graph.reranker.device", "graph.reranker.profile",
        "graph-reranker", "Memory reranker",
    ),
    _RerankLeg(
        "knowledge", "knowledge.retrieval.reranker.model_id", "knowledge.retrieval.reranker.device",
        "knowledge.retrieval.reranker.profile", "knowledge-reranker",
        "Knowledge reranker",
    ),
)
DEFAULT_EMBEDDER = ("default-embedder", "Default embedder")
DEFAULT_RERANKER = ("default-reranker", "Default reranker")

# Old leaves dropped from the raw JSON (pydantic would ignore them, but the saved v5 file stays clean).
OLD_PREFERENCE_PATHS = (
    "llm.default_embedder",
    "llm.default_reranker",
    "graph.embedder_model",
    "graph.reranker.model_id",
    "graph.reranker.device",
    "knowledge.default_embedding_model",
    "knowledge.retrieval.reranker.model_id",
    "knowledge.retrieval.reranker.device",
    "knowledge.retrieval.reranker.batch_size",
)


@dataclass
class SearchConversionSummary:
    """What the conversion did (one INFO line from the caller)."""

    picks: dict[str, str | None] = field(default_factory=dict)  # pick path → profile id
    embedding_profiles: dict[str, str] = field(default_factory=dict)  # profile id → model
    rerank_profiles: dict[str, str] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)  # "<leg>: <model> (<why>)"
    backup: str | None = None

    def line(self) -> str:
        def profiles(rows: dict[str, str]) -> str:
            return ", ".join(f"{pid}={model}" for pid, model in rows.items()) or "none"

        parts = [
            f"embedding profiles: {profiles(self.embedding_profiles)}",
            f"reranker profiles: {profiles(self.rerank_profiles)}",
            f"picks: {', '.join(f'{p}={v or 'none'}' for p, v in self.picks.items())}",
        ]
        if self.skipped:
            parts.append(f"skipped: {'; '.join(self.skipped)}")
        return " · ".join(parts)


def needs_search_conversion(data: Any) -> bool:
    """True for a raw preferences dict older than v5."""
    if not isinstance(data, dict):
        return False
    try:
        return int(data.get("version") or 0) < V5
    except (TypeError, ValueError):
        return True


def convert_preferences_v4_to_v5(
    workspace_path: Path, data: dict[str, Any]
) -> tuple[dict[str, Any], SearchConversionSummary]:
    """Convert the raw v4 dict (a copy is returned; ``data`` is not changed). See the module notes."""
    summary = SearchConversionSummary()
    summary.backup = _backup_preferences(workspace_path)
    out: dict[str, Any] = json.loads(json.dumps(data))  # deep copy of plain JSON

    embedding = _section(out, "embedding")
    rerank = _section(out, "rerank")
    embed_profiles: dict[str, Any] = embedding["profiles"]
    rerank_profiles: dict[str, Any] = rerank["profiles"]

    _convert_embedders(out, embed_profiles, summary)
    _convert_rerankers(out, rerank_profiles, summary)

    for path in OLD_PREFERENCE_PATHS:
        _pop_path(out, path)
    out["version"] = V5
    return out, summary


def _convert_embedders(out: dict[str, Any], profiles: dict[str, Any], summary: SearchConversionSummary) -> None:
    default = _text(_get_path(out, "llm.default_embedder"))
    if default and _valid(EmbeddingProfile, {"label": DEFAULT_EMBEDDER[1], "model": default}, "default embedder",
                          summary):
        _add(profiles, DEFAULT_EMBEDDER[0], {"label": DEFAULT_EMBEDDER[1], "model": default})
        summary.embedding_profiles[DEFAULT_EMBEDDER[0]] = default
    for leg in EMBED_LEGS:
        model = _text(_get_path(out, leg.old_path)) or default
        pid = None
        if model:
            pid = _find(profiles, {"model": model})
            if pid is None and _valid(EmbeddingProfile, {"label": leg.label, "model": model}, leg.name, summary):
                pid = _add(profiles, leg.profile_id, {"label": leg.label, "model": model})
                summary.embedding_profiles[pid] = model
        _set_path(out, leg.pick_path, pid)
        summary.picks[leg.pick_path] = pid


def _convert_rerankers(out: dict[str, Any], profiles: dict[str, Any], summary: SearchConversionSummary) -> None:
    default = _text(_get_path(out, "llm.default_reranker"))
    for leg in RERANK_LEGS:
        model = _text(_get_path(out, leg.old_model)) or default
        pid = None
        if model:
            wanted = {"model": model, "device": _text(_get_path(out, leg.old_device))}
            pid = _find(profiles, wanted)
            # The default model's first profile carries the default's name; any other gets the leg's.
            pid_wanted, label = DEFAULT_RERANKER if model == default and DEFAULT_RERANKER[0] not in profiles else (
                leg.profile_id, leg.label
            )
            if pid is None and _valid(RerankProfile, {"label": label, **wanted}, leg.name, summary):
                pid = _add(profiles, pid_wanted, {"label": label, **wanted})
                summary.rerank_profiles[pid] = model
        _set_path(out, leg.pick_path, pid)
        summary.picks[leg.pick_path] = pid
    # A default no leg used is kept as a profile of its own, so the choice isn't lost.
    if default and _find(profiles, {"model": default}) is None:
        payload = {"label": DEFAULT_RERANKER[1], "model": default, "device": None}
        if _valid(RerankProfile, payload, "default reranker", summary):
            pid = _add(profiles, DEFAULT_RERANKER[0], payload)
            summary.rerank_profiles[pid] = default


def _section(out: dict[str, Any], key: str) -> dict[str, Any]:
    section = out.get(key)
    if not isinstance(section, dict):
        section = out[key] = {}
    if not isinstance(section.get("profiles"), dict):
        section["profiles"] = {}
    if not isinstance(section.get("uses"), dict):
        section["uses"] = {}
    return section


def _text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _find(profiles: dict[str, Any], wanted: dict[str, Any]) -> str | None:
    """The id of a profile already holding exactly these settings."""
    for pid, payload in profiles.items():
        if isinstance(payload, dict) and all(payload.get(k) == v for k, v in wanted.items()):
            return pid
    return None


def _add(profiles: dict[str, Any], wanted_id: str, payload: dict[str, Any]) -> str:
    pid = wanted_id
    n = 2
    while pid in profiles:
        pid = f"{wanted_id}-{n}"
        n += 1
    profiles[pid] = payload
    return pid


def _valid(cls: type, payload: dict[str, Any], what: str, summary: SearchConversionSummary) -> bool:
    try:
        cls.model_validate(payload)
    except ValidationError as exc:
        reason = exc.errors()[0].get("msg", str(exc)) if exc.errors() else str(exc)
        summary.skipped.append(f"{what}: {payload.get('model')} ({reason})")
        logger.warning(
            "⚠️ Preferences v5 conversion — %s model skipped: %s (%s)", what, payload.get("model"), reason
        )
        return False
    return True


def _backup_preferences(workspace_path: Path) -> str | None:
    src = workspace_path / PREFERENCES_FILENAME
    dest = workspace_path / PREFERENCES_V4_BACKUP
    if dest.exists() or not src.is_file():
        return str(dest) if dest.exists() else None
    try:
        shutil.copy2(src, dest)
    except OSError as exc:
        # The conversion still runs (the old file is about to be replaced): say so loudly.
        logger.error("❌ preferences.v4.json backup failed — workspace · preferences v5 conversion",
                     extra={"error": str(exc), "workspace_path": str(workspace_path)})
        return None
    return str(dest)


__all__ = [
    "PREFERENCES_V4_BACKUP",
    "SearchConversionSummary",
    "V5",
    "convert_preferences_v4_to_v5",
    "needs_search_conversion",
]
