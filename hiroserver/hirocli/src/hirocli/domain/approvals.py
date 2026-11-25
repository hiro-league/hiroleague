"""What each paired app is approved for (Permissions phase 8, "What an app is approved for: the design").

The owner approves an app at pairing: its address, its LAN name and port, and each thing it asks to do on its own
(its declaration's ``asks``, the SDK's ``approvals.py``). The approved items live on the app's record
(``extension_records.approved``, a JSON list of ``{permission, subject}``); what waits is never kept: it is what the
last declaration asks less what is approved, worked out when read.

``approved`` NULL is an app paired before approvals existed: approved for everything, until its first declaration
with ``asks``, which approves exactly what it asks (nobody gains or loses at the deploy). A declaration with no
``asks`` (a kit from before) changes nothing, so a rollback drops nothing. A newly paired app starts with ``[]``.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from hiro_channel_sdk.approvals import (
    APPS_ASK,
    ASKABLE,
    SITE_ADDRESS,
    SITE_NAME,
    WORDS,
    AppAsk,
    ApprovedItem,
)

from .db import db_path, ensure_db

log = logging.getLogger(__name__)

TABLE = "extension_records"
# What is approved with the app itself: a new subject replaces the approved one only when the owner says yes
IDENTITY = frozenset({SITE_ADDRESS, SITE_NAME})


@dataclass(frozen=True)
class Asked:
    """One thing an app's declaration asks: a permission, its subject, whether it is required, and why."""

    permission: str
    subject: str = ""
    required: bool = True
    why: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.permission, self.subject)

    @property
    def understood(self) -> bool:
        return self.permission in ASKABLE or self.permission in IDENTITY

    @property
    def words(self) -> str:
        return WORDS.get(self.permission, f"{self.permission} (not understood by this core)")


@dataclass(frozen=True)
class Approval:
    """An app's approval as kept: the approved items (None: approved for everything) and the LAN name it asked for
    last and wasn't approved for ("" when none)."""

    approved: list[ApprovedItem] | None
    asked_claim: str = ""
    # The optional items the owner left off: answered, so they wait no more (until switched on)
    declined: frozenset[tuple[str, str]] = frozenset()


# ---------------------------------------------------------------------------
# Pure rules
# ---------------------------------------------------------------------------


def site_address(info: dict[str, Any]) -> str:
    """The address its card declares (offers.shows, kind "site"), "" when none."""
    offers = info.get("offers") if isinstance(info, dict) else None
    for item in (offers or {}).get("shows") or []:
        if isinstance(item, dict) and item.get("kind") == "site" and item.get("url"):
            return str(item["url"]).strip()
    return ""


def asked(info: dict[str, Any], claims: list[str]) -> list[Asked] | None:
    """What the declaration asks, with its address and its LAN names ("name:port", the claim it holds and the one it
    last asked for); None for a declaration with no ``asks`` (a kit from before)."""
    raw = info.get("asks") if isinstance(info, dict) else None
    if raw is None:
        return None
    items: list[Asked] = []
    for entry in raw:
        try:
            ask = AppAsk.model_validate(entry)
        except ValidationError as exc:  # one bad entry never refuses the connect: it is left out, and said once
            log.warning("Approvals: an ask the core can't read was left out", extra={"error": str(exc)})
            continue
        subject = (ask.to or "").strip() if ask.permission == APPS_ASK else ""
        items.append(Asked(ask.permission, subject, ask.required, ask.why))
    address = site_address(info)
    if address:
        items.append(Asked(SITE_ADDRESS, address, True, "Where HiroLeague sends people once they are signed in"))
    for claim in dict.fromkeys(c for c in claims if c):
        items.append(Asked(SITE_NAME, claim, True, "Its name on the home network"))
    return items


def covers(approved: list[ApprovedItem] | None, permission: str, subject: str = "") -> bool:
    """Whether the approved items let the app do this (None: approved for everything)."""
    if approved is None:
        return True
    return any(i.permission == permission and i.subject == subject for i in approved)


def waiting(items: list[Asked] | None, approved: list[ApprovedItem] | None,
            declined: frozenset[tuple[str, str]] = frozenset()) -> list[Asked]:
    """What the declaration asks that the owner hasn't answered: never for an app approved for everything. An
    optional item the owner left off was answered; a required one can't be left off (declining it removes the app)."""
    if items is None or approved is None:
        return []
    have = {(i.permission, i.subject) for i in approved}
    return [a for a in items if a.understood and a.key not in have and (a.required or a.key not in declined)]


