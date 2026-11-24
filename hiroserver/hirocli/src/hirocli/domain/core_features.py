"""The core's own features (Permissions phase 2): what a role may do in HiroLeague itself, declared the way an app
declares its own, under the source ``hiroleague``.

A permission is ``feature.action``, or ``area.feature.action`` when an area groups several features: a feature's id
carries its area (``ai.providers``), so keys, grants and the SDK's one check are an app's. People and roles are none of
these: they are the owner's.

Every admin page and tab names the feature that opens it (the admin's ``lib/shell/nav.ts``); only a grant that reaches
everyone's opens one. A grant for their own things (``conversations.see:own``) is used from a chat channel or a device.

Pure: no database, no import of the rest of the domain (db.py reads it for the one-time copy).
"""

from __future__ import annotations

from hiro_channel_sdk.access import OWN, SEE, ExtensionFeature, ExtensionRight, declared_keys

CORE_SOURCE = "hiroleague"

# The areas that group several features: the name the Roles page shows over them.
CORE_AREAS: dict[str, str] = {"assistant": "Hiro", "ai": "AI", "logs": "Logs"}


def _right(rid: str, name: str, says: str, personal: bool = False) -> ExtensionRight:
    return ExtensionRight(id=rid, name=name, says=says, personal=personal)


def _see(says: str, personal: bool = False) -> ExtensionRight:
    return _right(SEE, "See", says, personal)


def _change(says: str, personal: bool = False) -> ExtensionRight:
    return _right("change", "Change", says, personal)


CORE_FEATURES: list[ExtensionFeature] = [
    ExtensionFeature(id="assistant", name="Talking to Hiro",
                     rights=[_right("talk", "Talk", "On a chat channel, a device or the admin's chat")]),
    ExtensionFeature(id="assistant.characters", name="Characters",
                     rights=[_see("Hiro's characters"), _change("Add and change characters")]),
    ExtensionFeature(id="conversations", name="Conversations",
                     rights=[_see("Conversations and their messages", True), _change("Rename, clear and delete", True)]),
    ExtensionFeature(id="memories", name="Memories",
                     rights=[_see("What Hiro remembers", True), _change("Correct and forget", True)]),
    ExtensionFeature(id="knowledge", name="Knowledge",
                     rights=[_see("The knowledge base"), _change("Add, change and remove documents")]),
    ExtensionFeature(id="ai.providers", name="Providers and models",
                     rights=[_see("Providers, models and what is on"), _change("Keys and models")]),
    ExtensionFeature(id="ai.profiles", name="Profiles",
                     rights=[_see("Which model and voice does each job"), _change("Change the profiles and their uses")]),
    ExtensionFeature(id="ai.images", name="Pictures",
                     rights=[_right("run", "Make pictures", "Image Lab, which is paid")]),
    ExtensionFeature(id="extensions", name="Extensions",
                     rights=[_see("Apps and chat channels"), _change("Pair, start, stop and set them up")]),
    ExtensionFeature(id="devices", name="Devices",
                     rights=[_see("Paired devices"), _change("Pair and remove devices")]),
    ExtensionFeature(id="logs", name="Logs", rights=[_see("The logs and their stories")]),
    ExtensionFeature(id="logs.runs", name="Graph runs", rights=[_see("What Hiro recalled about people")]),
    ExtensionFeature(id="logs.usage", name="AI usage", rights=[_see("Its cost, per person")]),
    ExtensionFeature(id="server", name="Server",
                     rights=[_see("Workspaces, gateways, metrics"), _change("Restart and set up the server")]),
    ExtensionFeature(id="settings", name="Settings", rights=[_see("How Hiro behaves"), _change("Change it")]),
]

# Each core feature by its id: what the SDK's one check reads.
CORE_BY_ID: dict[str, ExtensionFeature] = {f.id: f for f in CORE_FEATURES}

# Talking to Hiro is a chat channel's or a device's: it opens no page of the admin.
NOT_IN_ADMIN = frozenset({"assistant"})


def every_core_key() -> list[str]:
    """Every plain key the core declares: what a role whose admin switch was on is given once (db.py)."""
    return [k for k in declared_keys(CORE_FEATURES) if not k.endswith(OWN)]


def feature_of(key: str) -> str:
    """The feature a key belongs to: everything before its action. Never find a feature's keys by prefix: ``logs.``
    also starts ``logs.runs.see``."""
    plain = key.removesuffix(OWN)
    return plain.rpartition(".")[0]


def admin_levels(keys: list[str], owner: bool) -> dict[str, str]:
    """Each core feature's level for the admin's pages: "use" with any action beyond ``see``, "see" with only that,
    else "no". Only a grant for everyone's counts; the owner has every feature at "use"."""
    levels: dict[str, str] = {}
    held = {k for k in keys if not k.endswith(OWN)}
    for f in CORE_FEATURES:
        if owner:
            levels[f.id] = "use"
            continue
        actions = {r.id for r in f.rights if f"{f.id}.{r.id}" in held}
        levels[f.id] = "use" if actions - {SEE} else "see" if SEE in actions else "no"
    return levels


def opens_admin(levels: dict[str, str]) -> bool:
    """Whether these levels open any page of the admin (beyond the Apps card)."""
    return any(level != "no" for fid, level in levels.items() if fid not in NOT_IN_ADMIN)
