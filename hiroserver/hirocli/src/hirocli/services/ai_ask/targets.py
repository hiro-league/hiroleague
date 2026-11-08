"""What an AI profile's model is: its kind (api / local / plan), provider, and what it can take.

Resolution order for ``provider:model``:

- a plan provider (``claude_code`` / ``codex``) → kind "plan", answered by a registered plan tool
  (``providers.register_plan_tool``; Part B);
- a catalog provider hosted ``local`` (``lm_studio`` / ``ollama``) → kind "local": the catalog row
  when there is one, else the model as the server last reported it (``domain.discovered_models``),
  else a bare row (the server may have it even though it wasn't checked yet: the ask tells);
- any other catalog provider → kind "api", which needs the catalog chat row.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ...domain.credential_store import CredentialStore
from ...domain.discovered_models import DiscoveredModel, discovered_model_spec, get_discovered_model
from ...domain.model_catalog import ModelSpec, get_model_catalog
from ...domain.preferences import AI_PLAN_PROVIDERS

AskKind = Literal["api", "local", "plan"]

PLAN_PROVIDER_LABELS: dict[str, str] = {
    "claude_code": "Claude Code (your Claude plan)",
    "codex": "Codex (your ChatGPT plan)",
}
# Only Gemini takes a sound clip with the question (the contract's audio part).
SOUND_PROVIDERS: frozenset[str] = frozenset({"google"})


@dataclass(frozen=True)
class AskTarget:
    kind: AskKind
    provider_id: str
    provider_label: str
    model_id: str  # canonical provider:model
    model_name: str  # the part after "provider:"
    spec: ModelSpec | None  # None for plan tools
    pictures: bool  # takes pictures (unknown local models: assumed, the server tells)
    sound: bool
    not_ready: str | None  # why it can't be asked now (no key, no endpoint); None = ready


def resolve_target(
    workspace_path: Path,
    model_id: str,
    *,
    store: CredentialStore | None,
) -> AskTarget:
    """Resolve ``model_id``; raises ValueError for a model no profile may name."""
    provider_id, sep, name = model_id.partition(":")
    if not sep or not provider_id or not name:
        raise ValueError(f"model must be provider:model, got {model_id!r}")
    if provider_id in AI_PLAN_PROVIDERS:
        from .providers import plan_tool_for

        return AskTarget(
            kind="plan",
            provider_id=provider_id,
            provider_label=PLAN_PROVIDER_LABELS.get(provider_id, provider_id),
            model_id=model_id,
            model_name=name,
            spec=None,
            pictures=True,
            sound=False,
            not_ready=None if plan_tool_for(provider_id) is not None else "plan tools aren't set up yet",
        )
    cat = get_model_catalog()
    prov = cat.get_provider(provider_id)
    if prov is None:
        raise ValueError(f"unknown provider {provider_id!r}")
    configured = store is not None and store.is_configured(provider_id)
    if prov.hosting == "local":
        spec = cat.get_model(model_id)
        seen: DiscoveredModel | None = None
        if spec is None:
            seen = get_discovered_model(workspace_path, model_id)
            spec = discovered_model_spec(
                seen
                or DiscoveredModel(
                    provider_id=provider_id, name=name, display_name=name, vision=True, reasoning=False, loaded=False
                )
            )
        return AskTarget(
            kind="local",
            provider_id=provider_id,
            provider_label=prov.display_name,
            model_id=model_id,
            model_name=name,
            spec=spec,
            pictures=_takes_pictures(spec),
            sound=False,
            not_ready=None if configured else f"{prov.display_name} has no address set (Providers)",
        )
    spec = cat.get_model(model_id)
    if spec is None or not spec.supports_kind("chat"):
        raise ValueError(f"model {model_id!r} is not a catalog chat model")
    return AskTarget(
        kind="api",
        provider_id=provider_id,
        provider_label=prov.display_name,
        model_id=model_id,
        model_name=name,
        spec=spec,
        pictures=_takes_pictures(spec),
        sound=provider_id in SOUND_PROVIDERS and "audio_in" in spec.modalities,
        not_ready=None if configured else f"{prov.display_name} has no API key (Providers)",
    )


def _takes_pictures(spec: ModelSpec) -> bool:
    return any(m in ("image", "image_in") for m in spec.modalities)
