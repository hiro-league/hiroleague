"""What a person approves when they install an app (Installing apps, phase 5; Permissions phase 8). Pure.

The admin step (sudo, or Windows' prompt) only says the machine changes: it says nothing about what the app may do.
So before it, the install shows what the app asks, from the package's manifest, in the Extensions page's words
(domain/approvals.py): each thing it asks to do on its own, the address it sends people to and its name on the home
network. The person's yes is the approval, kept on the install's row (``consent``). Nothing is approved by itself:
without a yes (or ``--approve``, consent given in advance) nothing is made.

When the app pairs with its install's code, it is approved for what the person approved and it still asks. What it
asks beyond the manifest waits on the Extensions page, as for a new version that asks more.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from hiro_channel_sdk.approvals import APPS_ASK, SITE_ADDRESS, SITE_NAME, ApprovedItem
from hiro_channel_sdk.manifest import Manifest, dashed

from .approvals import IDENTITY, Asked, approve, asked


def site_of(manifest: Manifest, domain: str) -> tuple[str, str]:
    """The app's address and its name on the home network, as the kit declares and claims them: its manifest's
    ``site`` (HomeHiro's http://homehiro.local), else http://<key, dashed>.<the core's domain>."""
    address = manifest.site or f"http://{dashed(manifest.key)}.{domain}"
    return address, (urlsplit(address).hostname or "").lower()


def sheet(manifest: Manifest, domain: str, port: int) -> list[Asked]:
    """What the person is asked to approve: the manifest's asks, its address and its name for ``port`` (the port the
    install gives it), each with the words and the why the Extensions page shows."""
    address, name = site_of(manifest, domain)
    items: list[Asked] = []
    for ask in manifest.asks:
        subject = (ask.to or "").strip() if ask.permission == APPS_ASK else ""
        items.append(Asked(ask.permission, subject, ask.required, ask.why))
    items.append(Asked(SITE_ADDRESS, address, True, "Where HiroLeague sends people once they are signed in"))
    if name:
        items.append(Asked(SITE_NAME, f"{name}:{port}", True, "Its name on the home network"))
    return items


def consent(items: list[Asked], chosen: set[tuple[str, str]] | None) -> list[ApprovedItem]:
    """The person's yes: every required item this core understands, and the optional ones in ``chosen`` (None: every
    optional one too). An item this core doesn't understand is never approved."""
    picked = {a.key for a in items if not a.required} if chosen is None else chosen
    return approve(items, None, picked)


def at_pairing(agreed: tuple[ApprovedItem, ...] | list[ApprovedItem], info: dict[str, Any]) -> list[ApprovedItem]:
    """What the app is approved for when it pairs with its install's code: what the person approved that its
    declaration still asks, and its address and name as approved (it claims its name only after pairing, so its
    declaration doesn't name it yet; the claim must match it exactly to be served)."""
    asks = asked(info, []) or []
    wanted = {a.key for a in asks}
    return [i for i in agreed if i.permission in IDENTITY or (i.permission, i.subject) in wanted]
