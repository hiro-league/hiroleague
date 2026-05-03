"""CharacterService tests with mocked tools."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from hirocli.admin.features.characters.service import CharacterService


def test_list_no_workspace() -> None:
    r = CharacterService().list_characters(None)
    assert not r.ok


def test_list_tool_error() -> None:
    with patch("hirocli.admin.features.characters.service.CharacterListTool") as T:
        T.return_value.execute.side_effect = RuntimeError("boom")
        r = CharacterService().list_characters("ws-1")
    assert not r.ok


def test_list_success() -> None:
    mock_r = MagicMock()
    mock_r.characters = [{"id": "hiro", "name": "Hiro"}]
    with patch("hirocli.admin.features.characters.service.CharacterListTool") as T:
        T.return_value.execute.return_value = mock_r
        r = CharacterService().list_characters("ws-1")
    assert r.ok and r.data and r.data[0]["id"] == "hiro"


def test_get_success() -> None:
    mock_r = MagicMock()
    mock_r.character = {"id": "kai", "name": "Kai"}
    with patch("hirocli.admin.features.characters.service.CharacterGetTool") as T:
        T.return_value.execute.return_value = mock_r
        r = CharacterService().get_character("ws-1", "kai")
    assert r.ok and r.data and r.data["name"] == "Kai"


def test_validate_json_array_invalid() -> None:
    r = CharacterService.validate_optional_json_array("x", "[1]")
    assert not r.ok


def test_validate_json_object_invalid() -> None:
    r = CharacterService.validate_optional_json_object("x", "[]")
    assert not r.ok


def test_get_resolved_configuration_requires_workspace() -> None:
    r = CharacterService().get_character_resolved_configuration(None, "hiro")
    assert not r.ok


def test_get_resolved_configuration_unknown_character() -> None:
    with patch("hirocli.admin.features.characters.service.CharacterGetTool") as T:
        T.return_value.execute.side_effect = FileNotFoundError("Unknown character id: nope")
        r = CharacterService().get_character_resolved_configuration("ws-1", "nope")
    assert not r.ok
