"""Tests for bundled LLM catalog loading and queries."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import pytest
import yaml

from hirocli.domain.model_catalog import (
    ModelCatalog,
    clear_model_catalog_cache,
    get_model_catalog,
    reload_model_catalog,
)


@pytest.fixture(autouse=True)
def _clear_catalog_cache() -> None:
    clear_model_catalog_cache()
    yield
    clear_model_catalog_cache()


def test_bundled_catalog_loads() -> None:
    root = resources.files("hirocli.catalog_data")
    raw_doc = yaml.safe_load(root.joinpath("catalog.yaml").read_text(encoding="utf-8"))
    expected_version = str(raw_doc["catalog_version"]).strip()
    cat = get_model_catalog()
    assert cat.catalog_version == expected_version
    assert cat.get_provider("openai") is not None
    assert cat.get_model("openai:gpt-5.4") is not None
    assert cat.get_model("openai:gpt-5.5") is not None
    assert cat.get_model("openai:gpt-image-2") is not None
    openai = cat.get_provider("openai")
    assert openai is not None and len(openai.tts_voices) >= 10
    assert cat.get_model("openai:tts-1") is not None
    assert cat.get_model("openai:tts-1-hd") is not None
    google = cat.get_provider("google")
    assert google is not None and len(google.tts_voices) >= 25
    assert any(v.id == "Kore" for v in google.tts_voices)
    for mid in (
        "google:gemini-3-flash-preview",
        "google:gemini-3.1-flash-lite-preview",
        "google:gemini-3.1-pro-preview",
        "google:gemini-3.1-flash-tts-preview",
        "google:gemini-2.5-flash-preview-tts",
        "google:gemini-2.5-pro-preview-tts",
    ):
        assert cat.get_model(mid) is not None

    g3 = cat.get_model("google:gemini-3-flash-preview")
    assert g3 is not None
    assert g3.supports_kind("chat")
    assert g3.supports_kind("stt")
    assert cat.list_models(model_kind="stt")
    assert any(m.id == "google:gemini-3-flash-preview" for m in cat.list_models(model_kind="stt"))

    voyage_rr = cat.get_model("voyage:rerank-2.5")
    assert voyage_rr is not None and voyage_rr.pricing is not None
    assert voyage_rr.pricing.per_1k_tokens == 0.00005
    assert voyage_rr.pricing.input_per_1m_tokens == 0.05
    assert voyage_rr.pricing.estimated_usd_per_request == 0.0025

    cohere_rr = cat.get_model("cohere:rerank-v4.0-pro")
    assert cohere_rr is not None and cohere_rr.pricing is not None
    assert cohere_rr.pricing.estimated_usd_per_1k_searches == 2.50

    voyage = cat.get_provider("voyage")
    assert voyage is not None and len(voyage.free_offers) == 1
    assert voyage.free_offers[0].label == "Free rerank"
    assert "200" in voyage.free_offers[0].summary
    assert voyage.free_offers[0].updated_at == "2026-05-30"
    assert voyage.free_offers[0].details_url is not None

    cohere = cat.get_provider("cohere")
    assert cohere is not None and len(cohere.free_offers) == 1
    assert cohere.free_offers[0].label == "Trial API"
    assert cohere.free_offers[0].updated_at == "2026-05-30"
    assert "1,000" in cohere.free_offers[0].summary
    assert "10 req/min" in cohere.free_offers[0].summary
    assert cohere.free_offers[0].details_url == "https://docs.cohere.com/docs/rate-limits"


def test_clear_cache_is_robust_when_get_model_catalog_is_monkeypatched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``clear_model_catalog_cache`` must not raise when ``get_model_catalog`` is a plain function.

    Regression for a cross-suite ordering bug: registering an eval test module as a plugin
    (``pytest_plugins = ["...test_retrieval_shim"]``) promotes its autouse ``monkeypatch``-dependent
    fixture to session scope. That reorders ``monkeypatch`` ahead of another module's autouse
    cache-clear fixture, so the teardown calls ``clear_model_catalog_cache()`` while
    ``get_model_catalog`` is still the patched lambda (no ``cache_clear``). The clear must no-op
    rather than ``AttributeError``.
    """
    import hirocli.domain.model_catalog as mc

    sentinel = get_model_catalog()
    monkeypatch.setattr(mc, "get_model_catalog", lambda: sentinel)
    assert not hasattr(mc.get_model_catalog, "cache_clear")
    # Must not raise even though the patched function has no LRU cache to clear.
    clear_model_catalog_cache()


