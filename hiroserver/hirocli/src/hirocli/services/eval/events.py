"""Eval event plumbing — publish, cooperative-cancel polling, preview.

Leaf module shared by both runners (knowledge + memory). Holds no track logic: the
``event_type`` is always passed in by the caller (one of the ``EVAL_*``
constants), so this module has no dependency on ``constants`` and never imports the
runners — keeping it at the bottom of the eval import graph.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from hiro_commons.log import Logger

from hirocli.domain.events import DomainEvent

log = Logger.get("SVC.KNOWLEDGE.EVAL")


def _publish(
    bus: Any, workspace_path: Path, event_type: str, payload: dict[str, Any]
) -> None:
    """Wrap publish in a try/except so a bus glitch never aborts the run.

    The event bus already wraps handlers in try/except; this guards the
    publish path itself (e.g. if the loop is detached during shutdown)."""
    try:
        bus.publish(
            DomainEvent(type=event_type, workspace_path=workspace_path, payload=dict(payload))
        )
    except Exception:
        log.warning("⚠️ knowledge.eval — event publish failed", event_type=event_type, exc_info=True)


def _cancel_requested(workspace_path: Path, run_id: str) -> bool:
    """True when the cancel route flipped ``cancel_requested`` for this run (see
    ``_raise_if_cancelled`` for why the flag exists alongside ``task.cancel()``)."""
    from hirocli.services.eval.registry import get_eval_registry

    state = get_eval_registry().get_run(workspace_path)
    return state is not None and state.run_id == run_id and state.cancel_requested


def _raise_if_cancelled(workspace_path: Path, run_id: str) -> None:
    """Cooperative cancel — stop the run between questions even when ``task.cancel()``'s
    ``CancelledError`` was swallowed deep in the async stack (graphiti/litellm/LangChain).

    The cancel route flips ``cancel_requested`` on the registry's run state (and also calls
    ``task.cancel()``); we poll that flag at the top of each question and raise
    ``CancelledError`` ourselves so the route's terminal-cancel path emits
    ``eval.cancelled``. Before this, the loops relied solely on the *one-shot*
    ``task.cancel()`` exception surviving every ``await`` — if any layer absorbed it, the run
    sailed on to completion (see ``registry.request_cancel``)."""
    if _cancel_requested(workspace_path, run_id):
        log.info("🛑 knowledge.eval — cooperative cancel honored · run_id=%s", run_id)
        raise asyncio.CancelledError()


def _preview(text: str, limit: int) -> str:
    s = " ".join((text or "").split())
    return s if len(s) <= limit else s[: limit - 1] + "…"
