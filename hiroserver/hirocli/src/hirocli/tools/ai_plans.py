"""Plan tool tools (Phase 7a Part B) — Claude Code and Codex on the owner's plans, for the admin, CLI and HTTP.

- ``plan_status``   — each tool: installed version, who is signed in, when the sign-in ends, its models, the
  last / next npm update, a running sign-in;
- ``plan_sign_in``  — ``start`` a sign-in (Claude: a link, then paste the code its page shows; Codex: a link
  and a device code to type there), read its ``state``, send the ``code``, or ``cancel``;
- ``plan_sign_out`` — sign the tool out (only the core's own copy of its login);
- ``plan_update``   — install / update both tools with npm into ``<workspace>/plans/tools`` now;
- ``plan_test``     — one short question, to see the sign-in and the plan work.

A sign-in holds a running program, so it lives in the process that started it: the admin's (the server)
or the CLI's own (``hiro ai plan sign-in`` runs the whole flow in the terminal).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..domain.workspace import resolve_workspace
from .base import Tool, ToolParam

_TOOL_HELP = "claude_code or codex"


def _path(workspace: str | None) -> Path:
    entry, _ = resolve_workspace(workspace)
    return Path(entry.path)


@dataclass
class PlanStatusResult:
    tools: list[dict[str, Any]] = field(default_factory=list)
    updates: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlanSignInResult:
    tool: str
    state: str
    link: str | None = None
    code: str | None = None
    takes_code: bool = False
    code_sent: bool = False
    message: str | None = None


@dataclass
class PlanSignOutResult:
    tool: str
    signed_out: bool
    message: str | None = None


@dataclass
class PlanUpdateResult:
    updates: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlanTestResult:
    tool: str
    ok: bool
    ms: int
    answer: str | None = None
    model: str | None = None
    error: str | None = None


class PlanStatusTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "plan_status"
    description = "Show Claude Code / Codex on the owner's plans: installed, signed in, sign-in end, models, updates"
    params = {
        "tool": ToolParam(str, f"Only this tool ({_TOOL_HELP}); both when empty", required=False),
        "fresh": ToolParam(bool, "Read who is signed in now (else at most every 5 minutes)", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, tool: str | None = None, fresh: bool = False, workspace: str | None = None) -> PlanStatusResult:
        from ..services.plans.ops import all_status

        out = all_status(_path(workspace), (tool or "").strip() or None, fresh=bool(fresh))
        return PlanStatusResult(tools=out["tools"], updates=out["updates"])


class PlanSignInTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "plan_sign_in"
    description = (
        "Sign Claude Code or Codex in with the owner's plan: action start (shows a link; Codex also a code to "
        "type there), state (poll), code (paste the code Claude's page shows), cancel"
    )
    params = {
        "tool": ToolParam(str, _TOOL_HELP),
        "action": ToolParam(str, "start (default), state, code or cancel", required=False),
        "code": ToolParam(str, "The code Claude's page shows (action code)", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(
        self, tool: str, action: str | None = None, code: str | None = None, workspace: str | None = None
    ) -> PlanSignInResult:
        from ..services.plans.ops import plan_kind, sign_in

        kind = plan_kind(tool)
        out = sign_in(_path(workspace), kind, (action or "start").strip(), code)
        return PlanSignInResult(tool=kind.id, **out.to_dict())


class PlanSignOutTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "plan_sign_out"
    description = "Sign Claude Code or Codex out of the core (the owner's own desktop tools stay signed in)"
    params = {
        "tool": ToolParam(str, _TOOL_HELP),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, tool: str, workspace: str | None = None) -> PlanSignOutResult:
        from ..services.plans.ops import plan_kind, sign_out

        out = sign_out(_path(workspace), plan_kind(tool))
        return PlanSignOutResult(tool=out["id"], signed_out=out["signed_out"], message=out["message"])


class PlanUpdateTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "plan_update"
    description = "Install or update Claude Code and Codex with npm (needs Node.js and npm on PATH)"
    params = {
        "wait": ToolParam(bool, "Wait for npm to finish (else it runs in the background)", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, wait: bool = True, workspace: str | None = None) -> PlanUpdateResult:
        from ..services.plans.updates import updater

        return PlanUpdateResult(updates=updater.update(_path(workspace), background=not wait).to_dict())


class PlanTestTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "plan_test"
    description = "Ask Claude Code or Codex one short test question (uses the plan a little)"
    params = {
        "tool": ToolParam(str, _TOOL_HELP),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, tool: str, workspace: str | None = None) -> PlanTestResult:
        from ..services.plans.ops import plan_kind, test

        out = test(_path(workspace), plan_kind(tool))
        return PlanTestResult(
            tool=out["id"], ok=out["ok"], ms=out["ms"], answer=out["answer"], model=out["model"], error=out["error"]
        )
