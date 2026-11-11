"""Writing files (files.py): atomic. (That nothing writes a file any other way is each app's own test.)"""

import os

import pytest

from hiro_extension_kit import files


def test_writes_the_file_and_makes_its_folder(tmp_path):
    target = tmp_path / "a" / "b" / "state.json"
    files.write_text(target, '{"hold": true}')
    assert target.read_text() == '{"hold": true}'
    assert list(target.parent.iterdir()) == [target]  # no temporary file left behind


def test_replaces_an_existing_file(tmp_path):
    target = tmp_path / "clip.ogg"
    files.write_bytes(target, b"old")
    files.write_bytes(target, b"new")
    assert target.read_bytes() == b"new"


def test_a_failed_write_keeps_the_old_file_whole(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    files.write_text(target, "old")

    def crash(*_args):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", crash)
    with pytest.raises(OSError, match="disk full"):
        files.write_text(target, "new")
    assert target.read_text() == "old"
    assert list(tmp_path.iterdir()) == [target]
