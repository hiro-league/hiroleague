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
        id="eval",
        label="Eval",
        # Evaluation harness (LoCoMo/BEAM answer+judge runs) — output still noisy
        # and the workflow is immature; hidden until it stabilizes.
        active=False,
        note="Memory/knowledge evaluation harness.",
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
        # immature; hide the management surface until it is more complete. This
        # gates only the admin UI/CLI/API, not the agent's runtime retrieval.
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
        id="whatsapp",
        label="WhatsApp",
        # WhatsApp channel admin (QR pairing, connection status, config).
        active=True,
        note="WhatsApp channel admin: QR pairing, connection status, config.",
    ),
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
