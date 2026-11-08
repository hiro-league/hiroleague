"""People routes: the family list, its roles and admin sign-ins (the plan's Phase 6).

Thin over the people tools (tools/people.py), for the selected workspace. A refused
change comes back as ``ok: false`` with the reason for people.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter
from hiro_commons.log import Logger
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from hirocli.admin_svelte.deps import SelectedWorkspaceIdDep
from hirocli.admin_svelte.result_payload import envelope_failure
from hirocli.domain.people import PeopleError
from hirocli.domain.workspace import WorkspaceError
from hirocli.tools.people import (
    PeopleListTool,
    PersonAddTool,
    PersonRemoveTool,
    PersonSignInRemoveTool,
    PersonSignInTool,
    PersonUpdateTool,
    RoleAddTool,
    RoleRemoveTool,
    RoleRenameTool,
)

log = Logger.get("ADMIN.PEOPLE")

people_router = APIRouter()


class PersonBody(BaseModel):
    name: str
    role_id: str
    calls_them: str = ""
    whatsapp: str = ""


class PersonPatch(BaseModel):
    name: str | None = None
    role_id: str | None = None
    calls_them: str | None = None
    whatsapp: str | None = None


class SignInBody(BaseModel):
    sign_in: str
    password: str


class RoleBody(BaseModel):
    name: str


async def _call(what: str, run: Callable[[], Any]) -> dict[str, Any]:
    """Run a people tool in a worker thread; a refused change is ``ok: false``."""
    try:
        result = await run_in_threadpool(run)
    except (PeopleError, WorkspaceError) as exc:
        return envelope_failure(str(exc))
    except Exception as exc:
        log.error(f"❌ People change failed — {what}", error=str(exc), exc_info=True)
        return envelope_failure(f"Couldn't {what}: {exc}")
    return {"ok": True, "error": None, "data": asdict(result)}


@people_router.get("/people")
async def list_people(workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    return await _call("read the family list", lambda: PeopleListTool().execute(workspace=workspace_id))


@people_router.post("/people")
async def add_person(body: PersonBody, workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    return await _call(
        "add the person",
        lambda: PersonAddTool().execute(
            name=body.name, role_id=body.role_id, calls_them=body.calls_them, whatsapp=body.whatsapp, workspace=workspace_id
        ),
    )


@people_router.put("/people/{person_id}")
async def update_person(person_id: str, body: PersonPatch, workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    return await _call(
        "save the person",
        lambda: PersonUpdateTool().execute(
            person=person_id,
            name=body.name,
            role_id=body.role_id,
            calls_them=body.calls_them,
            whatsapp=body.whatsapp,
            workspace=workspace_id,
        ),
    )


@people_router.delete("/people/{person_id}")
async def remove_person(person_id: str, workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    return await _call("remove the person", lambda: PersonRemoveTool().execute(person=person_id, workspace=workspace_id))


@people_router.put("/people/{person_id}/sign-in")
async def set_sign_in(person_id: str, body: SignInBody, workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    return await _call(
        "set the sign-in",
        lambda: PersonSignInTool().execute(
            person=person_id, sign_in=body.sign_in, password=body.password, workspace=workspace_id
        ),
    )


@people_router.delete("/people/{person_id}/sign-in")
async def remove_sign_in(person_id: str, workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    return await _call(
        "remove the sign-in", lambda: PersonSignInRemoveTool().execute(person=person_id, workspace=workspace_id)
    )


@people_router.post("/roles")
async def add_role(body: RoleBody, workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    return await _call("add the role", lambda: RoleAddTool().execute(name=body.name, workspace=workspace_id))


@people_router.put("/roles/{role_id}")
async def rename_role(role_id: str, body: RoleBody, workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    return await _call(
        "rename the role", lambda: RoleRenameTool().execute(role_id=role_id, name=body.name, workspace=workspace_id)
    )


@people_router.delete("/roles/{role_id}")
async def remove_role(role_id: str, workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    return await _call("remove the role", lambda: RoleRemoveTool().execute(role_id=role_id, workspace=workspace_id))
