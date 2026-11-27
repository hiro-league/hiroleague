"""The front door's Linux setup makes sure avahi is there: without it a fresh Ubuntu announces no name on the LAN."""

from __future__ import annotations

import logging
import subprocess

import pytest

from hirocli import front_door_setup as door


class _Apt:
    """Stands in for apt-get: records each call, answers with the exit code given for its first word."""

    def __init__(self, codes: dict[str, int] | None = None) -> None:
        self.calls: list[tuple[list[str], str]] = []
        self.codes = codes or {}

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw["env"].get("DEBIAN_FRONTEND", "")))
        code = self.codes.get(cmd[1], 0)
        return subprocess.CompletedProcess(cmd, code, "", "E: Could not get lock /var/lib/dpkg/lock-frontend" if code else "")


def _system(monkeypatch: pytest.MonkeyPatch, *programs: str, apt: _Apt) -> None:
    monkeypatch.setattr(door.shutil, "which", lambda name: f"/usr/bin/{name}" if name in programs else None)
    monkeypatch.setattr(door.subprocess, "run", apt)


def test_avahi_there_already_installs_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    apt = _Apt()
    _system(monkeypatch, "avahi-publish", "apt-get", apt=apt)
    assert door.ensure_avahi() == "avahi (announces each name on the LAN)"
    assert apt.calls == []


def test_a_fresh_ubuntu_gets_avahi_from_apt_without_a_question(monkeypatch: pytest.MonkeyPatch) -> None:
    apt = _Apt()
    _system(monkeypatch, "apt-get", apt=apt)
    assert door.ensure_avahi() == "avahi (installed now; announces each name on the LAN)"
    assert apt.calls == [(["apt-get", "update"], "noninteractive"),
                         (["apt-get", "install", "-y", "avahi-daemon", "avahi-utils"], "noninteractive")]


def test_apt_failing_never_fails_the_install_and_says_what_to_do(monkeypatch: pytest.MonkeyPatch,
                                                                 caplog: pytest.LogCaptureFixture) -> None:
    _system(monkeypatch, "apt-get", apt=_Apt({"install": 100}))
    caplog.set_level(logging.WARNING)
    said = door.ensure_avahi()
    assert said.startswith("avahi isn't installed") and "avahi-daemon and avahi-utils" in said
    warned = [r for r in caplog.records if "avahi couldn't be installed" in r.getMessage()]
    assert warned and warned[0].levelno == logging.WARNING


def test_no_apt_says_what_to_install(monkeypatch: pytest.MonkeyPatch) -> None:
    apt = _Apt()
    _system(monkeypatch, apt=apt)
    assert door.ensure_avahi().startswith("avahi isn't installed")
    assert apt.calls == []
