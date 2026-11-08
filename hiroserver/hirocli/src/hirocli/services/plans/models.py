"""The models each plan tool offers, read from the tool itself (ported from HomeHiro's llm/models.py).

- **Codex**: the models it lists for the owner's plan in its ``models_cache.json`` (in its own folder,
  written when it first runs), with each one's thinking levels; only listed ones that read pictures.
- **Claude Code**: its names for the newest of each family (haiku, sonnet, opus), plus the extra models
  the owner's account gets (its settings file, ``additionalModelOptionsCache``).

Read when asked (a couple of small files): an AI profile names the model as ``claude_code:<id>`` /
``codex:<id>``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import cli
from .kinds import PLAN_KINDS

CLAUDE_FAMILIES = [
    ("haiku", "Haiku", "the newest Haiku: fastest, lightest on the plan"),
    ("sonnet", "Sonnet", "the newest Sonnet: a good default"),
    ("opus", "Opus", "the newest Opus: strong, heavy on the plan"),
]
CLAUDE_EFFORTS = ["low", "medium", "high", "xhigh", "max"]


@dataclass
class PlanModel:
    id: str
    name: str
    about: str = ""
    thinking: list[str] = field(default_factory=list)  # the levels it takes ([] = the tool's own default only)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def plan_models(workspace_path: Path, provider_id: str) -> tuple[list[PlanModel], str | None]:
    """(models, why they couldn't be read). Claude Code always has its family names."""
    if provider_id == "codex":
        try:
            return _codex(workspace_path), None
        except ValueError as exc:
            return [], str(exc)
    if provider_id == "claude_code":
        return _claude(workspace_path), None
    return [], f"{provider_id!r} isn't a plan tool"


def model_levels(workspace_path: Path, provider_id: str, model: str) -> list[str]:
    found = next((m for m in plan_models(workspace_path, provider_id)[0] if m.id == model), None)
    return list(found.thinking) if found else []


def _codex(workspace_path: Path) -> list[PlanModel]:
    path = cli.tool_home(workspace_path, PLAN_KINDS["codex"]) / "models_cache.json"
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError("Codex hasn't listed its models here yet (it does when it first runs: try plan_test)") from None
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Codex's model list can't be read: {exc}") from exc
    out: list[PlanModel] = []
    for m in d.get("models") or []:
        if not isinstance(m, dict) or m.get("visibility") != "list":
            continue
        if "image" not in (m.get("input_modalities") or ["image"]):
            continue
        levels = [str(x.get("effort") if isinstance(x, dict) else x) for x in m.get("supported_reasoning_levels") or []]
        slug = str(m.get("slug") or "")
        if slug:
            out.append(PlanModel(slug, str(m.get("display_name") or slug), str(m.get("description") or ""), levels))
    if not out:
        raise ValueError("Codex lists no models")
    return out


def _claude(workspace_path: Path) -> list[PlanModel]:
    out = [PlanModel(i, n, a, list(CLAUDE_EFFORTS)) for i, n, a in CLAUDE_FAMILIES]
    path = cli.tool_home(workspace_path, PLAN_KINDS["claude_code"]) / ".claude.json"
    try:
        extra = json.loads(path.read_text(encoding="utf-8")).get("additionalModelOptionsCache") or []
    except FileNotFoundError:
        extra = []
    except (OSError, json.JSONDecodeError, AttributeError):
        extra = []  # its settings file mid-write or changed shape: the family names still work
    for m in extra:
        if not isinstance(m, dict):
            continue
        value, words = str(m.get("value") or ""), str(m.get("description") or "")
        if value and value not in {x.id for x in out}:
            name, _, about = words.partition(" · ")
            out.append(PlanModel(value, name or str(m.get("label") or value), about, list(CLAUDE_EFFORTS)))
    return out
