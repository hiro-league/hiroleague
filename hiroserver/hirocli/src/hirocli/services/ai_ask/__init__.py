"""AI asks — the core answers extensions' questions on AI profiles (Phase 7a).

Contract: ``docs/phase7a-ai-asks-design.md``. Profiles and uses live in preferences (``prefs.ai``);
the ask runs here: ``runner`` (profile/use resolution, the fallback walk, limits, at_once,
timeouts), ``providers`` (API and local models through ``model_factory``; the plan-tool seam),
``targets`` (what a profile's model is), ``usage`` (``ai_usage`` counts in workspace.db) and
``catalog_view`` (what the admin, CLI and extensions read).
"""

from __future__ import annotations

from .catalog_view import budget_hint, extension_use_map, job_rows, profile_rows, use_rows
from .errors import ASK_ERROR_CODES, AskError, ProviderFailed
from .providers import PlanCall, PlanTool, ProviderResult, register_plan_tool
from .runner import DRAFT_PROFILE_ID, AskAnswer, AskRequest, AskRunner, get_ask_runner

__all__ = [
    "ASK_ERROR_CODES",
    "AskAnswer",
    "AskError",
    "AskRequest",
    "AskRunner",
    "DRAFT_PROFILE_ID",
    "PlanCall",
    "PlanTool",
    "ProviderFailed",
    "ProviderResult",
    "budget_hint",
    "extension_use_map",
    "get_ask_runner",
    "job_rows",
    "profile_rows",
    "register_plan_tool",
    "use_rows",
]
