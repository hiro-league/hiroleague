"""The extensions' searching uses for the Catalog's Profiles → Uses tab: what each paired extension declared it embeds
(``ExtensionInfo.embed_uses``) and reranks (``rerank_uses``), and the profile picked for each.

The profiles themselves, Hiro's own four searching uses and the picks are written through the preferences API
(``embedding.*``, ``rerank.*``, the graph and knowledge fields), like the voice profiles.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from hirocli.admin_svelte.deps import SelectedWorkspaceIdDep
from hirocli.admin_svelte.result_payload import api_failure
from hirocli.admin_svelte.routes.ai import _workspace_path

search_router = APIRouter()

KINDS = ("embedding", "rerank")


def search_use_groups(workspace_path: Path, prefs: Any) -> list[dict[str, Any]]:
    """Each paired extension with search uses: ``{extension, embedding: [use], rerank: [use]}``, a use being
    ``{key, id, name, profile_id, status}``; a pick for a use the extension no longer declares is ``removed``."""
    from hirocli.domain.extensions import list_paired_extensions

    out: list[dict[str, Any]] = []
    for ext in list_paired_extensions(workspace_path):
        group: dict[str, Any] = {"extension": ext.name}
        for kind in KINDS:
            picks: dict[str, str | None] = getattr(prefs, kind).uses
            rows, declared = [], set()
            for use in ext.declared_search_uses(kind):
                key = f"{ext.name}:{use['id']}"
                declared.add(key)
                rows.append({"key": key, "id": use["id"], "name": str(use.get("name") or use["id"]),
                             "profile_id": picks.get(key), "status": "ok"})
            for key, pid in sorted(picks.items()):
                if key.startswith(f"{ext.name}:") and key not in declared:
                    use_id = key.partition(":")[2]
                    rows.append({"key": key, "id": use_id, "name": use_id, "profile_id": pid, "status": "removed"})
            group[kind] = rows
        if group["embedding"] or group["rerank"]:
            out.append(group)
    return out


@search_router.get("/search/uses")
async def search_uses(workspace_id: SelectedWorkspaceIdDep) -> Any:
    path = _workspace_path(workspace_id)
    if path is None:
        return api_failure("No workspace selected.")
    from hirocli.runtime.preferences_runtime import preferences_runtime_for

    prefs = preferences_runtime_for(path).current
    return {"extensions": await run_in_threadpool(search_use_groups, path, prefs)}
