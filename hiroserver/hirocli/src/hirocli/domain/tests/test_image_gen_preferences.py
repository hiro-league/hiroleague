"""Image-gen preferences: ImageProfile defaults, resolution chain, prompt composition,
and the credential store's account-id handling for cloudflare-style providers."""

from __future__ import annotations

from pathlib import Path

import pytest

from hirocli.domain.credential_store import CredentialStore
from hirocli.domain.preferences import (
    DEFAULT_IMAGE_PLAYGROUND_PROFILE_ID,
    ImageProfile,
    WorkspacePreferences,
    compose_image_prompt,
    resolve_image_gen,
)

_MODEL_ID = "cloudflare:flux-1-schnell"


@pytest.fixture()
def store(tmp_path: Path) -> CredentialStore:
    return CredentialStore(tmp_path, "ws-test", _test_secrets={})


def _prefs_with_default_model() -> WorkspacePreferences:
    prefs = WorkspacePreferences()
    prefs.llm.default_image_gen = _MODEL_ID
    return prefs


# ── profile schema ──────────────────────────────────────────────────────────


def test_playground_profile_seeded_and_locked() -> None:
    prefs = WorkspacePreferences()
    profile = prefs.image_profiles[DEFAULT_IMAGE_PLAYGROUND_PROFILE_ID]
    assert profile.locked
    assert profile.style_prefix == "" and profile.style_suffix == ""
    assert prefs.llm.default_image_profile == DEFAULT_IMAGE_PLAYGROUND_PROFILE_ID


def test_unknown_default_image_profile_rejected() -> None:
    prefs = WorkspacePreferences()
    data = prefs.model_dump(mode="python")
    data["llm"]["default_image_profile"] = "nope"
    with pytest.raises(ValueError, match="default_image_profile"):
        WorkspacePreferences.model_validate(data)


def test_seeded_profile_relocked_on_validation() -> None:
    prefs = WorkspacePreferences()
    data = prefs.model_dump(mode="python")
    data["image_profiles"][DEFAULT_IMAGE_PLAYGROUND_PROFILE_ID]["locked"] = False
    revalidated = WorkspacePreferences.model_validate(data)
    assert revalidated.image_profiles[DEFAULT_IMAGE_PLAYGROUND_PROFILE_ID].locked


# ── resolution chain ────────────────────────────────────────────────────────


def test_resolve_none_without_model_selection(tmp_path: Path, store: CredentialStore) -> None:
    assert resolve_image_gen(WorkspacePreferences(), tmp_path, credential_store=store) is None


def test_resolve_none_without_provider_credentials(
    tmp_path: Path, store: CredentialStore
) -> None:
    prefs = _prefs_with_default_model()
    assert resolve_image_gen(prefs, tmp_path, credential_store=store) is None


def test_resolve_profile_defaults_and_overrides(tmp_path: Path, store: CredentialStore) -> None:
    store.set_api_key("cloudflare", "tok", account_id="acct")
    prefs = _prefs_with_default_model()
    prefs.image_profiles["styled"] = ImageProfile(
        label="Styled",
        steps=6,
        style_prefix="warm tones",
        style_suffix="no text",
        seed=42,
    )

    resolved = resolve_image_gen(prefs, tmp_path, profile_id="styled", credential_store=store)
    assert resolved is not None
    assert resolved.model_id == _MODEL_ID  # profile.model None → llm.default_image_gen
    assert (resolved.steps, resolved.seed) == (6, 42)

    overridden = resolve_image_gen(
        prefs,
        tmp_path,
        profile_id="styled",
        steps_override=2,
        seed_override=7,
        credential_store=store,
    )
    assert overridden is not None
    assert (overridden.steps, overridden.seed) == (2, 7)

    assert compose_image_prompt(resolved, "a fox") == "warm tones, a fox, no text"


def test_resolve_unknown_profile_raises(tmp_path: Path, store: CredentialStore) -> None:
    with pytest.raises(ValueError, match="Unknown image profile"):
        resolve_image_gen(
            _prefs_with_default_model(), tmp_path, profile_id="nope", credential_store=store
        )


# ── credential store account id ─────────────────────────────────────────────


def test_set_api_key_requires_account_id_for_cloudflare(store: CredentialStore) -> None:
    with pytest.raises(ValueError, match="account id"):
        store.set_api_key("cloudflare", "tok")


def test_account_id_stored_and_kept_on_key_rotation(store: CredentialStore) -> None:
    store.set_api_key("cloudflare", "tok", account_id="acct")
    assert store.get_account_id("cloudflare") == "acct"
    # Rotating the key without re-passing the account id must not unset it.
    store.set_api_key("cloudflare", "tok2", account_id=None)
    assert store.get_account_id("cloudflare") == "acct"
    assert store.get_api_key("cloudflare") == "tok2"


def test_account_id_env_fallback(
    store: CredentialStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "env-acct")
    store.set_api_key("cloudflare", "tok")  # passes: env fallback satisfies the guard
    assert store.get_account_id("cloudflare") == "env-acct"


def test_account_id_not_required_for_simple_providers(store: CredentialStore) -> None:
    store.set_api_key("openai", "sk-test")
    assert store.get_account_id("openai") is None
