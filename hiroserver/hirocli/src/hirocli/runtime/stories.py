"""The core's own stories (the logging plan's phase 6a): what the core starts and names, each with its kind.

A story is listed only when its feature names it (`story.named`), and only with a declared name; the apps declare
theirs in `Extension(stories=...)`, the core here. Importing this module declares them in the process.

    with stories.started(stories.MEMORY_SWEEP, "memory.sweep", area="AGENT"):
        ...
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from hiro_commons.logging_foundation import story
from hiro_commons.logging_foundation.story import Declared

CHAT_TURN = Declared("core.chat_turn", "conversation", "Chat turn")
MEMORY_SWEEP = Declared("core.memory_sweep", "round", "Memory sweep")
KNOWLEDGE_INGEST = Declared("core.knowledge_ingest", "job", "Knowledge ingest")
GRAPH_INGEST = Declared("core.graph_ingest", "job", "Knowledge graph ingest")
TRY_PROFILE = Declared("core.try_profile", "action", "Try an AI profile")
TRY_VOICE = Declared("core.try_voice", "action", "Try a voice")
GENERATE_IMAGE = Declared("core.generate_image", "action", "Generate an image")
EXTENSION_APPROVED = Declared("core.extension_approved", "action", "Approve an app")  # Permissions phase 8
# Installing apps, phase 5: the core's own part of an install (the package unpacked, the service started) and of a
# removal (what it kept for the app dropped)
EXTENSION_INSTALL = Declared("core.extension_install", "job", "Install an app")
EXTENSION_REMOVE = Declared("core.extension_remove", "action", "Remove an app")
EXTENSION_UPGRADE = Declared("core.extension_upgrade", "job", "Upgrade an app")

STORIES = (CHAT_TURN, MEMORY_SWEEP, KNOWLEDGE_INGEST, GRAPH_INGEST, TRY_PROFILE, TRY_VOICE, GENERATE_IMAGE,
           EXTENSION_APPROVED, EXTENSION_INSTALL, EXTENSION_REMOVE, EXTENSION_UPGRADE)
story.declare(*STORIES)


@contextmanager
def started(declared: Declared, step: str, *, title: str | None = None, area: str = story.AREA, own: bool = False,
            **fields: Any) -> Iterator[story.Step]:
    """A step named as this story. Under the current story (an admin request's), or with `own` a story of its own
    even inside another (a job a request starts runs on after its answer): it then names the story it came from
    (`story.from`)."""
    came_from = story.current_id() if own else None
    opened = (story.begin(step, area=area, level=logging.DEBUG) if own
              else story.step(step, area=area, level=logging.DEBUG))
    with opened as s:
        extra = {"story.from": came_from} if came_from else {}
        story.named(declared.name, title, **extra, **fields)
        yield s
