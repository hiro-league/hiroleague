"""Catalog of installable channel plugins.

The channel list the admin UI shows is config-driven (``list_channel_configs``) — a
channel only appears once it has been *set up*. That leaves no way to add a brand-new
channel from the UI: with nothing configured there is no row to open, hence no Install
button. This catalog fills that gap: a small static registry of first-party channels
the UI can offer under "Add a channel", each carrying the `uv tool install` package and
the console command its config should run. Extend it as more plugins ship.

It is intentionally NOT the descriptor registry (config schema / capabilities): those
are shipped by a plugin over the wire *after* it installs and registers. This catalog
is only what's needed to bootstrap the config so the plugin can be installed + enabled.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogChannel:
    """A channel that can be added + installed from the admin UI without prior CLI setup."""

    name: str          # channel id, e.g. "whatsapp"
    label: str         # human-friendly display name
    description: str   # one-line summary shown in the Add picker
    package: str       # pip distribution name for `uv tool install`
    command: str       # console entry point the plugin exposes (its config's command)


# Known installable first-party channels. Keep in sync with the shipped plugin packages.
CHANNEL_CATALOG: tuple[CatalogChannel, ...] = (
    CatalogChannel(
        name="whatsapp",
        label="WhatsApp",
        description=(
            "Send and receive WhatsApp text and voice notes via an unofficial WhatsApp "
            "Web link (neonize / whatsmeow)."
        ),
        package="hiro-channel-whatsapp",
        command="hiro-channel-whatsapp",
    ),
)

_BY_NAME: dict[str, CatalogChannel] = {c.name: c for c in CHANNEL_CATALOG}


def catalog_channel(name: str) -> CatalogChannel | None:
    """The catalog entry for ``name``, or None if it isn't an installable channel."""
    return _BY_NAME.get(name)


def available_channels(configured_names: set[str]) -> list[CatalogChannel]:
    """Catalog channels that aren't already configured in the workspace (addable)."""
    return [c for c in CHANNEL_CATALOG if c.name not in configured_names]
