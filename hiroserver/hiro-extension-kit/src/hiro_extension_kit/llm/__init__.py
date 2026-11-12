"""the app's questions to an AI. Since Phase 7a the HiroLeague core answers them, with its AI profiles, budgets and
fallbacks (profiles.py asks it through hiroleague.link); the app keeps its own log of what was asked (recorder.py,
Logs → LLM requests); what that adds up to is counted by the core (Phase 7b: its Logs → AI usage).

Here: the error every caller handles, how much of a picture the model reads, and reading a reply's JSON."""

import json
import re
from typing import Any, Literal

from ..errors import OutsideError

Detail = Literal["low", "medium", "high"]
# A ```json … ``` block around a reply asked for JSON alone (Gemma 4 31B, 2026-10-02: 66 of 531 cam1 answers lost as
# "not JSON", each ending in the block's closing ```).
FENCE_OPEN = re.compile(r"^```(?:json)?", re.IGNORECASE)
FENCE_CLOSE = re.compile(r"```$")


class LLMError(OutsideError):
    """The question couldn't be asked or answered. status: 400 for our side, 502 for the AI's (or the core's)."""


def json_reply(text: str | None) -> Any:
    """A reply's JSON, without a code block around it. ValueError when it isn't JSON."""
    text = FENCE_CLOSE.sub("", FENCE_OPEN.sub("", (text or "").strip())).strip()
    return json.loads(text)


__all__ = ["Detail", "LLMError", "json_reply"]
