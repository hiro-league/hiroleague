"""Every name this machine serves, and the owner's own: extra names beside an app's and other sites (``hiro sites``).

An app's main name is its own (``sites.claim``, from its address setting); the owner adds an extra name beside it
(``homehiro.local`` for HomeHiro, kept for the Home Assistant add-on), or a site that is no app: a name or the
machine's address sent to a port on this machine, optionally only some paths, or a name only announced. The core
serves each at once when it runs (the tools run inside it: ``hiro sites add`` posts to the running server), else at
its next start. docs/site-names-design.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hiro_commons.log import Logger

from ..domain.config import load_config
from ..domain.events import DomainEvent, DomainEventType, get_domain_event_bus
from ..domain.extensions import list_paired_extensions
from ..domain.site_names import (
    CORE_ID,
    OTHER_ID,
    SiteNameError,
    add_extra,
    add_other_site,
    core_names_of,
    list_claims,
    list_other_sites,
    remove_site,
    served,
    taken_by_core,
)
from ..domain.workspace import resolve_workspace
from .base import Tool, ToolParam

log = Logger.get("TOOLS.SITES")

_WORKSPACE = ToolParam(str, "Workspace name (default: registry default)", required=False)


@dataclass
class SitesListResult:
    # One per name served: {name, kind (app | extra | core | site), owner, target, paths, announced}
    sites: list[dict[str, Any]] = field(default_factory=list)
    ip: str = ""


@dataclass
class SitesChangeResult:
    name: str
    change: str  # added | removed | refused
    kind: str = ""  # extra | site
    target: str = ""
    paths: list[str] = field(default_factory=list)
    # A refusal is an answer, not an error (the name taken, a rule broken): its code and its words for people. Raised,
    # it would reach the HTTP surface as an unexpected failure.
    code: str = ""
    reason: str = ""


def _refused(name: str, exc: SiteNameError) -> SitesChangeResult:
    log.info(f"Site refused — {name} · {exc.code}")
    return SitesChangeResult(name=name, change="refused", code=exc.code, reason=str(exc))


def _path(workspace: str | None) -> Path:
    entry, _ = resolve_workspace(workspace)
    return Path(entry.path)


def _changed(workspace_path: Path, name: str, change: str) -> None:
    # The running core serves what the tables hold now (runtime/site_names.py); with none running, its next start does.
    get_domain_event_bus().publish(DomainEvent(
        type=DomainEventType.SITES_CHANGED, workspace_path=workspace_path, payload={"name": name, "change": change},
    ))


class SitesListTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "sites_list"
    description = "List every name this machine serves: apps' names, their extra names, the core's own and other sites"
    params = {"workspace": _WORKSPACE}

    def execute(self, workspace: str | None = None) -> SitesListResult:
        workspace_path = _path(workspace)
        config = load_config(workspace_path)
        claims = list_claims(workspace_path)
        apps = {e.extension_id: e.name for e in list_paired_extensions(workspace_path, kind=None)}
        extra = {c.name for c in claims if c.extra}
        plan = served(claims, core_names_of(config), list_other_sites(workspace_path))
        sites = []
        for s in sorted(plan.sites, key=lambda s: s.name):
            kind = "core" if s.owner == CORE_ID else "site" if s.owner == OTHER_ID else "extra" if s.name in extra else "app"
            sites.append({
                "name": s.name, "kind": kind, "owner": apps.get(s.owner, s.owner), "target": s.upstream,
                "paths": list(s.paths), "announced": s.announce and bool(config.site_names_ip),
            })
        return SitesListResult(sites=sites, ip=config.site_names_ip)


class SitesAddTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "sites_add"
    description = (
        "Add a name this machine serves: an extra name beside an app's own (app), or a site that is no app (a .local "
        "name or the machine's address) sent to a port here (target), optionally only some paths, or a name only "
        "announced (no target)"
    )
    params = {
        "name": ToolParam(str, "The name (adguard.local) or the machine's address (192.168.1.10)"),
        "app": ToolParam(str, "The app it is an extra name of, by its key (home)", required=False),
        "target": ToolParam(str, "Where it goes on this machine: a port (3001) or host:port", required=False),
        "paths": ToolParam(list[str], "Only these paths go to the target (/tv, /_app/*); the rest answers 404",
                           required=False),
        "workspace": _WORKSPACE,
    }

    def execute(
        self,
        name: str,
        app: str | None = None,
        target: str | None = None,
        paths: list[str] | None = None,
        workspace: str | None = None,
    ) -> SitesChangeResult:
        workspace_path = _path(workspace)
        try:
            return self._add(workspace_path, name, app, target, paths)
        except SiteNameError as exc:
            return _refused(name, exc)

    def _add(
        self, workspace_path: Path, name: str, app: str | None, target: str | None, paths: list[str] | None,
    ) -> SitesChangeResult:
        config = load_config(workspace_path)
        taken, domain = taken_by_core(config), config.site_domain()
        if app:
            if target or paths:
                raise SiteNameError("invalid", "An extra name goes where its app's own name goes: give --app, or a "
                                               "--target, not both.")
            ext = next((e for e in list_paired_extensions(workspace_path) if e.name == app), None)
            if ext is None:
                raise SiteNameError("not_found", f"No app is called {app} (hiro extension list).")
            kept = add_extra(workspace_path, ext.extension_id, name, taken, domain)
            log.info(f"✅ Extra name added — {kept.name} · {app}", port=kept.port)
            _changed(workspace_path, kept.name, "added")
            return SitesChangeResult(name=kept.name, change="added", kind="extra", target=f"127.0.0.1:{kept.port}")
        site = add_other_site(workspace_path, name, target or "", list(paths or []), taken, domain)
        log.info(f"✅ Site added — {site.name}", target=site.target or "(announced only)", paths=" ".join(site.paths))
        _changed(workspace_path, site.name, "added")
        return SitesChangeResult(name=site.name, change="added", kind="site", target=site.target,
                                 paths=list(site.paths))


class SitesRemoveTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "sites_remove"
    description = "Remove an extra name or an other site (an app's own name goes with the app)"
    params = {"name": ToolParam(str, "The name or address to remove"), "workspace": _WORKSPACE}

    def execute(self, name: str, workspace: str | None = None) -> SitesChangeResult:
        workspace_path = _path(workspace)
        try:
            kind = remove_site(workspace_path, name)
        except SiteNameError as exc:
            return _refused(name, exc)
        clean = name.strip().lower()
        log.info(f"🗑️ {'Extra name' if kind == 'extra' else 'Site'} removed — {clean}")
        _changed(workspace_path, clean, "removed")
        return SitesChangeResult(name=clean, change="removed", kind=kind)
