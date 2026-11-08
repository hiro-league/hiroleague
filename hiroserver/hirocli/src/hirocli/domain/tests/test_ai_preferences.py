"""Phase 7a: AI profiles and uses in preferences — what a write accepts and refuses."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from hirocli.domain.preferences import AiPreferences, AiProfile, WorkspacePreferences, ai_fallback_chain
from hirocli.runtime.preferences_runtime import WorkspacePreferencesRuntime

API_MODEL = "google:gemini-3.8-flash"


def _profile(model: str = API_MODEL, fallback: str | None = None, **extra: Any) -> dict[str, Any]:
    return {"label": "P", "model": model, "fallback": fallback, **extra}


def test_profile_models_api_must_be_catalog_chat_local_and_plan_by_form() -> None:
    assert AiProfile(label="Camera", model=API_MODEL).model == API_MODEL
    # Local servers report their own models: any name passes (the server can be off while loading).
    assert AiProfile(label="Local", model="lm_studio:qwen3-vl-8b").model == "lm_studio:qwen3-vl-8b"
    assert AiProfile(label="Ollama", model="ollama:gemma4:e4b").model == "ollama:gemma4:e4b"
    # Plan tools name the model as the tool reports it.
    assert AiProfile(label="Plan", model="claude_code:claude-sonnet-5-5").model.startswith("claude_code:")
    for bad in ("google:no-such-model", "nobody:model", "no-colon", "openai:", "openai:text-embedding-3-small"):
        with pytest.raises(ValidationError):
            AiProfile(label="Bad", model=bad)


def test_profile_field_bounds() -> None:
    with pytest.raises(ValidationError):
        AiProfile(label="", model=API_MODEL)
    with pytest.raises(ValidationError):
        AiProfile(label="x" * 81, model=API_MODEL)
    with pytest.raises(ValidationError):
        AiProfile(label="P", model=API_MODEL, at_once=5)
    with pytest.raises(ValidationError):
        AiProfile(label="P", model=API_MODEL, temperature=2.5)
    assert AiProfile(label="P", model=API_MODEL, fallback="  ").fallback is None


def test_fallbacks_must_exist_never_loop_and_stay_within_three() -> None:
    ok = AiPreferences(
        profiles={
            "a": _profile(fallback="b"),
            "b": _profile(fallback="c"),
            "c": _profile(fallback="d"),
            "d": _profile(),
        }
    )
    assert ai_fallback_chain(ok.profiles, "a") == ["a", "b", "c", "d"]
    with pytest.raises(ValidationError, match="unknown profile"):
        AiPreferences(profiles={"a": _profile(fallback="zz")})
    with pytest.raises(ValidationError, match="itself"):
        AiPreferences(profiles={"a": _profile(fallback="a")})
    with pytest.raises(ValidationError, match="loop"):
        AiPreferences(profiles={"a": _profile(fallback="b"), "b": _profile(fallback="a")})
    with pytest.raises(ValidationError, match="more than 3"):
        AiPreferences(
            profiles={
                "a": _profile(fallback="b"),
                "b": _profile(fallback="c"),
                "c": _profile(fallback="d"),
                "d": _profile(fallback="e"),
                "e": _profile(),
            }
        )


def test_profile_ids_and_use_keys() -> None:
    with pytest.raises(ValidationError, match="lowercase"):
        AiPreferences(profiles={"Camera Questions": _profile()})
    with pytest.raises(ValidationError, match="unknown profile"):
        AiPreferences(profiles={"a": _profile()}, uses={"home:ask": "zz"})
    with pytest.raises(ValidationError, match="<extension>:<use id>"):
        AiPreferences(profiles={"a": _profile()}, uses={"home.ask": "a"})
    prefs = AiPreferences(profiles={"a": _profile()}, uses={"home:ask": "a", "home:sites": None})
    assert prefs.uses == {"home:ask": "a", "home:sites": None}


def test_profiles_and_uses_write_through_the_preferences_patch_paths(tmp_path: Path) -> None:
    runtime = WorkspacePreferencesRuntime(tmp_path, initial=WorkspacePreferences())
    runtime.update_many({"ai.profiles.camera": _profile(fallback=None, at_once=2)})
    runtime.update("ai.uses.home:ask", "camera")
    reloaded = WorkspacePreferencesRuntime(tmp_path).current
    assert reloaded.ai.profiles["camera"].at_once == 2
    assert reloaded.ai.uses == {"home:ask": "camera"}
    # A write that breaks a link is refused and nothing changes.
    with pytest.raises(ValidationError):
        runtime.update("ai.uses.home:sites", "missing")
    assert WorkspacePreferencesRuntime(tmp_path).current.ai.uses == {"home:ask": "camera"}