def settled(items: list[Asked] | None, approved: list[ApprovedItem] | None) -> list[ApprovedItem] | None:
    """The approved items once a new declaration is kept: the first one with ``asks`` approves exactly what it asks;
    after that, what it no longer asks leaves at once, but an approved address or LAN name stays in use until the
    owner approves the new one. A declaration with no ``asks`` changes nothing."""
    if items is None:
        return approved
    if approved is None:
        return [ApprovedItem(permission=a.permission, subject=a.subject) for a in items if a.understood]
    keys = {a.key for a in items}
    return [i for i in approved if (i.permission, i.subject) in keys or i.permission in IDENTITY]


def approve(items: list[Asked], approved: list[ApprovedItem] | None, chosen: set[tuple[str, str]]) -> list[ApprovedItem]:
    """The owner's yes: every required item asked, the optional ones in ``chosen``. A new address or LAN name
    replaces the approved one."""
    # An optional item left off is not approved, even if it was before: the switches say what is approved now
    new = [a for a in items if a.understood and (a.required or a.key in chosen)]
    out = [ApprovedItem(permission=a.permission, subject=a.subject) for a in new]
    new_identity = {a.permission for a in new if a.permission in IDENTITY}
    # An address or LAN name the declaration no longer names stays in use until a new one of its kind is approved
    out += [i for i in (approved or []) if i.permission in IDENTITY and i.permission not in new_identity]
    return out


def required_waiting(items: list[Asked] | None, approved: list[ApprovedItem] | None) -> bool:
    """Whether a required item waits: declining it declines the app."""
    return any(a.required for a in waiting(items, approved))


def left_off(items: list[Asked], chosen: set[tuple[str, str]]) -> frozenset[tuple[str, str]]:
    """The optional items the owner's answer leaves off."""
    return frozenset(a.key for a in items if a.understood and not a.required and a.key not in chosen)


# ---------------------------------------------------------------------------
# Kept on the app's record
# ---------------------------------------------------------------------------


def _items(raw: str | None) -> list[ApprovedItem] | None:
    if raw is None:
        return None
    try:
        return [ApprovedItem.model_validate(i) for i in json.loads(raw or "[]")]
    except (json.JSONDecodeError, ValidationError) as exc:
        # A record the core can't read approves nothing new: it is said, and the owner approves again
        log.warning("Approvals: an app's approved items can't be read; it is approved for nothing",
                    extra={"error": str(exc)})
        return []


def read(workspace_path: Path, extension_id: str) -> Approval | None:
    """The app's approval, or None when it has no record."""
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        row = conn.execute(
            f"SELECT approved, asked_claim, declined FROM {TABLE} WHERE extension_id = ?", (extension_id,)
        ).fetchone()
    if row is None:
        return None
    declined = frozenset((i.permission, i.subject) for i in _items(row[2]) or [])
    return Approval(approved=_items(row[0]), asked_claim=row[1] or "", declined=declined)


def write(workspace_path: Path, extension_id: str, approved: list[ApprovedItem] | None) -> None:
    ensure_db(workspace_path)
    value = None if approved is None else json.dumps([i.model_dump() for i in approved])
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.execute(f"UPDATE {TABLE} SET approved = ? WHERE extension_id = ?", (value, extension_id))
        conn.commit()


def set_declined(workspace_path: Path, extension_id: str, declined: frozenset[tuple[str, str]]) -> None:
    ensure_db(workspace_path)
    value = json.dumps([{"permission": p, "subject": s} for p, s in sorted(declined)])
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.execute(f"UPDATE {TABLE} SET declined = ? WHERE extension_id = ?", (value, extension_id))
        conn.commit()


def set_asked_claim(workspace_path: Path, extension_id: str, claim: str) -> None:
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.execute(f"UPDATE {TABLE} SET asked_claim = ? WHERE extension_id = ?", (claim, extension_id))
        conn.commit()


# ---------------------------------------------------------------------------
# Kept as a declaration is kept
# ---------------------------------------------------------------------------


def claims_of(workspace_path: Path, extension_id: str) -> list[str]:
    """The LAN names the app holds, as "name:port"."""
    from .site_names import list_claims

    return [f"{c.name}:{c.port}" for c in list_claims(workspace_path) if c.extension_id == extension_id]


