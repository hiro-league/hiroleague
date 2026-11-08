"""What the plan_* tools (tools/ai_plans.py) do, on one workspace. Blocking: call from a thread."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from hiro_commons.log import Logger

from . import cli, status
from .kinds import PLAN_KINDS, TEST_QUESTION, PlanKind
from .models import plan_models
from .signin import SignInOut, signins
from .updates import updater

log = Logger.get("PLANS")

SIGNOUT_TIMEOUT = 30.0
TEST_TIMEOUT = 120.0


def plan_kind(tool_id: str) -> PlanKind:
    kind = PLAN_KINDS.get((tool_id or "").strip())
    if kind is None:
        raise ValueError(f"tool must be one of {', '.join(PLAN_KINDS)}, got {tool_id!r}")
    return kind


def tool_status(workspace_path: Path, kind: PlanKind, *, fresh: bool = False) -> dict[str, Any]:
    """One tool's row: installed version, sign-in (who, plan, since, ends), models, a running sign-in."""
    if fresh:
        status.recheck(workspace_path, kind)
    seen = status.view(workspace_path, kind)
    models, models_problem = plan_models(workspace_path, kind.id)
    versions = updater.state(workspace_path).versions
    s = seen.status
    return {
        "id": kind.id,
        "name": kind.name,
        "installed": kind.id in versions or seen.problem is None,
        "version": versions.get(kind.id),
        "signed_in": bool(s and s.signed_in),
        "account": s.account if s else None,
        "plan": s.plan if s else None,
        "method": s.method if s else None,
        "problem": seen.problem,
        "signed_in_at": seen.signed_in_at.isoformat() if seen.signed_in_at else None,
        "sign_in_ends_at": seen.ends_at.isoformat() if seen.ends_at else None,
        "attention": seen.attention,
        "takes_code": kind.takes_code,
        "models": [m.to_dict() for m in models],
        "models_problem": models_problem,
        "sign_in": signins.state(workspace_path, kind).to_dict(),
        "queue_note": "Waiting asks take their turn; an app is told it's busy and asks again.",
    }


def all_status(workspace_path: Path, tool_id: str | None = None, *, fresh: bool = False) -> dict[str, Any]:
    kinds = [plan_kind(tool_id)] if tool_id else list(PLAN_KINDS.values())
    return {
        "tools": [tool_status(workspace_path, k, fresh=fresh) for k in kinds],
        "updates": updater.state(workspace_path).to_dict(),
    }


def sign_in(workspace_path: Path, kind: PlanKind, action: str, code: str | None = None) -> SignInOut:
    """``start`` a sign-in, read its ``state``, paste the ``code`` (Claude), or ``cancel`` it."""
    if action == "start":
        return signins.begin(workspace_path, kind)
    if action == "state":
        return signins.state(workspace_path, kind)
    if action == "code":
        return signins.send_code(workspace_path, kind, code or "")
    if action == "cancel":
        return signins.drop(workspace_path, kind)
    raise ValueError("action must be start, state, code or cancel")


def sign_out(workspace_path: Path, kind: PlanKind) -> dict[str, Any]:
    signins.drop(workspace_path, kind)
    r = cli.run(workspace_path, kind, kind.signout_args, "sign-out", SIGNOUT_TIMEOUT)
    status.note_signed_out(workspace_path, kind)
    log.info(f"🔌 Plan tool signed out — {kind.name}", exit_code=r.code)
    return {"id": kind.id, "signed_out": r.code == 0, "message": (r.err or r.out).strip()[-300:] or None}


def test(workspace_path: Path, kind: PlanKind) -> dict[str, Any]:
    """One short question with no tools: whether the sign-in, the plan and the tool work."""
    started = time.monotonic()
    r = cli.run(workspace_path, kind, kind.test_args(TEST_QUESTION), "a test question", TEST_TIMEOUT)
    ms = int((time.monotonic() - started) * 1000)
    try:
        answer = kind.test_answer(r.out, r.err)
    except ValueError as exc:
        status.recheck(workspace_path, kind)
        said = (r.err or r.out).strip()[-300:]
        return {"id": kind.id, "ok": False, "ms": ms, "answer": None, "model": None, "error": f"{exc}: {said}".strip(": ")}
    return {"id": kind.id, "ok": True, "ms": ms, "answer": answer.text, "model": answer.model, "error": None}