def test_reload_model_catalog_refreshes_process_cache() -> None:
    """``reload_model_catalog`` must clear LRU cache so a new singleton is loaded."""
    first = get_model_catalog()
    reloaded = reload_model_catalog()
    again = get_model_catalog()
    assert reloaded is again
    assert reloaded.catalog_version == first.catalog_version


def test_list_models_filter_hosting() -> None:
    cat = get_model_catalog()
    cloud = cat.list_models(hosting="cloud")
    local = cat.list_models(hosting="local")
    assert all(
        cat.get_provider(m.provider_id) and cat.get_provider(m.provider_id).hosting == "cloud"
        for m in cloud
    )
    assert all(
        cat.get_provider(m.provider_id) and cat.get_provider(m.provider_id).hosting == "local"
        for m in local
    )
    assert len(cloud) > 0 and len(local) > 0


def test_list_credential_env_keys_unique_sorted() -> None:
    cat = get_model_catalog()
    keys = cat.list_credential_env_keys()
    assert keys == sorted(set(keys))
    assert "OPENAI_API_KEY" in keys


def test_validate_model_ids_buckets(tmp_path: Path) -> None:
    doc = {
        "catalog_version": "99.0.0",
        "providers": [
            {
                "id": "p1",
                "display_name": "P1",
                "hosting": "cloud",
                "credential_env_keys": ["K1"],
                "metadata_updated_at": "2026-01-01",
            }
        ],
        "models": [
            {
                "id": "p1:old",
                "provider_id": "p1",
                "display_name": "Old",
                "model_kind": "chat",
                "deprecated_since": "2026-01-01",
                "replacement_id": "p1:new",
            },
            {
                "id": "p1:new",
                "provider_id": "p1",
                "display_name": "New",
                "model_kind": "chat",
            },
        ],
    }
    path = tmp_path / "cat.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    cat = ModelCatalog.load_from_path(path)
    vr = cat.validate_model_ids(["p1:new", "p1:old", "missing:foo"])
    assert vr.known == ["p1:new"]
    assert vr.unknown == ["missing:foo"]
    assert len(vr.deprecated) == 1
    assert vr.deprecated[0].model_id == "p1:old"
    assert vr.deprecated[0].replacement_id == "p1:new"


def test_estimate_token_usage_cost_uses_catalog_pricing(tmp_path: Path) -> None:
    doc = {
        "catalog_version": "1.0.0",
        "providers": [
            {
                "id": "p1",
                "display_name": "P1",
                "hosting": "cloud",
                "credential_env_keys": [],
                "metadata_updated_at": "2026-01-01",
            }
        ],
        "models": [
            {
                "id": "p1:chat",
                "provider_id": "p1",
                "display_name": "Chat",
                "model_kind": "chat",
                "pricing": {
                    "input_per_1m_tokens": 2.0,
                    "cached_input_per_1m_tokens": 0.5,
                    "output_per_1m_tokens": 10.0,
                    "pricing_updated_at": "2026-01-01",
                },
            },
        ],
    }
    path = tmp_path / "cat.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    cat = ModelCatalog.load_from_path(path)

    estimate = cat.estimate_token_usage_cost(
        model_id="p1:chat",
        input_tokens=1_000,
        cached_input_tokens=250,
        output_tokens=2_000,
    )

    assert estimate.currency == "USD"
    assert estimate.pricing_available is True
    assert estimate.estimated_total == pytest.approx(0.021625)
    assert estimate.reason is None


def test_pricing_version_is_stable_and_changes_with_pricing(tmp_path: Path) -> None:
    base_doc = {
        "catalog_version": "1.0.0",
        "providers": [
            {
                "id": "p1",
                "display_name": "P1",
                "hosting": "cloud",
                "credential_env_keys": [],
                "metadata_updated_at": "2026-01-01",
            }
        ],
        "models": [
            {
                "id": "p1:chat",
                "provider_id": "p1",
                "display_name": "Chat",
                "model_kind": "chat",
                "pricing": {
                    "input_per_1m_tokens": 2.0,
                    "output_per_1m_tokens": 10.0,
                    "pricing_updated_at": "2026-01-01",
                },
            },
        ],
    }
    path = tmp_path / "cat.yaml"
    path.write_text(yaml.safe_dump(base_doc), encoding="utf-8")
    first = ModelCatalog.load_from_path(path)
    second = ModelCatalog.load_from_path(path)

    changed_doc = dict(base_doc)
    changed_doc["models"] = [dict(base_doc["models"][0])]
    changed_doc["models"][0]["pricing"] = dict(base_doc["models"][0]["pricing"])
    changed_doc["models"][0]["pricing"]["input_per_1m_tokens"] = 3.0
    path.write_text(yaml.safe_dump(changed_doc), encoding="utf-8")
    changed = ModelCatalog.load_from_path(path)

    assert first.pricing_version == second.pricing_version
    assert first.pricing_version != changed.pricing_version


