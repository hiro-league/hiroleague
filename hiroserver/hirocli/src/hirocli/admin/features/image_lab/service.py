"""Image Lab operations for the admin API.

Read-side options for the playground page (catalog image models, image profiles,
defaults, provider readiness). Generation itself goes through ``GenerateImageTool``
in the route (tools-first), not here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hirocli.admin.shared.result import Result
from hirocli.domain.credential_store import CredentialStore
from hirocli.domain.model_catalog import get_model_catalog
from hirocli.domain.preferences import load_preferences
from hirocli.domain.workspace import resolve_workspace


class ImageLabService:
    """Options payload for the Image Lab page of the selected workspace."""

    def options(self, workspace_id: str | None) -> Result[dict[str, Any]]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        try:
            entry, _ = resolve_workspace(workspace_id)
            workspace_path = Path(entry.path)
            store = CredentialStore(workspace_path, entry.id)
            prefs = load_preferences(workspace_path)
            cat = get_model_catalog()

            from hirocli.services.image_gen import IMPLEMENTED_IMAGE_GEN_PROVIDERS

            models: list[dict[str, Any]] = []
            for spec in cat.list_models(model_kind="image_gen"):
                # Catalog rows without a provider implementation (e.g. openai:gpt-image-2)
                # would fail at generation time — don't offer them in the Lab.
                if spec.provider_id not in IMPLEMENTED_IMAGE_GEN_PROVIDERS:
                    continue
                prov = cat.get_provider(spec.provider_id)
                configured = store.is_configured(spec.provider_id)
                # Cloudflare-style providers also need the account id to actually work.
                ready = configured and (
                    not (prov is not None and prov.requires_account_id)
                    or bool(store.get_account_id(spec.provider_id))
                )
                pricing = spec.pricing
                models.append(
                    {
                        "id": spec.id,
                        "display_name": spec.display_name,
                        "provider_id": spec.provider_id,
                        "provider_display_name": prov.display_name if prov else spec.provider_id,
                        "available": ready,
                        "configured": configured,
                        "notes": spec.notes,
                        "per_image": pricing.per_image if pricing else None,
                        "per_step": pricing.per_step if pricing else None,
                    }
                )

            profiles = {
                pid: profile.model_dump(mode="json")
                for pid, profile in sorted(prefs.image_profiles.items())
            }
            return Result.success(
                {
                    "models": models,
                    "profiles": profiles,
                    "default_profile": prefs.llm.default_image_profile,
                    "default_model": prefs.llm.default_image_gen,
                }
            )
        except Exception as exc:
            return Result.failure(str(exc))
