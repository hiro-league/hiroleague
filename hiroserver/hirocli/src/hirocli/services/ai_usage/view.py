"""AI usage rows as the AI usage page shows them (Phase 7b): names instead of ids.

Rows are stored with ids (source, use, profile, person), so a renamed profile or person reads by
its current name everywhere; what no longer exists reads by the name kept with the row (a
profile) or by its id. The page groups and filters on these names.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from hiro_commons.log import Logger

from ...domain.extensions import list_paired_extensions
from ...domain.people import list_people
from ...domain.preferences import WorkspacePreferences
from .store import HIRO_SOURCE, read_rows

log = Logger.get("AI.USAGE")

KIND_LABELS = {
    "question": "Question",
    "speech": "Speech",
    "transcription": "Transcription",
    "image": "Image",
    "embedding": "Embedding",
    "rerank": "Reranking",
}

# The core's own uses (source ``hiro``), as people name them.
HIRO_USE_LABELS = {
    "try_it": "Try it",
    "chat": "Chat",
    "memory": "Memory",
    "knowledge": "Knowledge",
    "graph": "Graph",
    "eval": "Eval",
    "vision": "Reading pictures",
    "voice_replies": "Voice replies",
    "voice_notes": "Voice notes",
    "image_generation": "Image generation",
    "embeddings": "Embeddings",
}

NO_PROFILE = "No profile"


def page_rows(workspace_path: Path, prefs: WorkspacePreferences, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """The hours in [start, end) as the page's rows (``UsageRow`` in the admin's ai-usage.ts)."""
    rows = read_rows(workspace_path, start, end)
    if not rows:
        return []
    names = _Names(workspace_path, prefs)
    return [names.row(r) for r in rows]


class _Names:
    """The current names of what rows point at, read once per page load."""

    def __init__(self, workspace_path: Path, prefs: WorkspacePreferences) -> None:
        self.profiles = {pid: p.label for pid, p in prefs.ai.profiles.items()}
        self.sources: dict[str, str] = {HIRO_SOURCE: "Hiro"}
        self.uses: dict[tuple[str, str], str] = {(HIRO_SOURCE, k): v for k, v in HIRO_USE_LABELS.items()}
        try:
            for ext in list_paired_extensions(workspace_path):
                self.sources[ext.name] = ext.name[:1].upper() + ext.name[1:]
                for use in ext.declared_uses():
                    self.uses[(ext.name, use["id"])] = str(use.get("name") or use["id"])
        except Exception as exc:  # names only: the page still reads with ids
            log.warning("⚠️ AI usage — extension names unreadable", error=str(exc))
        try:
            self.people = {p.person_id: p.name for p in list_people(workspace_path)}
        except Exception as exc:
            log.warning("⚠️ AI usage — people unreadable", error=str(exc))
            self.people = {}

    def row(self, r: dict[str, Any]) -> dict[str, Any]:
        source = r["source"]
        pid = r["profile_id"]
        person = r["person_id"]
        return {
            "hour": int(datetime.fromisoformat(r["hour"].replace("Z", "+00:00")).timestamp() * 1000),
            "kind": KIND_LABELS.get(r["kind"], r["kind"]),
            "source": self.sources.get(source, source[:1].upper() + source[1:]),
            "use": self.uses.get((source, r["use_id"]), r["use_id"] or KIND_LABELS.get(r["kind"], r["kind"])),
            "profile": (self.profiles.get(pid) or r["profile_name"] or pid) if pid else NO_PROFILE,
            "provider": r["provider"],
            "model": r["model"],
            "billing": r["billing"],
            "person": (self.people.get(person) or person) if person else None,
            "label": r["label"] or None,
            "result": r["result"],
            "requests": r["requests"],
            "tokensIn": r["tokens_in"],
            "tokensOut": r["tokens_out"],
            "ms": r["ms"],
            "cost": r["cost"],
            "estimate": r["estimate"],
            "unpriced": r["unpriced"],
        }
