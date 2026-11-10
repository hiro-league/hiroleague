"""What each role may do, per source (the plan's Phase 9a).

A source is HiroLeague itself or one paired extension. Each declares features with rights
(hiro_channel_sdk.access); the core keeps, per role, the rights it grants in each extension
(domain/people.py ``Role.rights``) and the extension enforces them. HiroLeague's own source has one
right for now, opening its settings, which is Phase 8's ``Role.admin`` switch; Hiro's tools get
theirs in Phase 10.

Rights are checked against what the extension declared when they are set, and again when they are
read (a right the extension no longer declares drops out). The owner has every right except the
features not made for the owner, and can't be changed.

Synchronous (CLI and admin worker threads), like domain/people.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hiro_channel_sdk.access import ExtensionFeature, ExtensionRight, normalize, owner_rights
from pydantic import BaseModel, ValidationError

from hiro_commons.log import Logger

from .extensions import PairedExtension, list_paired_extensions
from .people import OWNER_ROLE, PeopleError, Role, get_role, list_roles, set_role_admin, set_role_rights, set_role_says

log = Logger.get("ACCESS")

CORE_SOURCE = "hiroleague"
CORE_FEATURES: list[ExtensionFeature] = [
    ExtensionFeature(
        id="admin",
        name="HiroLeague's settings",
        rights=[ExtensionRight(id="open", name="Open", says="Open HiroLeague's settings (this admin); without it, the Apps card only")],
    )
]
ADMIN_OPEN = "admin.open"


class Source(BaseModel):
    id: str  # "hiroleague", or the extension's name (the key its rights are kept under)
    name: str
    kind: str  # "core" | "extension"
    extension_id: str = ""
    features: list[ExtensionFeature]


def _declared(ext: PairedExtension) -> list[ExtensionFeature]:
    """The features an extension last declared; a malformed one is skipped (logged), not fatal."""
    out: list[ExtensionFeature] = []
    for raw in ext.info.get("features") or []:
        try:
            out.append(ExtensionFeature.model_validate(raw))
        except ValidationError as exc:
            log.warning(f"⚠️ A declared feature can't be read — {ext.name} · skipped", error=str(exc)[:200])
    return out


def list_sources(workspace_path: Path) -> list[Source]:
    """HiroLeague first, then every paired extension that declared features, in pairing order."""
    sources = [Source(id=CORE_SOURCE, name="HiroLeague", kind="core", features=CORE_FEATURES)]
    for ext in list_paired_extensions(workspace_path):
        features = _declared(ext)
        if features and ext.name:
            sources.append(Source(id=ext.name, name=_title(ext), kind="extension", extension_id=ext.extension_id, features=features))
    return sources


def _title(ext: PairedExtension) -> str:
    """What people call the extension: its site's title on the Apps card (Phase 8: HomeHiro's is "Home"), else its name."""
    offers = ext.info.get("offers") or {}
    for item in offers.get("shows") or [] if isinstance(offers, dict) else []:
        if isinstance(item, dict) and item.get("title"):
            return str(item["title"])
    return ext.name


def source_features(workspace_path: Path, source: str) -> list[ExtensionFeature]:
    for s in list_sources(workspace_path):
        if s.id == source:
            return s.features
    raise PeopleError(f"{source} hasn't declared any features to give rights in.")


def rights_in(role: Role, source: str, features: list[ExtensionFeature]) -> list[str]:
    """A role's rights in one source, kept to what the source declares now."""
    if role.role_id == OWNER_ROLE:
        return [k for k in normalize(features, owner_rights(features))]
    if source == CORE_SOURCE:
        return [ADMIN_OPEN] if role.admin else []
    return normalize(features, role.rights.get(source, []))


def set_rights(workspace_path: Path, role_id: str, source: str, keys: list[str]) -> Role:
    """Give a role exactly these rights in one source (unknown keys refused, ``see`` added where needed)."""
    features = source_features(workspace_path, source)
    known = {f"{f.id}.{r.id}" for f in features for r in f.rights}
    unknown = sorted(set(keys) - known)
    if unknown:
        raise PeopleError(f"{source} has no right called {', '.join(unknown)}.")
    if source == CORE_SOURCE:
        return set_role_admin(workspace_path, role_id, ADMIN_OPEN in keys)
    return set_role_rights(workspace_path, role_id, source, normalize(features, keys))


def import_rights(workspace_path: Path, source: str, roles: dict[str, Any]) -> list[str]:
    """Once, an extension's own grants from before Phase 9a: fills only roles with no rights in that source yet
    (and an empty ``says``); never overwrites what the admin set. Unknown roles are skipped. Returns the role ids
    whose rights were filled."""
    features = source_features(workspace_path, source)
    filled: list[str] = []
    for role_id, entry in roles.items():
        role = get_role(workspace_path, str(role_id))
        if role is None or role.role_id == OWNER_ROLE or not isinstance(entry, dict):
            continue
        says = str(entry.get("says") or "").strip()
        if says and not role.says:
            set_role_says(workspace_path, role.role_id, says)
        if source in role.rights:
            continue
        keys = [str(k) for k in entry.get("rights") or []]
        set_role_rights(workspace_path, role.role_id, source, normalize(features, keys))
        filled.append(role.role_id)
    return filled


def roles_for_extension(workspace_path: Path, source: str) -> list[dict[str, Any]]:
    """Every role as one extension sees it: its rights there, not the other extensions'."""
    try:
        features = source_features(workspace_path, source)
    except PeopleError:
        features = []
    return [
        {"role_id": r.role_id, "name": r.name, "built_in": r.built_in, "says": r.says, "rights": rights_in(r, source, features)}
        for r in list_roles(workspace_path)
    ]


def roles_with_rights(workspace_path: Path) -> list[dict[str, Any]]:
    """Every role with its rights in every source (the admin's Roles tab)."""
    sources = list_sources(workspace_path)
    return [
        {**r.model_dump(exclude={"rights"}), "rights": {s.id: rights_in(r, s.id, s.features) for s in sources}}
        for r in list_roles(workspace_path)
    ]
