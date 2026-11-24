"""The person behind a chat message (Permissions phase 3): who wrote it, whether they may talk to Hiro, and the
conversation it belongs in.

A turn belongs to the person who writes it, whatever the door:
- a paired device: the person the device belongs to;
- a chat channel (WhatsApp): the person whose number sent it (``routing.metadata.sender_number``; the sender id is
  the channel's own, often a WhatsApp LID, not the number);
- the admin or the command line: the person handed in by the caller (the signed-in person; the owner).

A message from anyone else, or from someone who may not talk, is refused before anything is kept. With no family list
yet, whoever writes from a device, the admin or the command line is the owner.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hiro_channel_sdk.models import UnifiedMessage
from hiro_commons.constants.domain import MANDATORY_CHANNEL_NAME

from ..domain.conversation_channel import (
    CHAT_CHANNEL_ID_METADATA_KEY,
    ConversationChannel,
    _get_channel_by_id,
    parse_chat_channel_id,
    person_conversation,
)
from ..domain.pairing import device_person_id
from ..domain.people import Person, find_by_number, get_person, list_people
from ..domain.talkers import chat_user_for, is_owner, may_talk, owner_person

# What the core writes on a message it let in: the writer, for the turn, its story and its AI usage. Set by the core
# only: a value a plugin sent is replaced.
PERSON_ID_METADATA_KEY = "person_id"
PERSON_NAME_METADATA_KEY = "person_name"
PERSON_OWNER_METADATA_KEY = "person_is_owner"


class NotAllowed(Exception):
    """A message the core refuses: nobody it knows, or someone who may not talk. ``reason`` is for the log."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Writer:
    person_id: str  # "" = no family list yet: the owner
    name: str
    owner: bool
    user_id: int  # their chat user: their conversations and memory group are keyed by it


def writer_of(workspace_path: Path, msg: UnifiedMessage, *, person_id: str | None = None) -> Writer:
    """The person who wrote ``msg``, if they may talk; else :class:`NotAllowed`. ``person_id`` is handed in by an
    in-process sender (the admin, the command line), never read from the message."""
    people = list_people(workspace_path)
    person = _person(workspace_path, msg, person_id, people)
    if person is None:
        if not people and msg.routing.channel == MANDATORY_CHANNEL_NAME:
            # No family list yet: a paired device, the admin or the command line is the owner's
            return Writer(person_id="", name="the owner", owner=True, user_id=_user(workspace_path, None, people))
        raise NotAllowed("the sender is nobody in the family list")
    if not may_talk(workspace_path, person):
        raise NotAllowed(f"{person.name} may not talk to Hiro")
    return Writer(
        person_id=person.person_id,
        name=person.hiro_calls_them,
        owner=is_owner(person),
        user_id=_user(workspace_path, person, people),
    )


def _user(workspace_path: Path, person: Person | None, people: list[Person]) -> int:
    user_id = chat_user_for(workspace_path, person, people)
    if user_id is None:  # chat_user_for answers None only for nobody, with a family list: refused above
        raise NotAllowed("the sender is nobody in the family list")
    return user_id


def _person(workspace_path: Path, msg: UnifiedMessage, person_id: str | None, people: list[Person]) -> Person | None:
    if person_id is not None:
        return get_person(workspace_path, person_id) if person_id else owner_person(people)
    if msg.routing.channel == MANDATORY_CHANNEL_NAME:
        pid = device_person_id(workspace_path, msg.routing.sender_id or "")
        return get_person(workspace_path, pid) if pid else None
    return find_by_number(workspace_path, str((msg.routing.metadata or {}).get("sender_number") or ""))


def conversation_for(workspace_path: Path, msg: UnifiedMessage, writer: Writer) -> ConversationChannel:
    """The conversation a message belongs in: the one a device or the admin names, which must be the writer's own;
    else (a chat channel) the writer's own General."""
    meta: dict[str, Any] = msg.routing.metadata
    raw = meta.get(CHAT_CHANNEL_ID_METADATA_KEY)
    if not raw:
        return person_conversation(workspace_path, writer.user_id)
    try:
        channel = _get_channel_by_id(workspace_path, parse_chat_channel_id(raw))
    except ValueError as exc:
        raise NotAllowed(f"the conversation it names can't be read ({exc})") from exc
    if channel is None or channel.user_id != writer.user_id:
        # Never trust a conversation a device names without checking whose it is
        raise NotAllowed(f"the conversation it names isn't {writer.name}'s")
    return channel


def stamp(msg: UnifiedMessage, writer: Writer, conversation: ConversationChannel) -> None:
    """Write the writer and the conversation on the message, over anything the sender put there."""
    meta = msg.routing.metadata
    meta[PERSON_ID_METADATA_KEY] = writer.person_id
    meta[PERSON_NAME_METADATA_KEY] = writer.name
    meta[PERSON_OWNER_METADATA_KEY] = writer.owner
    meta.setdefault(CHAT_CHANNEL_ID_METADATA_KEY, conversation.id)
