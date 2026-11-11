"""Routes that post-process a tool's answer read the data itself (UI kit step 1d).

Two routes still read the old ``{"ok", "data"}`` envelope after step 1d's backend change and raised
``KeyError: 'ok'`` (an HTTP 500): People -> Roles' access list, and the local servers' check.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi import Response

from hirocli.admin_svelte.routes import ai, people
from hirocli.domain.people import PeopleError


@dataclass
class _Access:
    sources: list[dict[str, Any]] = field(default_factory=list)
    roles: list[dict[str, Any]] = field(default_factory=list)


class _Manager:
    def snapshot(self) -> dict[str, Any]:
        return {"ext-1": {}}


def _access_tool(result: Any) -> type:
    class Tool:
        def execute(self, **_: Any) -> Any:
            if isinstance(result, Exception):
                raise result
            return result

    return Tool


def test_access_list_marks_each_source_connected(monkeypatch: pytest.MonkeyPatch) -> None:
    sources = [
        {"id": "hiroleague", "kind": "core", "extension_id": ""},
        {"id": "home", "kind": "extension", "extension_id": "ext-1"},
        {"id": "net", "kind": "extension", "extension_id": "ext-2"},
    ]
    monkeypatch.setattr(people, "AccessListTool", _access_tool(_Access(sources=sources)))
    monkeypatch.setattr(people.ExtensionService, "workspace_path", lambda self, workspace_id: None)
    monkeypatch.setattr(people, "_live_manager", lambda request, path: _Manager())

    answer = asyncio.run(people.list_access(request=None, workspace_id="w"))  # type: ignore[arg-type]

    assert [s["connected"] for s in answer["sources"]] == [True, True, False]
    assert "ok" not in answer and "data" not in answer


def test_access_list_failure_is_the_failure_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(people, "AccessListTool", _access_tool(PeopleError("No such workspace.")))

    answer = asyncio.run(people.list_access(request=None, workspace_id="w"))  # type: ignore[arg-type]

    assert isinstance(answer, Response) and answer.status_code == 400
    assert json.loads(answer.body) == {"detail": "No such workspace."}


@dataclass
class _Server:
    provider_id: str
    state: str = "up"


def test_local_servers_lists_each_check(monkeypatch: pytest.MonkeyPatch) -> None:
    class Check:
        def execute(self, *, provider_id: str, workspace: str) -> _Server:
            return _Server(provider_id)

    monkeypatch.setattr(ai, "LocalServerCheckTool", Check)
    monkeypatch.setattr(ai, "DISCOVERABLE_LOCAL_PROVIDERS", ("ollama", "lm_studio"))

    answer = asyncio.run(ai.ai_local_servers(workspace_id="w"))

    assert answer == {
        "servers": [{"provider_id": "ollama", "state": "up"}, {"provider_id": "lm_studio", "state": "up"}]
    }


def test_local_servers_failure_is_the_failure_response(monkeypatch: pytest.MonkeyPatch) -> None:
    class Check:
        def execute(self, *, provider_id: str, workspace: str) -> _Server:
            raise ValueError("Unknown provider.")

    monkeypatch.setattr(ai, "LocalServerCheckTool", Check)
    monkeypatch.setattr(ai, "DISCOVERABLE_LOCAL_PROVIDERS", ("ollama",))

    answer = asyncio.run(ai.ai_local_servers(workspace_id="w"))

    assert isinstance(answer, Response) and answer.status_code == 400
    assert json.loads(answer.body) == {"detail": "Unknown provider."}
