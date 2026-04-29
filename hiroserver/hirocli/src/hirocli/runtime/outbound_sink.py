"""OutboundSink — protocol the CommunicationManager uses to dispatch to channels.

Defining this as a Protocol lets ``CommunicationManager`` depend on a shape
(``send_to_channel(channel_name, message)``) rather than the concrete
``ChannelManager``. This breaks the previous bidirectional import / setter
injection between the two managers.

``ChannelManager`` already exposes ``async def send_to_channel(...)`` and
satisfies this protocol structurally — no inheritance needed.
"""

from __future__ import annotations

from typing import Any, Protocol


class OutboundSink(Protocol):
    """Anything that can deliver an outbound UnifiedMessage to a named channel."""

    async def send_to_channel(
        self, channel_name: str, message: dict[str, Any]
    ) -> None: ...
