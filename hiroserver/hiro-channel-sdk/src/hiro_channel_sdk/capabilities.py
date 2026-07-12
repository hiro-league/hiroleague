"""Channel capability descriptors (design §5.2).

A channel declares, at registration, HOW its non-config admin surface behaves —
its pairing style, which admin actions it supports, whether it reports a live
status, and its lifecycle states. The server and admin UI drive onboarding from
this descriptor generically, instead of shipping per-channel routes and UI.

The descriptor travels as plain JSON on ``channel.register`` (see
``ChannelInfo.capabilities``); build it with ``ChannelCapabilities(...)`` and
``.model_dump()`` so every channel declares it the same way.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Pairing styles the admin UI knows how to render. A channel with no linking step
# (e.g. an inbound webhook) declares PAIRING_NONE.
PAIRING_NONE = "none"
PAIRING_QR = "qr"
PAIRING_TOKEN = "token"
PAIRING_OAUTH = "oauth"

PairingKind = Literal["none", "qr", "token", "oauth"]

# Standard admin action names. An action "<a>" is invoked generically by the
# server sending the plugin a ``channel.<a>`` event (see ChannelPlugin.on_event).
ACTION_LOGOUT = "logout"
ACTION_RECONNECT = "reconnect"


class ChannelCapabilities(BaseModel):
    """Declarative description of a channel's admin / onboarding surface.

    - ``pairing``       — how the account is linked (QR, token, OAuth, or none).
    - ``actions``       — admin action names the channel handles via ``on_event``.
    - ``live_status``   — whether the channel emits ``channel.status`` updates the
                          UI should poll and render.
    - ``state_machine`` — ordered lifecycle states, most-preliminary first, for the
                          UI to show where onboarding currently stands.
    """

    pairing: PairingKind = PAIRING_NONE
    actions: list[str] = Field(default_factory=list)
    live_status: bool = False
    state_machine: list[str] = Field(default_factory=list)
