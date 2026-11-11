"""The folder an ``ai.ask`` may name for a plan tool to read: who may, where, and what the request carries."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from hirocli.domain.preferences import AiPreferences
from hirocli.services.ai_ask import AskError
from hirocli.services.ai_ask.errors import ProviderFailed
from hirocli.services.ai_ask.folders import check_folder
from hirocli.services.ai_ask.params import ask_request_from_params
from hirocli.services.ai_ask.providers import ChatModelProvider, ProviderCall


def _check(folder: Path | str, allowed: list[Path | str], reads: bool = True) -> Path:
    return check_folder(str(folder), [str(a) for a in allowed], extension="reports", use="review", use_reads_folders=reads)


def test_a_folder_inside_an_allowed_one_is_resolved(tmp_path: Path) -> None:
    root = tmp_path / "worktrees"
    inner = root / "hiroleague" / "abc123"
    inner.mkdir(parents=True)
    assert _check(inner, [root]) == inner.resolve()
    assert _check(root, [root]) == root.resolve()  # the allowed folder itself


def test_everything_else_is_refused(tmp_path: Path) -> None:
    root, other = tmp_path / "worktrees", tmp_path / "secrets"
    root.mkdir()
    other.mkdir()
    (root / "file.txt").write_text("x", encoding="utf-8")
    cases = [
        (other, [root], True, "outside"),  # not inside an allowed folder
        (root / "gone", [root], True, "no folder"),
        (root / "file.txt", [root], True, "isn't a folder"),
        (root, [], True, "isn't allowed to name any folder"),  # nothing allowed for this extension
        (root, [root], False, "doesn't declare"),  # the use doesn't say it reads a folder
        ("relative/path", [root], True, "absolute"),
        ("", [root], True, "absolute"),
        (str(root) + os.sep + ".." + os.sep + "secrets", [root], True, "outside"),  # .. resolves out of it
    ]
    for folder, allowed, reads, why in cases:
        with pytest.raises(AskError, match=why) as err:
            _check(folder, allowed, reads)
        assert err.value.code == "invalid"


def test_a_link_pointing_out_of_the_allowed_folder_is_refused(tmp_path: Path) -> None:
    root, other = tmp_path / "worktrees", tmp_path / "secrets"
    root.mkdir()
    other.mkdir()
    link = root / "sneaky"
    try:
        link.symlink_to(other, target_is_directory=True)
    except OSError:
        pytest.skip("this machine can't make symlinks")
    with pytest.raises(AskError, match="outside"):
        _check(link, [root])


def test_a_sibling_whose_name_starts_the_same_is_not_inside(tmp_path: Path) -> None:
    root, sibling = tmp_path / "work", tmp_path / "work-secrets"
    root.mkdir()
    sibling.mkdir()
    with pytest.raises(AskError, match="outside"):
        _check(sibling, [root])


def test_the_request_carries_the_folder_but_not_with_pictures_or_sound() -> None:
    request = ask_request_from_params({"prompt": "Review", "folder": " /srv/x "}, use_key="reports:review", who="reports")
    assert request.folder == "/srv/x" and not request.pictures
    assert ask_request_from_params({"prompt": "Ask"}, use_key="reports:review", who="reports").folder == ""
    for extra in ({"pictures": ["aGk="]}, {"sound": {"b64": "aGk="}}):
        with pytest.raises(AskError, match="can't carry"):
            ask_request_from_params({"prompt": "Review", "folder": "/srv/x", **extra}, use_key="reports:review", who="reports")
    with pytest.raises(AskError, match="path as text"):
        ask_request_from_params({"prompt": "Review", "folder": 5}, use_key="reports:review", who="reports")


def test_the_admin_allows_folders_per_extension() -> None:
    prefs = AiPreferences.model_validate({"folders": {"reports": ["/srv/worktrees"]}})
    assert prefs.folders == {"reports": ["/srv/worktrees"]} and AiPreferences().folders == {}


def test_an_api_or_local_model_cannot_read_a_folder_so_the_walk_moves_on(tmp_path: Path) -> None:
    call = ProviderCall(
        profile=SimpleNamespace(), target=SimpleNamespace(model_id="google:gemini-3.8-flash"), prompt="Review", folder=tmp_path
    )
    with pytest.raises(ProviderFailed, match="can't read a folder"):
        asyncio.run(ChatModelProvider(tmp_path, None).answer(call))  # type: ignore[arg-type]
