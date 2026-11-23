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

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CatalogChannel:
    """A channel that can be added + installed from the admin UI without prior CLI setup."""

    name: str          # channel id, e.g. "whatsapp"
    label: str         # human-friendly display name
    description: str   # one-line summary shown in the Add picker
    package: str       # pip distribution name for `uv tool install`
    command: str       # console entry point the plugin exposes (its config's command)
    # Environment variables its process starts with (the core sets them when it starts the plugin). For what a
    # plugin's libraries read from the environment before any of its Python code runs.
    env: dict[str, str] = field(default_factory=dict)


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
        # neonize 0.5.2 tags every one-to-one message sent to a phone number as a business bot (<bot biz_bot="1"/>)
        # unless this says off. WhatsApp's server accepts such a message from a personal account and delivers it to
        # no device. neonize's Go code reads the process's start environment only: a value the plugin sets once it
        # runs doesn't reach it.
        env={"NEONIZE_BOT_TAG": "off"},
    ),
)

_BY_NAME: dict[str, CatalogChannel] = {c.name: c for c in CHANNEL_CATALOG}


def catalog_channel(name: str) -> CatalogChannel | None:
    """The catalog entry for ``name``, or None if it isn't an installable channel."""
    return _BY_NAME.get(name)


def channel_env(name: str) -> dict[str, str]:
    """The environment variables the channel's process starts with ({} for a channel the catalog doesn't know)."""
    entry = _BY_NAME.get(name)
    return dict(entry.env) if entry is not None else {}


def available_channels(configured_names: set[str]) -> list[CatalogChannel]:
    """Catalog channels that aren't already configured in the workspace (addable)."""
    return [c for c in CHANNEL_CATALOG if c.name not in configured_names]
