"""Removing an app cleans up what the core kept under its name (Installing apps, phase 2): its LAN name, every role's
grants in it, its AI and voice picks and the folders its asks may name. Another app's, and the app's own data, stay."""

from __future__ import annotations

import logging
import sqlite3
from types import SimpleNamespace

import pytest

from hirocli.domain.db import db_path
from hirocli.domain.events import DomainEventType, get_domain_event_bus
from hirocli.domain.extensions import add_paired_extension, list_paired_extensions
from hirocli.domain.people import get_role, set_role_rights
from hirocli.domain.site_names import claim, list_claims
from hirocli.runtime.preferences_runtime import preferences_runtime_for
from hirocli.tools import extension as extension_tools
from hirocli.tools.extension import ExtensionRemoveTool, picks_without


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(extension_tools, "_resolve_path", lambda _ws: tmp_path)
    home = add_paired_extension(tmp_path, name="home", public_key="pk-home", info={"name": "home"})
    net = add_paired_extension(tmp_path, name="net", public_key="pk-net", info={"name": "net"})
    claim(tmp_path, home.extension_id, "home.hiro.local", 8100, set())
    claim(tmp_path, net.extension_id, "net.hiro.local", 8130, set())
    set_role_rights(tmp_path, "adult", "home", ["dashboard.see", "dashboard.control.switch"])
    set_role_rights(tmp_path, "adult", "net", ["status.see"])
    set_role_rights(tmp_path, "kid", "home", ["dashboard.see"])
    set_role_rights(tmp_path, "kid", "hiroleague", ["assistant.see"])
    preferences_runtime_for(tmp_path).update_many({
        "ai.uses": {"home:ask": None, "net:explain": None, "homehiro:other": None},
        "voice.uses": {"home:say": None},
        "embedding.uses": {"home:find": None},
        "rerank.uses": {"net:order": None},
        "ai.folders": {"home": ["C:/x"], "net": ["C:/y"]},
    })
    return tmp_path


def _id(workspace, name: str) -> str:
    return next(e.extension_id for e in list_paired_extensions(workspace) if e.name == name)


def test_removing_an_app_leaves_no_name_grant_or_pick_behind(workspace, caplog) -> None:
    caplog.set_level(logging.INFO)

    result = ExtensionRemoveTool().execute(_id(workspace, "home"))

    assert result.removed and result.site_name == "home.hiro.local"
    assert [c.name for c in list_claims(workspace)] == ["net.hiro.local"]
    assert result.rights_dropped == {"adult": ["dashboard.see", "dashboard.control.switch"], "kid": ["dashboard.see"]}
    assert get_role(workspace, "adult").rights == {"net": ["status.see"]}
    assert get_role(workspace, "kid").rights == {"hiroleague": ["assistant.see"]}
    prefs = preferences_runtime_for(workspace).current
    assert prefs.ai.uses == {"net:explain": None, "homehiro:other": None}  # the name matched exactly
    assert prefs.voice.uses == {} and prefs.embedding.uses == {} and prefs.rerank.uses == {"net:order": None}
    assert prefs.ai.folders == {"net": ["C:/y"]}
    assert sorted(result.picks_dropped) == [
        "ai.folders: home", "ai.uses: home:ask", "embedding.uses: home:find", "voice.uses: home:say",
    ]
    # What went is in the log, so a removal by mistake can be set again by hand.
    [line] = [r for r in caplog.records if "App removed" in r.getMessage()]
    assert line.levelno == logging.INFO and "home.hiro.local" in line.getMessage()


def test_the_running_core_hears_the_removal(workspace, monkeypatch) -> None:
    heard: list[dict] = []
    monkeypatch.setattr(get_domain_event_bus(), "publish",
                        lambda event: heard.append({"type": event.type, **event.payload}))
    home = _id(workspace, "home")

    ExtensionRemoveTool().execute(home)

    assert {"type": DomainEventType.EXTENSION_REMOVED, "extension_id": home, "name": "home",
            "site_name": "home.hiro.local"} in heard


def test_an_app_with_no_name_grant_or_pick_is_removed_all_the_same(workspace) -> None:
    lone = add_paired_extension(workspace, name="lone", public_key="pk-lone", info={"name": "lone"})

    result = ExtensionRemoveTool().execute(lone.extension_id)

    assert result.removed and (result.site_name, result.rights_dropped, result.picks_dropped) == ("", {}, [])


def test_a_name_another_row_still_holds_keeps_its_grants_and_picks(workspace) -> None:
    # Two rows could share a name before names were unique; removing one leaves the other's grants and picks.
    with sqlite3.connect(str(db_path(workspace))) as conn:
        conn.execute("INSERT INTO extension_records (extension_id, name, kind, public_key, paired_at, info, "
                     "relays_chat, started_by_core) VALUES ('old-home', 'home', 'app', 'pk', '', '{}', 0, 0)")
        conn.commit()

    result = ExtensionRemoveTool().execute("old-home")

    assert result.removed and result.rights_dropped == {} and result.picks_dropped == []
    assert "home" in get_role(workspace, "adult").rights
    assert "home:ask" in preferences_runtime_for(workspace).current.ai.uses


def test_picks_match_the_whole_name() -> None:
    prefs = SimpleNamespace(
        ai=SimpleNamespace(uses={"home:ask": "p", "homehiro:x": "p"}, folders={"home": [], "homehiro": []}),
        voice=SimpleNamespace(uses={}),
        embedding=SimpleNamespace(uses={}),
        rerank=SimpleNamespace(uses={}),
    )

    edits, dropped = picks_without(prefs, "home")

    assert edits == {"ai.uses": {"homehiro:x": "p"}, "ai.folders": {"homehiro": []}}
    assert dropped == ["ai.uses: home:ask", "ai.folders: home"]


def test_pair_again_makes_a_code_for_one_app_only(workspace) -> None:
    from hirocli.domain.extensions import load_extension_pairing
    from hirocli.tools.extension import ExtensionPairAgainTool

    home = _id(workspace, "home")
    result = ExtensionPairAgainTool().execute(home)

    assert result.pairs_again == "home" and load_extension_pairing(workspace).extension_id == home
    with pytest.raises(ValueError, match="isn't in the list"):
        ExtensionPairAgainTool().execute("no-such-id")
    with sqlite3.connect(str(db_path(workspace))) as conn:
        conn.execute("INSERT INTO extension_records (extension_id, name, kind, public_key, paired_at, info, "
                     "relays_chat, started_by_core) VALUES ('e-wa', 'whatsapp', 'channel', 'pk', '', '{}', 1, 1)")
        conn.commit()
    with pytest.raises(ValueError, match="channel"):
        ExtensionPairAgainTool().execute("e-wa")
