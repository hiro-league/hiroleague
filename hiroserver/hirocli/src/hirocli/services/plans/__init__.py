"""Plan tools — Claude Code and Codex on the owner's own plans, as AI profile providers (Phase 7a Part B).

Ported from HomeHiro's ``agents/`` and the plan half of ``llm/providers.py``:

- ``kinds``    — each tool: status / sign-in / sign-out / test commands, and an ask's question and answer;
- ``cli``      — running them: their own folders under ``<workspace>/plans/``, a clean environment, timeouts;
- ``signin``   — the sign-in flows (Claude: paste the code back; Codex: a device code);
- ``status``   — who is signed in (read at most every 5 minutes) and when a sign-in ends by itself;
- ``updates``  — npm install / nightly update into ``<workspace>/plans/tools``;
- ``models``   — the models each tool offers, read from the tool's own files;
- ``provider`` — the ``ai_ask`` plan-tool seam: lines (wait vs busy), a folder per ask, the API-price estimate;
- ``ops``      — what the plan_* tools call.
"""

from __future__ import annotations

from .cli import NotInstalled, PlanToolError, plans_dir, tool_home, tools_folder
from .kinds import PLAN_KINDS, PlanKind

__all__ = ["NotInstalled", "PLAN_KINDS", "PlanKind", "PlanToolError", "plans_dir", "tool_home", "tools_folder"]
