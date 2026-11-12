"""The app's LAN name (Settings → HiroLeague → the app's address): the rules for the name typed there. Pure: no
database, HA or core (the app's title, for the messages, is the only thing it reads).

Since the site-names change (hiroleague docs/site-names-design.md) the address is a NAME the HiroLeague core sets up on
the LAN (it publishes the name and points its web proxy at the app), not a URL typed by hand. A person types a label
and picks one of two kinds:

- `subdomain`: `home` → `home.hiro.local` (SITES_DOMAIN, the core's own name);
- `local`: a one-word `.local` name, `abc` → `abc.local`.

A label is letters, digits and dashes (not at either end), up to 63 of them: the core checks the same rule
(`sites.claim` answers `invalid`); checking it here first answers at once and in the app's words.
"""

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from hiro_channel_sdk.constants import SITES_DOMAIN

from . import identity

Kind = Literal["subdomain", "local"]
KINDS: tuple[Kind, ...] = ("subdomain", "local")
_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class BadLabel(ValueError):
    """The label can't be a name; the message is for people."""


@dataclass(frozen=True)
class SiteName:
    label: str
    kind: Kind

    @property
    def name(self) -> str:
        """The full name: `<label>.hiro.local` or `<label>.local`."""
        return f"{self.label}.{SITES_DOMAIN}" if self.kind == "subdomain" else f"{self.label}.local"

    @property
    def url(self) -> str:
        """The site the app declares for the name (the core proxies plain http on the LAN)."""
        return f"http://{self.name}"


def site_name(label: str, kind: str) -> SiteName:
    """The name for a label as typed: trimmed, lower case, and the kind's own suffix dropped when typed too (people
    paste the whole name). Raises BadLabel with the rule in words."""
    if kind not in KINDS:
        raise BadLabel("Pick a subdomain of hiro.local or a one-word .local name.")
    clean = label.strip().lower()
    suffix = f".{SITES_DOMAIN}" if kind == "subdomain" else ".local"
    if clean.endswith(suffix):
        clean = clean[: -len(suffix)]
    if not clean:
        raise BadLabel(f"Type a name for {identity.app().title} (e.g. home).")
    if not _LABEL.match(clean):
        raise BadLabel(f"“{label.strip()}” can't be a name: use letters, digits and dashes (not at the start or end), "
                       "one word.")
    return SiteName(label=clean, kind=kind)  # type: ignore[arg-type]  # kind checked against KINDS above


def name_of(url: str) -> SiteName | None:
    """The label and kind of a site address, for the form: `http://home.hiro.local` → (home, subdomain),
    `http://nethiro.local` → (nethiro, local); None for an address that isn't one of the two shapes (a port, an IP,
    https, a deeper name)."""
    parts = urlsplit(url)
    host = parts.netloc.lower()
    if parts.scheme != "http" or not host or ":" in host or parts.path not in ("", "/"):
        return None
    if host.endswith(f".{SITES_DOMAIN}"):
        label, kind = host[: -len(SITES_DOMAIN) - 1], "subdomain"
    elif host.endswith(".local"):
        label, kind = host[: -len(".local")], "local"
    else:
        return None
    return SiteName(label=label, kind=kind) if _LABEL.match(label) else None  # type: ignore[arg-type]
