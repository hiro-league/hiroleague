"""An older workspace's credentials move into credentials/ without loss, and the conversions' old copies go (438)."""

from __future__ import annotations

from pathlib import Path

from hiro_commons.keys import generate_private_key, private_key_to_pem, public_key_to_b64

from hirocli.domain import workspace_layout
from hirocli.domain.credential_store import CredentialStore
from hirocli.domain.crypto import load_or_create_master_key
from hirocli.domain.workspace_layout import credentials_index_path, drop_old_copies, master_key_path

INDEX = '{"version": 1, "providers": []}'


def _old_workspace(ws: Path) -> bytes:
    ws.mkdir(parents=True)
    key = private_key_to_pem(generate_private_key())
    (ws / "master_key.pem").write_bytes(key)
    (ws / "providers.json").write_text(INDEX, encoding="utf-8")
    return key


def test_the_key_moves_and_stays_the_same_key(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    key = _old_workspace(ws)
    loaded = load_or_create_master_key(ws)
    assert master_key_path(ws).read_bytes() == key  # the same key: no device pairs again
    assert not (ws / "master_key.pem").exists()
    assert public_key_to_b64(loaded.public_key()) == public_key_to_b64(load_or_create_master_key(ws).public_key())
    assert not list((ws / "credentials").glob("*.moving-*"))


def test_the_providers_index_moves_when_the_store_opens(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    _old_workspace(ws)
    store = CredentialStore(ws, "ws-id", _test_secrets={})
    assert store.providers_file() == credentials_index_path(ws)
    assert credentials_index_path(ws).read_text(encoding="utf-8") == INDEX
    assert not (ws / "providers.json").exists()


def test_two_different_keys_are_both_kept(tmp_path: Path, monkeypatch) -> None:
    ws = tmp_path / "ws"
    old = _old_workspace(ws)
    master_key_path(ws).parent.mkdir()
    new = private_key_to_pem(generate_private_key())
    master_key_path(ws).write_bytes(new)
    warned: list[str] = []
    monkeypatch.setattr(workspace_layout.log, "warning", lambda msg, **kw: warned.append(msg))
    workspace_layout.move_credentials(ws)
    assert (ws / "master_key.pem").read_bytes() == old and master_key_path(ws).read_bytes() == new
    assert len(warned) == 1


def test_a_move_cut_short_is_finished(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    key = _old_workspace(ws)
    master_key_path(ws).parent.mkdir()
    master_key_path(ws).write_bytes(key)  # copied, the old one not removed yet
    workspace_layout.move_credentials(ws)
    assert not (ws / "master_key.pem").exists() and master_key_path(ws).read_bytes() == key


def test_a_key_that_does_not_load_stays_where_it_is(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "master_key.pem").write_bytes(b"not a key")
    workspace_layout.move_credentials(ws)
    assert (ws / "master_key.pem").read_bytes() == b"not a key" and not master_key_path(ws).exists()


def test_the_conversions_old_copies_go_and_nothing_else(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    hiro = ws / "characters" / "hiro"
    hiro.mkdir(parents=True)
    for name in ("preferences.v3.json", "preferences.v4.json", "preferences.json", "preferences.json.before-x"):
        (ws / name).write_text("{}", encoding="utf-8")
    (hiro / "character.v3.json").write_text("{}", encoding="utf-8")
    (hiro / "character.json").write_text("{}", encoding="utf-8")
    drop_old_copies(ws)
    assert sorted(p.name for p in ws.iterdir() if p.is_file()) == ["preferences.json", "preferences.json.before-x"]
    assert [p.name for p in hiro.iterdir()] == ["character.json"]
