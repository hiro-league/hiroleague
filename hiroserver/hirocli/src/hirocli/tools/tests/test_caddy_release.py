"""The front door's program: one pinned Caddy release per system, its program taken out of the checked archive."""

from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from hiro_commons.fetch import FetchError
from hiro_commons.systemd_service import ServiceError
from hirocli import caddy_release as cr


def test_every_system_has_a_pinned_archive_of_the_same_release() -> None:
    assert set(cr.ARCHIVES) == {(s, m) for s in ("linux", "mac", "windows") for m in ("amd64", "arm64")}
    for (system, machine), (archive, sha256) in cr.ARCHIVES.items():
        assert archive == f"caddy_{cr.CADDY_VERSION}_{system}_{machine}.{'zip' if system == 'windows' else 'tar.gz'}"
        assert len(sha256) == 64 and int(sha256, 16) >= 0


def _fake_fetch(monkeypatch, make) -> list[str]:
    asked: list[str] = []

    def fetch(url: str, dest: Path, sha256: str) -> bool:
        asked.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        make(dest)
        return True

    monkeypatch.setattr(cr, "fetch_checked", fetch)
    return asked


def test_only_the_program_is_taken_out_of_a_windows_zip(tmp_path, monkeypatch) -> None:
    def make(dest: Path) -> None:
        with zipfile.ZipFile(dest, "w") as zf:
            zf.writestr("caddy.exe", b"MZ caddy")
            zf.writestr("README.md", b"not wanted")

    asked = _fake_fetch(monkeypatch, make)
    program = cr.fetch_caddy(tmp_path, "windows", "amd64")
    assert program == tmp_path / cr.CADDY_VERSION / "caddy.exe" and program.read_bytes() == b"MZ caddy"
    assert asked == [f"https://github.com/caddyserver/caddy/releases/download/v{cr.CADDY_VERSION}/"
                     f"caddy_{cr.CADDY_VERSION}_windows_amd64.zip"]
    assert sorted(p.name for p in program.parent.iterdir()) == ["caddy.exe", f"caddy_{cr.CADDY_VERSION}_windows_amd64.zip"]


def test_only_the_program_is_taken_out_of_a_linux_tarball(tmp_path, monkeypatch) -> None:
    def make(dest: Path) -> None:
        with tarfile.open(dest, "w:gz") as tf:
            for name, data in (("caddy", b"\x7fELF caddy"), ("LICENSE", b"Apache")):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))

    _fake_fetch(monkeypatch, make)
    program = cr.fetch_caddy(tmp_path, "linux", "amd64")
    assert program.read_bytes() == b"\x7fELF caddy"


def test_an_archive_without_the_program_or_a_system_without_one_is_refused(tmp_path, monkeypatch) -> None:
    def make(dest: Path) -> None:
        with zipfile.ZipFile(dest, "w") as zf:
            zf.writestr("other.exe", b"x")

    _fake_fetch(monkeypatch, make)
    with pytest.raises(ServiceError, match="Could not take Caddy out"):
        cr.fetch_caddy(tmp_path, "windows", "arm64")
    assert not (tmp_path / cr.CADDY_VERSION / "caddy.exe").exists()
    with pytest.raises(ServiceError, match="no front door for freebsd"):
        cr.fetch_caddy(tmp_path, "freebsd", "amd64")


def test_a_download_that_is_not_the_pinned_file_is_a_service_error(tmp_path, monkeypatch) -> None:
    def refuse(url: str, dest: Path, sha256: str) -> bool:
        raise FetchError("caddy.zip is not the file this version of Hiro League expects")

    monkeypatch.setattr(cr, "fetch_checked", refuse)
    with pytest.raises(ServiceError, match="not the file"):
        cr.fetch_caddy(tmp_path, "windows", "amd64")