def test_gemini_3_flash_preview_cost_uses_cached_input_rate() -> None:
    cat = get_model_catalog()

    first = cat.estimate_token_usage_cost(
        model_id="google:gemini-3-flash-preview",
        input_tokens=7_466,
        cached_input_tokens=5_931,
        output_tokens=73,
    )
    second = cat.estimate_token_usage_cost(
        model_id="google:gemini-3-flash-preview",
        input_tokens=7_750,
        cached_input_tokens=5_931,
        output_tokens=88,
    )

    assert first.pricing_available is True
    assert first.estimated_total == pytest.approx(0.00128305)
    assert second.estimated_total == pytest.approx(0.00147005)
    assert first.estimated_total + second.estimated_total == pytest.approx(0.0027531)


def test_estimate_tts_usage_cost_openai_character_priced() -> None:
    cat = get_model_catalog()

    estimate = cat.estimate_tts_usage_cost(
        provider_id="openai",
        model_id="tts-1",
        input_characters=1_000,
    )

    assert estimate.currency == "USD"
    assert estimate.pricing_available is True
    assert estimate.estimated_total == pytest.approx(0.015)


def test_estimate_tts_usage_cost_openai_mini_uses_tokens_and_audio_seconds() -> None:
    cat = get_model_catalog()

    estimate = cat.estimate_tts_usage_cost(
        provider_id="openai",
        model_id="gpt-4o-mini-tts",
        input_text_tokens=250,
        generated_audio_seconds=48,
    )

    assert estimate.pricing_available is True
    assert estimate.estimated_total == pytest.approx(0.01215)


def test_estimate_tts_usage_cost_gemini_uses_text_and_audio_tokens() -> None:
    cat = get_model_catalog()

    estimate = cat.estimate_tts_usage_cost(
        provider_id="gemini",
        model_id="gemini-3.1-flash-tts-preview",
        input_text_tokens=100,
        output_audio_tokens=200,
    )

    assert estimate.pricing_available is True
    assert estimate.estimated_total == pytest.approx(0.0041)


def test_estimate_tts_usage_cost_unsupported_provider_is_unpriced() -> None:
    cat = get_model_catalog()

    estimate = cat.estimate_tts_usage_cost(
        provider_id="other",
        model_id="voice",
        input_characters=1_000,
    )

    assert estimate.pricing_available is False
    assert estimate.estimated_total == 0
    assert estimate.reason == "unsupported_tts_provider"


def test_estimate_token_usage_cost_reports_missing_pricing(tmp_path: Path) -> None:
    doc = {
        "catalog_version": "1.0.0",
        "providers": [
            {
                "id": "p1",
                "display_name": "P1",
                "hosting": "cloud",
                "credential_env_keys": [],
                "metadata_updated_at": "2026-01-01",
            }
        ],
        "models": [
            {
                "id": "p1:chat",
                "provider_id": "p1",
                "display_name": "Chat",
                "model_kind": "chat",
            },
        ],
    }
    path = tmp_path / "cat.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    cat = ModelCatalog.load_from_path(path)

    estimate = cat.estimate_token_usage_cost(model_id="p1:chat", input_tokens=1)

    assert estimate.currency == "USD"
    assert estimate.estimated_total == 0
    assert estimate.pricing_available is False
    assert estimate.reason == "pricing_missing"


def test_invalid_provider_reference_rejected(tmp_path: Path) -> None:
    doc = {
        "catalog_version": "1.0.0",
        "providers": [
            {
                "id": "only",
                "display_name": "Only",
                "hosting": "cloud",
                "credential_env_keys": [],
                "metadata_updated_at": "2026-01-01",
            }
        ],
        "models": [
            {
                "id": "other:bad",
                "provider_id": "other",
                "display_name": "Bad",
                "model_kind": "chat",
            }
        ],
    }
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown provider_id"):
        ModelCatalog.load_from_path(path)


def test_model_id_must_match_provider_prefix(tmp_path: Path) -> None:
    doc = {
        "catalog_version": "1.0.0",
        "providers": [
            {
                "id": "openai",
                "display_name": "OpenAI",
                "hosting": "cloud",
                "credential_env_keys": [],
                "metadata_updated_at": "2026-01-01",
            }
        ],
        "models": [
            {
                "id": "wrong:gpt-4",
                "provider_id": "openai",
                "display_name": "X",
                "model_kind": "chat",
            }
        ],
    }
    path = tmp_path / "prefix.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="must start with provider prefix"):
        ModelCatalog.load_from_path(path)


