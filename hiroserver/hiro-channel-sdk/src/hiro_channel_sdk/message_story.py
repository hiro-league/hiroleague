"""A chat message's story at one hop: the device, the gateway, a channel plugin, the server and back.

A chat story takes the message's own id, which the device makes (`story.id_for(msg_id)`), so every hop finds the same
story even when nothing was carried to it. Each hop is a timed step; the step travels on in the frame, in
`routing.metadata["traceparent"]` (W3C Trace Context), so the next process's step is a child of this one.

    with message_story.hop("devices.receive", msg.routing.metadata, msg_id, area="DEVICES"):
        ...  # handle the frame; the metadata now carries this hop

Only frames that belong to a message's story get a step: a chat message, its events and its replies (they have a
`msg_id`, as `unified_message_log_scope` gives it), or a frame that carries a story in. JSON-RPC requests and
responses carry none and get none.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from typing import Any

from hiro_commons.logging_foundation import story


@contextmanager
def hop(name: str, metadata: MutableMapping[str, Any] | None, msg_id: str | None, *, area: str,
        level: int = logging.INFO, **fields: Any) -> Iterator[story.Step | None]:
    """This hop of the message's story as a timed step, continued from the frame's metadata (or started from the
    message's id), and carried on in the same metadata. No step (None) for a frame of no message's story."""
    carried = metadata.get(story.TRACEPARENT) if metadata is not None else None
    if not msg_id and not carried:
        yield None
        return
    with story.begin(name, parent=carried if isinstance(carried, str) else None,
                     story_id=story.id_for(msg_id) if msg_id else None, area=area, level=level, **fields) as step:
        if metadata is not None:
            story.inject(metadata)
        yield step
