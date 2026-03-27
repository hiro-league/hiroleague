"""Tests for character dual storage (disk + workspace.db index)."""

from __future__ import annotations

import sqlite3

from hiro_commons.constants.storage import CHARACTERS_DIR, DEFAULT_CHARACTER_ID

import pytest

from hirocli.domain.character import (
    CHARACTER_JSON_NAME,
    DEFAULT_PROMPT_TEXT,
    character_dir,
    create_character,
    delete_character,
    get_character_detail,
    load_character_from_disk,
    load_default_character_prompt,
    list_character_dirs,
    normalize_character_id,
    replace_character_photo,
    save_character_to_disk,
    save_default_character_prompt,
    seed_default_characters,
    update_character,
)
from hirocli.domain.db import db_path


def test_seed_creates_hiro_on_disk_and_db(tmp_path) -> None:
    seed_default_characters(tmp_path)
    hiro = character_dir(tmp_path, DEFAULT_CHARACTER_ID)
    assert (hiro / CHARACTER_JSON_NAME).is_file()
    assert (hiro / "prompt.md").is_file()
    assert (hiro / "backstory.md").is_file()
    assert (hiro / "photo.png").is_file()
    assert list_character_dirs(tmp_path) == [DEFAULT_CHARACTER_ID]

    with sqlite3.connect(str(db_path(tmp_path))) as conn:
        row = conn.execute(
            "SELECT id, name, is_default, folder_path FROM characters WHERE id = ?",
            (DEFAULT_CHARACTER_ID,),
        ).fetchone()
    assert row is not None
    assert row[0] == DEFAULT_CHARACTER_ID
    assert row[1] == "Hiro"
    assert row[2] == 1
    assert row[3] == f"{CHARACTERS_DIR}/{DEFAULT_CHARACTER_ID}"


def test_load_save_roundtrip(tmp_path) -> None:
    seed_default_characters(tmp_path)
    ch = load_character_from_disk(tmp_path, DEFAULT_CHARACTER_ID)
    ch.description = "Updated"
    ch.prompt = "Custom prompt body\n"
    save_character_to_disk(tmp_path, ch)
    ch2 = load_character_from_disk(tmp_path, DEFAULT_CHARACTER_ID)
    assert ch2.description == "Updated"
    assert ch2.prompt == "Custom prompt body\n"
    assert ch2.has_photo is True
    assert ch2.photo_filename == "photo.png"


def test_load_default_character_prompt_and_save(tmp_path) -> None:
    seed_default_characters(tmp_path)
    loaded = load_default_character_prompt(tmp_path).replace("\r\n", "\n")
    expected = DEFAULT_PROMPT_TEXT.strip().replace("\r\n", "\n")
    assert loaded == expected
    save_default_character_prompt(tmp_path, "  trimmed  ")
    assert load_default_character_prompt(tmp_path) == "trimmed"


def test_normalize_character_id_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        normalize_character_id("ab")
    with pytest.raises(ValueError):
        normalize_character_id("Bad_Case")
    assert normalize_character_id("Kai-1") == "kai-1"


def test_create_update_delete_roundtrip(tmp_path) -> None:
    seed_default_characters(tmp_path)
    create_character(tmp_path, "coach-1", "Coach", description="Test coach", prompt="Be brief.")
    d = get_character_detail(tmp_path, "coach-1")
    assert d["name"] == "Coach"
    assert d["description"] == "Test coach"
    assert "Be brief" in d["prompt"]

    update_character(tmp_path, "coach-1", description="Updated")
    d2 = get_character_detail(tmp_path, "coach-1")
    assert d2["description"] == "Updated"

    assert delete_character(tmp_path, "coach-1") is True
    assert delete_character(tmp_path, "coach-1") is False


def test_cannot_delete_default_character(tmp_path) -> None:
    seed_default_characters(tmp_path)
    with pytest.raises(ValueError, match="default"):
        delete_character(tmp_path, DEFAULT_CHARACTER_ID)


def test_replace_character_photo(tmp_path) -> None:
    seed_default_characters(tmp_path)
    src = character_dir(tmp_path, DEFAULT_CHARACTER_ID) / "photo.png"
    name = replace_character_photo(tmp_path, DEFAULT_CHARACTER_ID, src)
    assert name.startswith("photo.")
    d = get_character_detail(tmp_path, DEFAULT_CHARACTER_ID)
    assert d["has_photo"] is True