def test_recommended_models_validated(tmp_path: Path) -> None:
    doc = {
        "catalog_version": "1.0.0",
        "providers": [
            {
                "id": "other",
                "display_name": "Other",
                "hosting": "cloud",
                "credential_env_keys": [],
                "metadata_updated_at": "2026-01-01",
            },
            {
                "id": "p",
                "display_name": "P",
                "hosting": "cloud",
                "credential_env_keys": [],
                "metadata_updated_at": "2026-01-01",
                "recommended_models": {"chat": "other:x"},
            },
        ],
        "models": [
            {
                "id": "other:x",
                "provider_id": "other",
                "display_name": "X",
                "model_kind": "chat",
            },
            {
                "id": "p:y",
                "provider_id": "p",
                "display_name": "Y",
                "model_kind": "chat",
            },
        ],
    }
    path = tmp_path / "rec.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="belongs to provider"):
        ModelCatalog.load_from_path(path)


def test_recommended_models_wrong_kind(tmp_path: Path) -> None:
    doc = {
        "catalog_version": "1.0.0",
        "providers": [
            {
                "id": "p",
                "display_name": "P",
                "hosting": "cloud",
                "credential_env_keys": [],
                "metadata_updated_at": "2026-01-01",
                "recommended_models": {"chat": "p:tts1"},
            }
        ],
        "models": [
            {
                "id": "p:tts1",
                "provider_id": "p",
                "display_name": "T",
                "model_kind": "tts",
            },
        ],
    }
    path = tmp_path / "rec2.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="does not support kind"):
        ModelCatalog.load_from_path(path)


def test_suggested_defaults_empty_and_populated(tmp_path: Path) -> None:
    doc = {
        "catalog_version": "1.0.0",
        "providers": [
            {
                "id": "p",
                "display_name": "P",
                "hosting": "cloud",
                "credential_env_keys": [],
                "metadata_updated_at": "2026-01-01",
                "recommended_models": {"chat": "p:one"},
            }
        ],
        "models": [
            {
                "id": "p:one",
                "provider_id": "p",
                "display_name": "One",
                "model_kind": "chat",
            },
        ],
    }
    path = tmp_path / "sd.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    cat = ModelCatalog.load_from_path(path)
    assert cat.suggested_defaults("missing") == {}
    assert cat.suggested_defaults("p") == {"chat": "p:one"}


def test_replacement_id_must_exist(tmp_path: Path) -> None:
    doc = {
        "catalog_version": "1.0.0",
        "providers": [
            {
                "id": "p",
                "display_name": "P",
                "hosting": "cloud",
                "credential_env_keys": [],
                "metadata_updated_at": "2026-01-01",
            }
        ],
        "models": [
            {
                "id": "p:old",
                "provider_id": "p",
                "display_name": "Old",
                "model_kind": "chat",
                "deprecated_since": "2026-01-01",
                "replacement_id": "p:missing",
            },
        ],
    }
    path = tmp_path / "repl.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="replacement_id"):
        ModelCatalog.load_from_path(path)


def test_recommended_models_accepts_extra_kinds_stt(tmp_path: Path) -> None:
    doc = {
        "catalog_version": "1.0.0",
        "providers": [
            {
                "id": "p",
                "display_name": "P",
                "hosting": "cloud",
                "credential_env_keys": [],
                "metadata_updated_at": "2026-01-01",
                "recommended_models": {"chat": "p:chatstt", "stt": "p:chatstt"},
            },
        ],
        "models": [
            {
                "id": "p:chatstt",
                "provider_id": "p",
                "display_name": "Both",
                "model_kind": "chat",
                "extra_kinds": ["stt"],
            },
        ],
    }
    path = tmp_path / "rec_stt.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    cat = ModelCatalog.load_from_path(path)
    spec = cat.get_model("p:chatstt")
    assert spec is not None
    assert spec.supports_kind("stt")


def test_extra_kinds_must_not_repeat_primary(tmp_path: Path) -> None:
    doc = {
        "catalog_version": "1.0.0",
        "providers": [
            {
                "id": "p",
                "display_name": "P",
                "hosting": "cloud",
                "credential_env_keys": [],
                "metadata_updated_at": "2026-01-01",
            },
        ],
        "models": [
            {
                "id": "p:x",
                "provider_id": "p",
                "display_name": "X",
                "model_kind": "chat",
                "extra_kinds": ["chat"],
            },
        ],
    }
    path = tmp_path / "dup_primary.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="extra_kinds must not repeat"):
        ModelCatalog.load_from_path(path)
