"""Every ask an app makes, held to the SDK's table (Permissions phase 8, "What an app is approved for: the design").

An ask with no proof is the app's own: it is held to what the owner approved for the app. An ask that carries a
person's proof (``_signed_in``, given at sign-in) is that person's, on a method whose person right the table names:
it is answered only for an app approved for ``people.act``, and by that person's own rights. Where a test
environment's sign-in is off, its stand-in person (``quick_person``) answers for a page that sends no proof.

Refusals come per ask, never at connect, in words; a refusal of the app is said once per app, item and connect
(``forget``), so a worker's every round doesn't fill the problems list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hiro_channel_sdk.approvals import (
    ALWAYS,
    APP_METHODS,
    APPS_ASK,
    NEVER,
    NOT_ALLOWED,
    NOT_APPROVED,
    NOT_ON_ITS_OWN,
    OWNER_ONLY,
    PARAM_SIGNED_IN,
    PEOPLE_ACT,
    SIGN_IN_AGAIN,
    SITE_NAME,
    WORDS,
)
from hiro_commons.log import Logger

from ..domain import approvals, person_tokens
from ..domain.extensions import get_paired_extension

log = Logger.get("APPROVALS")


class AppRefused(Exception):
    """An app's ask refused by its approvals or by the person's rights: a code, words for a person, and data."""

    def __init__(self, code: str, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.data = data or {}


@dataclass(frozen=True)
class AppAsker:
    """Who an app's ask is answered for: the app on its own (``person_id`` ""), or a person through it."""

    extension_id: str
    person_id: str = ""


@dataclass
class _Said:
    """The refusals already said per app since it connected."""

    keys: dict[str, set[tuple[str, str]]] = field(default_factory=dict)


_SAID = _Said()


def forget(extension_id: str) -> None:
    """The app connected again: its refusals are said again, once each."""
    _SAID.keys.pop(extension_id, None)


def _label(info: dict[str, Any], name: str) -> str:
    offers = info.get("offers") if isinstance(info, dict) else None
    for item in (offers or {}).get("shows") or []:
        if isinstance(item, dict) and item.get("kind") == "site" and item.get("title"):
            return str(item["title"])
    return name or "This app"


def subject_of(permission: str, params: dict[str, Any]) -> str:
    """The subject an ask names for a permission that has one: the app asked, the LAN name and port claimed."""
    if permission == APPS_ASK:
        return str(params.get("to") or "").strip()
    if permission == SITE_NAME:
        return f"{str(params.get('name') or '').strip().lower()}:{params.get('port')}"
    return ""


def check(workspace_path: Path, extension_id: str, method: str, params: dict[str, Any]) -> AppAsker:
    """Who the ask is answered for, or :class:`AppRefused`. Takes the person's proof out of ``params``."""
    from hiro_channel_sdk.access import allowed

    from ..domain.access import admin_access
    from ..domain.admin_sign_in import quick_person
    from ..domain.core_features import CORE_BY_ID
    from ..domain.people import get_person
    from ..domain.talkers import is_owner

    token = str(params.pop(PARAM_SIGNED_IN, "") or "")
    need = APP_METHODS.get(method)
    if need is None:
        raise AppRefused("method_not_found", f"Unknown method: {method}")
    record = get_paired_extension(workspace_path, extension_id)
    approval = approvals.read(workspace_path, extension_id)
    if record is None or approval is None:
        raise AppRefused(NOT_APPROVED, "HiroLeague doesn't know this app any more.")
    label = _label(record.info, record.name)
    approved = approval.approved

    if need.app == NEVER:
        raise AppRefused(NOT_ALLOWED, "No app may do this: it is done in HiroLeague's admin.", {"right": method})

    if need.person is not None:
        person_id = person_tokens.person_of(workspace_path, token, extension_id) if token else None
        if token and person_id is None:
            raise AppRefused(SIGN_IN_AGAIN, "Sign in again to do this.")
        person = get_person(workspace_path, person_id) if person_id else (None if token else quick_person(workspace_path))
        if person is None:
            if approved is None:  # an app from before approvals, with no proof: as before
                return AppAsker(extension_id)
            raise AppRefused(SIGN_IN_AGAIN, "Sign in again to do this.")
        if not approvals.covers(approved, PEOPLE_ACT):
            raise _not_approved(label, PEOPLE_ACT, "", approval, record.info)
        if need.person == OWNER_ONLY:
            if not is_owner(person):
                raise AppRefused(NOT_ALLOWED, f"{person.name} may not do this: only the owner can.",
                                 {"right": "owner"})
        else:
            feature, action = need.person
            roles = admin_access(workspace_path, person.role_ids).roles
            if not allowed(roles, feature, action, CORE_BY_ID, asker=person.person_id, owners=[person.person_id]):
                raise AppRefused(NOT_ALLOWED, f"{person.name} may not do this: their roles don't include it.",
                                 {"right": f"{feature}.{action}"})
        return AppAsker(extension_id, person.person_id)

    if need.app == ALWAYS:
        return AppAsker(extension_id)
    if need.app == NOT_ON_ITS_OWN:
        if approved is None:  # an app from before approvals: as before, until it declares what it asks
            return AppAsker(extension_id)
        raise AppRefused(NOT_ALLOWED, f"{label} can't do this on its own: it notifies people through HiroLeague.",
                         {"right": method})
    subject = subject_of(need.app, params)
    if approvals.covers(approved, need.app, subject):
        return AppAsker(extension_id)
    if need.app == SITE_NAME and subject != approval.asked_claim:
        approvals.set_asked_claim(workspace_path, extension_id, subject)
        approval = approvals.Approval(approved=approved, asked_claim=subject, declined=approval.declined)
    raise _not_approved(label, need.app, subject, approval, record.info)


def _not_approved(label: str, permission: str, subject: str, approval: approvals.Approval,
                  info: dict[str, Any]) -> AppRefused:
    claims = [approval.asked_claim] if approval.asked_claim else []
    asked = approvals.asked(info, claims) or []
    waits = any(a.permission == permission and a.subject == subject for a in approvals.waiting(asked, approval.approved, approval.declined))
    words = WORDS.get(permission, permission)
    if waits:
        # "yet" before the words: they may hold a list of their own ("the people list: names, numbers, roles")
        message = f"{label} isn't approved yet to {words}. It waits for the owner's yes on HiroLeague's Extensions page."
    else:
        message = f"{label} isn't approved to {words}. The owner approves it on HiroLeague's Extensions page."
    return AppRefused(NOT_APPROVED, message, {"permission": permission, "subject": subject, "waiting": waits})


def said_once(extension_id: str, refused: AppRefused) -> bool:
    """True the first time this refusal is met since the app connected: it is logged as a warning then."""
    key = (str(refused.data.get("permission") or refused.data.get("right") or refused.code),
           str(refused.data.get("subject") or ""))
    seen = _SAID.keys.setdefault(extension_id, set())
    if key in seen:
        return False
    seen.add(key)
    return True
