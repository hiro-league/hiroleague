"""Feature ledger — the single source of truth for which features are exposed.

This is the one place that decides whether a feature is wired into the running
admin UI, its HTTP API, and the CLI. Flip ``active`` and commit; the change shows
up in ``git diff`` and is reviewed in the PR.

    active = True   -> feature is wired in and usable.
    active = False  -> hidden everywhere (nav, routes, API, CLI) and NOT usable.
                       The code stays in the repo; a contributor flips this to
                       True on their branch to work on it, and only merges the
                       flip once the feature is ready for everyone.

The frontend reads a generated copy of this ledger. After editing, regenerate it:

    (from admin_frontend/)  npm run gen:features
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureSpec:
    """One gate-able feature. ``id`` is the stable key used by nav items, route
    guards, API mounts, and CLI registration to look the feature up."""

    id: str
    label: str
    active: bool
    note: str = ""


# ---------------------------------------------------------------------------
# The ledger. One entry per gate-able feature (alphabetical by id). A feature
# listed here with active=False is hidden; a feature not listed here is treated
# as always-active (see feature_active).
# ---------------------------------------------------------------------------
_FEATURES: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        id="devices",
        label="Devices",
        # Device pairing + the mandatory "devices" channel: phones and the device web
        # app chat with Hiro through the gateway (Hiro Gate relay). Unlike the other
        # flags this one also gates RUNTIME behavior: when on, the core runs its own
        # gateway beside it (runtime/builtin_gateway.py, unless the workspace names a
        # gateway run elsewhere) and spawns the devices channel, which connects to it;
        # when off, neither runs. Admin chat + WhatsApp never depend on it.
        active=True,
        note="Device pairing + the mandatory gateway-backed devices channel.",
    ),
    FeatureSpec(
        id="gateway",
        label="Gateway",
        # Managing gateways run apart from the core (hirogate instances: an
        # off-LAN relay on another machine) — the Server-page "Gateways" tab +
        # dashboard gateway cards. Purely a surface gate. Device chat doesn't need
        # it: with `devices` on, the core runs its own gateway beside it.
        active=False,
        note="Managing hirogate instances run apart from the core.",
    ),
    FeatureSpec(
        id="image_lab",
        label="Image Lab",
        # Text-to-image playground — stage 1 only (no agent attach flow yet),
        # hidden from users until it is more complete.
        active=False,
        note="Text-to-image playground over the generate_image tool.",
    ),
    FeatureSpec(
        id="knowledge",
        label="Knowledge",
        # Knowledge base admin (ingest/browse/search) — retrieval quality still
        # immature; hide it until it is more complete. Gates the admin UI/CLI/API
        # AND the agent's runtime retrieval: when inactive, agent_manager
        # ._build_knowledge_subgraph returns None so the chat graph omits the
        # knowledge branch entirely (no per-turn rewrite call). A RUNTIME gate.
        active=False,
        note="Workspace knowledge base ingest/browse/search admin.",
    ),
    FeatureSpec(
        id="metrics",
        label="Metrics",
        # Server resource metrics (CPU/memory/disk/network) — the Metrics subtab on
        # the Server page + `hiro metrics` CLI. Hidden until it is more complete.
        active=False,
        note="Server resource metrics (CPU/memory/disk/network).",
    ),
    FeatureSpec(
        id="ui_kit",
        label="UI kit",
        # The shared UI kit's gallery + Theme designer, shown inside the admin. A pure
        # frontend page (no API behind it); active so the owner/admin can design a theme.
        active=True,
        note="The shared UI kit's components and theme, as deployed",
    ),
    # WhatsApp is no feature of its own: every channel plugin is a row of the admin's
    # Extensions page, its Settings drawn from its declared schema + capabilities (§5.5).
    # No per-channel flag.
)

FEATURES: dict[str, FeatureSpec] = {f.id: f for f in _FEATURES}


def feature_active(feature_id: str) -> bool:
    """True when the feature is exposed and usable.

    Unknown ids default to ``True`` (fail-open): only features explicitly listed
    in the ledger can be hidden, so a typo in a gate call never silently hides a
    live feature. The frontend ``isFeatureActive`` mirrors this rule.
    """
    spec = FEATURES.get(feature_id)
    return spec.active if spec is not None else True


def feature_registry() -> dict[str, dict[str, object]]:
    """Serializable ledger for codegen (frontend ``feature-registry.json``)."""
    return {
        f.id: {"label": f.label, "active": f.active, "note": f.note} for f in _FEATURES
    }
