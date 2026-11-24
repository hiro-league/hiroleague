"""Which connected devices get a frame from the core (Permissions phase 3).

A device is sent only its own person's replies, messages and notices: a frame about a conversation goes to the
connected devices of that conversation's person, and a frame the core sends to no device in particular would reach
every device through the gateway, so it never leaves without one. One object, on the server context, shared by the
outbound pipeline and the resource hints; the gateway's device events keep its list of connected devices.
"""

from __future__ import annotations

from pathlib import Path

from hiro_commons.log import Logger

from ..domain.conversation_channel import _get_channel_by_id, parse_chat_channel_id
from ..domain.data_store import get_default_user_id, person_of_chat_user
from ..domain.pairing import device_ids_of
from ..domain.people import list_people
from ..domain.talkers import owner_person

log = Logger.get("DEVICE.TARGETING")


class DeviceTargeting:
    """The connected devices, and which of them may get a frame about a conversation."""

    def __init__(self, workspace_path: Path) -> None:
        self._workspace_path = workspace_path
        self._connected: set[str] = set()

    # -- the gateway's device events (resource_change_broadcaster.py, infra_event_handlers.py) ---------------------

    def connected(self, device_id: str) -> None:
        self._connected.add(device_id)

    def disconnected(self, device_id: str) -> None:
        self._connected.discard(device_id)

    def clear(self) -> None:
        self._connected.clear()

    # -- who gets a frame ---------------------------------------------------------------------------------------------

    def all_connected(self) -> list[str]:
        """Every connected device: for a notice about something every device reads (characters, settings)."""
        return sorted(self._connected)

    def for_conversation(self, chat_channel_id: object) -> list[str]:
        """The connected devices of a conversation's person; none when it is nobody's we know. Reads the database:
        call it off the loop."""
        if not list_people(self._workspace_path):
            # No family list yet: every device and conversation is the owner's
            return self.all_connected()
        try:
            channel = _get_channel_by_id(self._workspace_path, parse_chat_channel_id(chat_channel_id))
        except ValueError:
            channel = None
        if channel is None:
            log.warning("⚠️ A frame names a conversation that isn't there — sent to no device", conversation=str(chat_channel_id))
            return []
        return self.for_chat_user(channel.user_id)

    def for_chat_user(self, user_id: int) -> list[str]:
        """The connected devices of a chat user's person."""
        if not list_people(self._workspace_path):
            return self.all_connected()
        return self.for_person(self._person_of_user(user_id))

    def for_person(self, person_id: str) -> list[str]:
        """A person's connected devices."""
        if not person_id:
            return []
        return sorted(device_ids_of(self._workspace_path, person_id) & self._connected)

    def _person_of_user(self, user_id: int) -> str:
        person_id = person_of_chat_user(self._workspace_path, user_id)
        if person_id:
            return person_id
        # The seeded chat user before its owner first talks: the owner's, as every conversation before phase 3
        if user_id == get_default_user_id(self._workspace_path):
            owner = owner_person(list_people(self._workspace_path))
            return owner.person_id if owner else ""
        return ""
