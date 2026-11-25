from __future__ import annotations

import json
from pathlib import Path

import pytest

from hiro_commons import log as core_log
from hiro_commons import logging_foundation as foundation
from hiro_commons.log import Logger
from hiro_commons.logging_foundation import daily
from hiro_commons.env_file import EnvFileError, load_env_file, parse_env_text
from hiro_commons.systemd_service import render_env_file


@pytest.fixture
def logged(tmp_path, monkeypatch):
    """The core's logger writing to a folder of this test's own; returns a reader of its lines."""
    monkeypatch.delenv(foundation.LEVELS_SETTING, raising=False)
    saved = (Logger._level, dict(core_log._MODULE_OVERRIDES))
    folder = tmp_path / "logs"
    Logger.start(folder, name="server", service="core", console=False)

    def lines() -> list[dict]:
        foundation.flush()
        found = []
        for _day, path in daily.files(folder, "server"):
            found += [json.loads(t) for t in path.read_text(encoding="utf-8").splitlines()]
        return found

    yield lines
    Logger.close()
    Logger._level = saved[0]
    core_log._MODULE_OVERRIDES.clear()
    core_log._MODULE_OVERRIDES.update(saved[1])


def test_parse_reads_name_value_lines_and_skips_comments() -> None:
    values, bad = parse_env_text("# a comment\n\nOPENAI_API_KEY=sk-1\n  GOOGLE_API_KEY = g-2 \n# ANTHROPIC_API_KEY=\n")
    assert values == {"OPENAI_API_KEY": "sk-1", "GOOGLE_API_KEY": "g-2"}
    assert bad == []


def test_parse_keeps_a_value_whole_and_reports_bad_lines_by_number() -> None:
    values, bad = parse_env_text('KEY=a=b"c\nnot a line\n1BAD=x\nOK=1\n')
    assert values == {"KEY": 'a=b"c', "OK": "1"}
    assert bad == [2, 3]


def test_the_template_the_install_writes_sets_nothing() -> None:
    text = render_env_file(
        service_name="hiro", user="NT SERVICE\\hiro", restart_command="Restart-Service hiro",
        sections=[("Provider API keys", ["OPENAI_API_KEY"])],
        reader_line="# Secrets for the HiroLeague service 'hiro'.", access_line="# Only administrators.",
    )
    assert text.splitlines()[:2] == ["# Secrets for the HiroLeague service 'hiro'.", "# Only administrators."]
    assert parse_env_text(text) == ({}, [])


def test_load_sets_missing_names_only_and_skips_empty_values(tmp_path: Path) -> None:
    path = tmp_path / "hiro.env"
    path.write_text("\ufeffOPENAI_API_KEY=sk-1\nPATH=C:\\evil\nGOOGLE_API_KEY=\n", encoding="utf-8")  # BOM from Notepad
    environ = {"PATH": "C:\\Windows"}

    loaded = load_env_file(path, environ=environ)

    assert loaded == ["OPENAI_API_KEY"]
    assert environ == {"PATH": "C:\\Windows", "OPENAI_API_KEY": "sk-1"}


def test_load_warns_about_bad_lines_without_their_text(tmp_path: Path, logged) -> None:
    path = tmp_path / "hiro.env"
    path.write_text("sk-this-is-a-pasted-key\nOK=1\n", encoding="utf-8")

    load_env_file(path, environ={})

    (warning,) = [line for line in logged() if line["SeverityText"] == "WARNING"]
    assert "not NAME=value" in warning["Body"]
    assert warning["Attributes"]["lines"] == [1]
    assert "sk-this-is-a-pasted-key" not in json.dumps(logged())


def test_a_missing_file_says_what_to_do(tmp_path: Path) -> None:
    with pytest.raises(EnvFileError, match="is missing") as info:
        load_env_file(tmp_path / "gone.env", environ={})
    assert "hiro service install" in str(info.value)
