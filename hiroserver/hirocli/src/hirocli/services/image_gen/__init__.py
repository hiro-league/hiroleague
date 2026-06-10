"""Image-generation provider package.

Public API
----------
    ImageGenProvider           — ABC for all image-gen providers
    ImageGenModelInfo          — dataclass describing a single model
    ImageGenResult             — dataclass carrying output (image bytes, MIME, metadata)
    ImageGenService            — orchestrator aggregating providers, routed by model id
    CloudflareImageGenProvider — Cloudflare Workers AI (FLUX.1 [schnell])
    create_image_gen_service   — factory building an ImageGenService from workspace preferences
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hiro_commons.log import Logger

from .cloudflare_provider import CloudflareImageGenProvider
from .provider import ImageGenModelInfo, ImageGenProvider, ImageGenResult
from .service import ImageGenService

if TYPE_CHECKING:
    from hirocli.domain.preferences import WorkspacePreferences

__all__ = [
    "ImageGenProvider",
    "ImageGenModelInfo",
    "ImageGenResult",
    "ImageGenService",
    "CloudflareImageGenProvider",
    "IMPLEMENTED_IMAGE_GEN_PROVIDERS",
    "create_image_gen_service",
]

_log = Logger.get("IMAGEGEN")

# Catalog provider ids with an actual ImageGenProvider implementation. The catalog may
# carry image_gen models from other vendors (e.g. openai:gpt-image-2) before we implement
# them — UIs must not offer those for generation.
IMPLEMENTED_IMAGE_GEN_PROVIDERS: frozenset[str] = frozenset({"cloudflare"})


def create_image_gen_service(
    workspace_path: Path,
    *,
    prefs: "WorkspacePreferences | None" = None,
) -> ImageGenService | None:
    """Build an ImageGenService from workspace credentials and catalog availability.

    Resolves the default model from ``preferences.llm.default_image_gen`` through the
    catalog and credential store — same pattern as ``create_tts_service``. Cloudflare
    needs both the API token (keyring) and the account id (providers.json metadata).
    """
    from hirocli.domain.credential_store import CredentialStore
    from hirocli.domain.model_catalog import get_model_catalog
    from hirocli.domain.preferences import load_preferences
    from hirocli.domain.workspace import workspace_id_for_path

    prefs = prefs or load_preferences(workspace_path)

    wid = workspace_id_for_path(workspace_path)
    if wid is None:
        _log.warning(
            "Image gen requested but workspace is not in registry — cannot build credential store"
        )
        return None
    store = CredentialStore(workspace_path, wid)

    cat = get_model_catalog()
    providers: list[ImageGenProvider] = []
    if store.is_configured("cloudflare") and any(
        m.supports_kind("image_gen") for m in cat.list_models(provider_id="cloudflare")
    ):
        inst = CloudflareImageGenProvider(
            api_token=store.get_api_key("cloudflare"),
            account_id=store.get_account_id("cloudflare"),
        )
        if inst.is_available():
            providers.append(inst)
        else:
            # Configured but unusable — most likely the account id is missing.
            _log.warning(
                "⚠️ Cloudflare configured but image gen unavailable — check API token AND account id"
            )

    default_model: str | None = None
    model_id = prefs.llm.default_image_gen
    if model_id:
        spec = cat.get_model(model_id)
        if spec is None:
            _log.warning("Image-gen model id not in catalog", model_id=model_id)
        else:
            default_model = model_id.split(":", 1)[1]

    if not providers:
        _log.warning(
            "Image gen requested but no providers loaded (add cloudflare credentials first)"
        )
        return None

    return ImageGenService(providers=providers, default_model=default_model)