def asked_now(workspace_path: Path, extension_id: str, info: dict[str, Any], approval: Approval) -> list[Asked] | None:
    """What the app asks now: its declaration, its address, the LAN name it holds and the one it last asked for."""
    claims = claims_of(workspace_path, extension_id) + ([approval.asked_claim] if approval.asked_claim else [])
    return asked(info, claims)


def keep(workspace_path: Path, extension_id: str, info: dict[str, Any], *, new: bool = False) -> None:
    """A declaration was kept (a connect, pairing again, the Uses page's refresh): its approval follows it. A newly
    paired app is approved for nothing until the owner answers."""
    if new:
        write(workspace_path, extension_id, [])
        return
    approval = read(workspace_path, extension_id)
    if approval is None:
        return
    after = settled(asked_now(workspace_path, extension_id, info, approval), approval.approved)
    if after != approval.approved:
        write(workspace_path, extension_id, after)
        if approval.approved is None:
            log.info("Approvals: an app from before approvals is approved for what it first declared",
                     extra={"extension_id": extension_id, "items": len(after or [])})


def on_the_wire(workspace_path: Path, extension_id: str, info: dict[str, Any]) -> dict[str, Any]:
    """What the app is approved for and what waits, as the welcome and approval.changed carry it."""
    from hiro_channel_sdk.approvals import Approval as WireApproval

    approval = read(workspace_path, extension_id) or Approval(approved=None)
    items = asked_now(workspace_path, extension_id, info, approval)
    wire = WireApproval(
        approved=approval.approved,
        waiting=[ApprovedItem(permission=a.permission, subject=a.subject)
                 for a in waiting(items, approval.approved, approval.declined)],
    )
    return wire.model_dump(mode="json")


# ---------------------------------------------------------------------------
# The owner's view and answer (the Extensions page, `hiro extension approve`)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ItemView:
    """One item on the owner's sheet: what it is, in words, and where it stands."""

    permission: str
    subject: str
    words: str
    required: bool
    why: str
    approved: bool
    waiting: bool
    understood: bool


@dataclass(frozen=True)
class AppApproval:
    """An app's approval as the owner sees it. ``pending``: never answered (nothing approved, something asked)."""

    extension_id: str
    name: str
    approved_for_everything: bool
    pending: bool
    items: list[ItemView]

    @property
    def waits(self) -> bool:
        return any(i.waiting for i in self.items)


def view(workspace_path: Path, extension_id: str) -> AppApproval | None:
    """What the app asks, what is approved and what waits; None when the app isn't paired."""
    from .extensions import get_paired_extension

    record = get_paired_extension(workspace_path, extension_id)
    approval = read(workspace_path, extension_id)
    if record is None or approval is None:
        return None
    items = asked_now(workspace_path, extension_id, record.info, approval) or []
    waits = {a.key for a in waiting(items, approval.approved, approval.declined)}
    out = [
        ItemView(a.permission, a.subject, a.words, a.required, a.why,
                 covers(approval.approved, a.permission, a.subject), a.key in waits, a.understood)
        for a in items
    ]
    return AppApproval(
        extension_id=extension_id,
        name=record.name,
        approved_for_everything=approval.approved is None,
        pending=approval.approved == [] and bool(waits),
        items=out,
    )


def approve_app(
    workspace_path: Path, extension_id: str, chosen: set[tuple[str, str]] | None = None
) -> tuple[list[ApprovedItem], list[str]]:
    """The owner's yes: every required item, the optional ones in ``chosen`` (None: every optional one too). Returns
    the approved items and the LAN names ("name:port") newly approved, which the core then claims for the app."""
    from .extensions import get_paired_extension

    record = get_paired_extension(workspace_path, extension_id)
    approval = read(workspace_path, extension_id)
    if record is None or approval is None:
        raise LookupError("That app isn't paired any more.")
    items = asked_now(workspace_path, extension_id, record.info, approval) or []
    picked = {a.key for a in items if not a.required} if chosen is None else chosen
    before = {(i.permission, i.subject) for i in (approval.approved or [])}
    after = approve(items, approval.approved, picked)
    write(workspace_path, extension_id, after)
    set_declined(workspace_path, extension_id, left_off(items, picked))
    claims = [i.subject for i in after if i.permission == SITE_NAME and (i.permission, i.subject) not in before]
    if claims and approval.asked_claim in claims:
        set_asked_claim(workspace_path, extension_id, "")
    return after, claims
