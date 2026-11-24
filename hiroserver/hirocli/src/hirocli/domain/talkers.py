"""Who talks to Hiro (Permissions phase 3): the owner, whether a person may talk, and the addresses a chat channel lets
through.

Talking to Hiro is the core's right ``assistant.talk``, checked by the SDK's one check over every role a person holds.
Hiro remembers everyone who may talk to it: being remembered is no right of its own.
"""

from __future__ import annotations

from pathlib import Path

from hiro_channel_sdk.access import allowed

from .access import admin_access
from .core_features import CORE_BY_ID
from .data_store import chat_user_id
from .pairing import device_person_id
from .people import OWNER_ROLE, Person, get_person, list_people

TALK_FEATURE = "assistant"
TALK = "talk"


def is_owner(person: Person) -> bool:
    return OWNER_ROLE in person.role_ids


def owner_person(people: list[Person]) -> Person | None:
    """The owner: the first person who holds Owner. The conversations and devices from before phase 3 are theirs."""
    owners = sorted((p for p in people if is_owner(p)), key=lambda p: (p.created_at, p.person_id))
    return owners[0] if owners else None


def may_talk(workspace_path: Path, person: Person) -> bool:
    """Whether a person may talk to Hiro: any of their roles holds ``assistant.talk`` (the owner always does)."""
    roles = admin_access(workspace_path, person.role_ids).roles
    return allowed(roles, TALK_FEATURE, TALK, CORE_BY_ID)


def talking_numbers(workspace_path: Path) -> list[str]:
    """The WhatsApp numbers that may reach Hiro: those of the people who may talk. A chat channel that strangers can
    write to is handed this list and drops every other sender; the core checks each message again."""
    return sorted({p.whatsapp for p in list_people(workspace_path) if p.whatsapp and may_talk(workspace_path, p)})


def chat_user_for(workspace_path: Path, person: Person | None, people: list[Person]) -> int | None:
    """The chat user a person's conversations and memory are keyed by. The first owner takes the seeded one (every
    conversation from before phase 3); with no family list yet, the seeded one is everyone's. None: nobody we know."""
    if person is None:
        return None if people else chat_user_id(workspace_path, "", owner=True)
    owner = owner_person(people)
    return chat_user_id(workspace_path, person.person_id, owner=owner is not None and person.person_id == owner.person_id)


def device_owner(workspace_path: Path, device_id: str) -> tuple[Person | None, int | None]:
    """The person a paired device belongs to, and their chat user: a device shows, writes and fetches only that
    person's conversations. (None, None) for a device that is nobody's we know."""
    people = list_people(workspace_path)
    pid = device_person_id(workspace_path, device_id)
    person = get_person(workspace_path, pid) if pid else None
    if person is None and people:
        return None, None
    return person, chat_user_for(workspace_path, person, people)
