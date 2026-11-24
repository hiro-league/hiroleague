"""The one list's routes (Unified communication, phase 2): the list adds what is live for both kinds (connected,
and a channel's linked account), and removing picks the kind's path: a channel is stopped first, the mandatory
channel is refused before anything stops."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.responses import JSONResponse

from hiro_commons.constants.domain import MANDATORY_CHANNEL_NAME
from hirocli.admin.shared.result import Result
from hirocli.admin_svelte.routes import extensions
from hirocli.domain.extensions import KIND_APP, KIND_CHANNEL, PairedExtension
from hirocli.tools.extension import ExtensionAddressResult, ExtensionRemoveResult


def _row(name: str, kind: str, pairing: str = "") -> dict[str, Any]:
    return {
        "extension_id": f"id-{name}",
        "name": name,
        "label": name.capitalize(),
        "kind": kind,
        "version": "0.1.0",
        "description": "",
        "paired_at": None,
        "last_seen": None,
        "relays_chat": kind == KIND_CHANNEL,
        "started_by_core": kind == KIND_CHANNEL,
        "enabled": True if kind == KIND_CHANNEL else None,
        "mandatory": False,
        "has_settings": False,
        "pairing": pairing,
        "site": "",
        "offers": [],
        "uses": [],
    }


class _Manager:
    def __init__(self, live: dict[str, Any]) -> None:
        self.live = live
        self.stopped: list[str] = []
        self.closed: list[str] = []

    def snapshot(self, kind: str | None = KIND_APP) -> dict[str, Any]:
        return {k: v for k, v in self.live.items() if kind is None or v["kind"] == kind}

    def listen_state(self) -> dict[str, Any]:
        return {"listening": True, "error": None, "host": "127.0.0.1"}

    async def deactivate(self, name: str) -> None:
        self.stopped.append(name)

    async def disconnect(self, extension_id: str) -> None:
        self.closed.append(extension_id)


def _request(status: dict[str, Any] | None = None) -> Any:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(ctx=SimpleNamespace(channel_status=status or {}))))


def _connected(kind: str) -> dict[str, Any]:
    return {"kind": kind, "info": {"version": "0.2.0"}, "connected_at": "2026-11-23T10:00:00Z", "remote": "127.0.0.1"}


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [_row("whatsapp", KIND_CHANNEL, pairing="qr"), _row("home", KIND_APP)]
    monkeypatch.setattr(extensions.ExtensionService, "list_extensions", lambda self, w: Result.success(rows))
    monkeypatch.setattr(
        extensions.ExtensionService,
        "address",
        lambda self, w, host=None: Result.success(ExtensionAddressResult("127.0.0.1", 18082, "ws://x", False, False)),
    )
    monkeypatch.setattr(extensions.ExtensionService, "workspace_path", lambda self, w: None)


def test_the_list_marks_both_kinds_connected_and_a_channels_link(service, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _Manager({"id-whatsapp": _connected(KIND_CHANNEL), "id-home": _connected(KIND_APP)})
    monkeypatch.setattr(extensions, "_live_manager", lambda request, path: manager)
    request = _request({"whatsapp": {"state": "ready", "account": "The family's WhatsApp"}})

    answer = asyncio.run(extensions.list_extensions(request, workspace_id="w"))  # type: ignore[arg-type]

    rows = {r["name"]: r for r in answer["extensions"]}
    assert rows["whatsapp"]["connected"] and rows["home"]["connected"]
    assert rows["whatsapp"]["version"] == "0.2.0"  # the live connection's version
    assert rows["whatsapp"]["linked"] is True and rows["whatsapp"]["account"] == "The family's WhatsApp"
    assert rows["home"]["linked"] is None  # an app links no account
    extensions.ExtensionList.model_validate(answer)  # the declared answer


def test_a_channel_waiting_for_its_qr_code_is_not_linked(service, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extensions, "_live_manager", lambda request, path: _Manager({}))
    request = _request({"whatsapp": {"state": "spawned"}})

    answer = asyncio.run(extensions.list_extensions(request, workspace_id="w"))  # type: ignore[arg-type]

    whatsapp = next(r for r in answer["extensions"] if r["name"] == "whatsapp")
    assert whatsapp["connected"] is False and whatsapp["linked"] is False


def _found(monkeypatch: pytest.MonkeyPatch, name: str, kind: str) -> list[str]:
    removed: list[str] = []
    ext = PairedExtension(extension_id=f"id-{name}", name=name, kind=kind, started_by_core=kind == KIND_CHANNEL)
    monkeypatch.setattr(extensions.ExtensionService, "find", lambda self, eid, w: ext)
    monkeypatch.setattr(extensions.ExtensionService, "workspace_path", lambda self, w: None)

    def remove(self: Any, eid: str, w: Any) -> Result[ExtensionRemoveResult]:
        removed.append(eid)
        return Result.success(ExtensionRemoveResult(True, eid, kind=kind, name=name, uninstalled=True))

    monkeypatch.setattr(extensions.ExtensionService, "remove_extension", remove)
    return removed


def test_removing_a_channel_stops_it_first(monkeypatch: pytest.MonkeyPatch) -> None:
    removed = _found(monkeypatch, "whatsapp", KIND_CHANNEL)
    manager = _Manager({})
    monkeypatch.setattr(extensions, "_live_manager", lambda request, path: manager)
    request = _request({"whatsapp": {"state": "ready"}})

    answer = asyncio.run(extensions.remove_extension("id-whatsapp", request, workspace_id="w"))  # type: ignore[arg-type]

    assert manager.stopped == ["whatsapp"] and removed == ["id-whatsapp"]
    assert "whatsapp" not in request.app.state.ctx.channel_status
    assert "uninstalled" in answer["message"]


def test_removing_an_app_closes_its_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    _found(monkeypatch, "home", KIND_APP)
    manager = _Manager({})
    monkeypatch.setattr(extensions, "_live_manager", lambda request, path: manager)

    asyncio.run(extensions.remove_extension("id-home", _request(), workspace_id="w"))  # type: ignore[arg-type]

    assert manager.closed == ["id-home"] and manager.stopped == []


def test_the_mandatory_channel_is_refused_before_anything_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    removed = _found(monkeypatch, MANDATORY_CHANNEL_NAME, KIND_CHANNEL)
    manager = _Manager({})
    monkeypatch.setattr(extensions, "_live_manager", lambda request, path: manager)

    answer = asyncio.run(
        extensions.remove_extension(f"id-{MANDATORY_CHANNEL_NAME}", _request(), workspace_id="w")  # type: ignore[arg-type]
    )

    assert isinstance(answer, JSONResponse) and answer.status_code == 400
    assert manager.stopped == [] and removed == []


def test_an_extension_already_gone_is_a_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extensions.ExtensionService, "find", lambda self, eid, w: None)

    answer = asyncio.run(extensions.remove_extension("gone", _request(), workspace_id="w"))  # type: ignore[arg-type]

    assert isinstance(answer, JSONResponse) and answer.status_code == 404


def test_removing_an_app_says_what_went_with_it(monkeypatch: pytest.MonkeyPatch) -> None:
    ext = PairedExtension(extension_id="id-home", name="home", kind=KIND_APP)
    monkeypatch.setattr(extensions.ExtensionService, "find", lambda self, eid, w: ext)
    monkeypatch.setattr(extensions.ExtensionService, "workspace_path", lambda self, w: None)
    monkeypatch.setattr(extensions, "_live_manager", lambda request, path: None)
    gone = ExtensionRemoveResult(True, "id-home", kind=KIND_APP, name="home", site_name="home.hiro.local",
                                 rights_dropped={"adult": ["x.see"], "kid": ["x.see"]}, picks_dropped=["ai.uses: home:ask"])
    monkeypatch.setattr(extensions.ExtensionService, "remove_extension", lambda self, eid, w: Result.success(gone))

    answer = asyncio.run(extensions.remove_extension("id-home", _request(), workspace_id="w"))  # type: ignore[arg-type]

    assert answer["message"] == ("home removed, with its name home.hiro.local, its rights in 2 role(s), 1 AI or voice "
                                 "pick(s): it pairs again with a new code. Its own data stays.")
