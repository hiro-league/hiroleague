"""A link to a page, turned into an address when the core shows it (unified communication, phase 3).

A link is ``PageLink {app, path}`` (hiro_channel_sdk.offers): an app's name (``home``) or none for the core's admin,
and the page with its query. It holds no sign-in: a signed-out person who opens it goes through the one sign-in and
lands on that page. The address is the app's site, from its description's ``shows`` entry of kind site (the same site
the app switcher and the one sign-in use), plus the path; for the admin, the admin's address plus the path.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from hiro_channel_sdk import PageLink

from .sign_in_for_extensions import Site, list_sites

if TYPE_CHECKING:
    from .extension_manager import ExtensionManager


def address(link: PageLink, sites: Iterable[Site], admin_url: str) -> str | None:
    """The address a link opens (pure). For the admin: its address plus the path, or the path alone when shown inside
    the admin (``admin_url`` ""). None when the app has no site the core knows (not paired, or no name yet)."""
    if link.app is None:
        return f"{admin_url.rstrip('/')}{link.path}"
    site = next((s for s in sites if s.extension == link.app), None)
    return f"{site.url}{link.path}" if site is not None else None


def address_now(link: PageLink, manager: ExtensionManager | None, workspace_path: Path, admin_url: str) -> str | None:
    """The address a link opens, from every paired app's site as it is now (live when connected)."""
    return address(link, list_sites(manager, workspace_path) if link.app is not None else (), admin_url)
