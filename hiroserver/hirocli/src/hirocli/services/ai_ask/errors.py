"""Why an ask got no answer — the error codes of the ``ai.ask`` contract."""

from __future__ import annotations

from typing import Any

from hiro_channel_sdk.constants import (
    AI_ERROR_BUDGET,
    AI_ERROR_BUSY,
    AI_ERROR_FAILED,
    AI_ERROR_INVALID,
    AI_ERROR_NO_PROFILE,
)

ASK_ERROR_CODES: frozenset[str] = frozenset(
    {AI_ERROR_NO_PROFILE, AI_ERROR_BUDGET, AI_ERROR_BUSY, AI_ERROR_FAILED, AI_ERROR_INVALID}
)


class AskError(Exception):
    """The ask was not answered. ``code`` is one of ASK_ERROR_CODES; ``message`` is for people.

    ``notes`` and ``tries`` say what the fallback walk did (the same shapes as an answer's).
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        notes: list[str] | None = None,
        tries: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.notes = list(notes or [])
        self.tries = list(tries or [])


class ProviderFailed(Exception):
    """One profile's provider couldn't answer (bad key, server off, timeout, unreadable answer).

    The walk passes over to the profile's fallback.
    """
