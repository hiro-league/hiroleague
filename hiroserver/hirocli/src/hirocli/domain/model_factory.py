"""Build LangChain chat models from catalog ids + workspace credential store."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain.chat_models import init_chat_model
from langchain_ollama import ChatOllama

from .credential_store import CredentialStore
from .model_catalog import ModelSpec, get_model_catalog
from .preferences import ModelTuning, ThinkingLevel
from .workspace import workspace_id_for_path

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

logger = logging.getLogger(__name__)


def _api_model_id(canonical_id: str) -> str:
    parts = canonical_id.split(":", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Invalid canonical model id (expected provider:model): {canonical_id!r}")
    return parts[1]


def create_chat_model(
    model_id: str,
    *,
    workspace_path: Path,
    workspace_id: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 1024,
    thinking: ThinkingLevel | None = None,
    credential_store: CredentialStore | None = None,
    callbacks: list[Any] | None = None,
) -> BaseChatModel:
    """Resolve ``provider:api_id`` to a chat model with credentials injected.

    Raises ``ValueError`` if the model is unknown, not a chat model, or the provider
    is not configured for this workspace.
    """
    return build_chat_model_from_tuning(
        model_id,
        workspace_path=workspace_path,
        workspace_id=workspace_id,
        tuning=ModelTuning(
            temperature=temperature,
            max_tokens=max_tokens,
            thinking=thinking,
        ),
        credential_store=credential_store,
        callbacks=callbacks,
    )


def build_chat_model_from_tuning(
    model_id: str,
    *,
    workspace_path: Path,
    workspace_id: str | None = None,
    tuning: ModelTuning | None = None,
    credential_store: CredentialStore | None = None,
    callbacks: list[Any] | None = None,
) -> BaseChatModel:
    """Build a chat model and map provider-neutral tuning to provider kwargs."""
    cat = get_model_catalog()
    spec = cat.get_model(model_id)
    if spec is None:
        raise ValueError(f"Unknown model id: {model_id}")
    if spec.model_kind != "chat":
        raise ValueError(f"Model {model_id} is not a chat model (kind={spec.model_kind})")

    wid = workspace_id or workspace_id_for_path(workspace_path)
    if wid is None and credential_store is None:
        raise ValueError(
            "Workspace path is not registered; cannot resolve credential scope. "
            "Pass workspace_id explicitly or add this folder via hiro workspaces."
        )

    store = credential_store or CredentialStore(workspace_path, wid)
    if not store.is_configured(spec.provider_id):
        raise ValueError(
            f"Provider {spec.provider_id!r} is not configured for this workspace. "
            f"Run: hiro provider add {spec.provider_id}"
        )

    api_model = _api_model_id(model_id)
    pid = spec.provider_id
    effective = tuning or ModelTuning()
    cb = callbacks or []

    if pid == "openai":
        key = store.get_api_key("openai")
        if not key:
            raise ValueError("OpenAI API key missing (keyring or OPENAI_API_KEY).")
        kwargs: dict[str, Any] = {
            "model_provider": "openai",
            "api_key": key,
            "callbacks": cb,
        }
        if spec.supports_reasoning():
            kwargs["max_completion_tokens"] = effective.max_tokens
            effort = _openai_reasoning_effort(effective.thinking)
            if effort is not None:
                kwargs["reasoning_effort"] = effort
        else:
            kwargs["temperature"] = effective.temperature
            kwargs["max_tokens"] = effective.max_tokens
        return init_chat_model(
            api_model,
            **kwargs,
        )

    if pid == "anthropic":
        key = store.get_api_key("anthropic")
        if not key:
            raise ValueError("Anthropic API key missing (keyring or ANTHROPIC_API_KEY).")
        kwargs = {
            "model_provider": "anthropic",
            "api_key": key,
            "temperature": effective.temperature,
            "max_tokens": effective.max_tokens,
            "callbacks": cb,
        }
        thinking = _anthropic_thinking(effective.thinking, effective.max_tokens, spec)
        if thinking is not None:
            kwargs["thinking"] = thinking
        return init_chat_model(
            api_model,
            **kwargs,
        )

    if pid == "google":
        key = store.get_api_key("google")
        if not key:
            raise ValueError("Google API key missing (keyring or GOOGLE_API_KEY).")
        kwargs = {
            "model_provider": "google_genai",
            "google_api_key": key,
            "temperature": effective.temperature,
            "max_output_tokens": effective.max_tokens,
            "callbacks": cb,
        }
        kwargs.update(_google_thinking_kwargs(effective.thinking, api_model, spec))
        return init_chat_model(
            api_model,
            **kwargs,
        )

    if pid == "lm_studio":
        from langchain_openai import ChatOpenAI

        cred = store.get("lm_studio")
        base_url = getattr(cred, "base_url", None)
        if not base_url:
            raise ValueError("LM Studio base_url missing for chat model")
        return ChatOpenAI(
            model=api_model,
            base_url=base_url,
            api_key="lm-studio",
            temperature=effective.temperature,
            max_tokens=effective.max_tokens,
            callbacks=cb,
        )

    if pid == "ollama":
        cred = store.get("ollama")
        prov = cat.get_provider("ollama")
        base_url = (cred.base_url if cred and cred.base_url else None) or (
            prov.default_base_url if prov else None
        )
        if not base_url:
            raise ValueError(
                "Ollama base_url missing; run: hiro provider endpoint ollama http://localhost:11434"
            )
        logger.debug("Building ChatOllama — HiroServer · base_url=%s · model=%s", base_url, api_model)
        return ChatOllama(
            model=api_model,
            base_url=base_url,
            temperature=effective.temperature,
            num_predict=effective.max_tokens,
            callbacks=cb,
        )

    raise ValueError(f"Model factory does not support provider {pid!r} yet.")


def _openai_reasoning_effort(thinking: ThinkingLevel | None) -> str | None:
    if thinking in (None, "off"):
        return None
    return thinking


def _google_thinking_kwargs(
    thinking: ThinkingLevel | None,
    api_model: str,
    spec: ModelSpec,
) -> dict[str, Any]:
    if thinking is None or not spec.supports_reasoning():
        return {}
    lower = api_model.lower()
    if thinking == "off":
        return {"thinking_budget": 0}
    if lower.startswith("gemini-3"):
        return {"thinking_level": thinking}
    return {"thinking_budget": _thinking_budget_tokens(thinking)}


def _anthropic_thinking(
    thinking: ThinkingLevel | None,
    max_tokens: int,
    spec: ModelSpec,
) -> dict[str, Any] | None:
    if thinking in (None, "off") or not spec.supports_reasoning():
        return None
    return {
        "type": "enabled",
        "budget_tokens": min(max(_thinking_budget_tokens(thinking), 1024), max_tokens),
    }


def _thinking_budget_tokens(thinking: ThinkingLevel) -> int:
    return {
        "minimal": 256,
        "low": 1024,
        "medium": 4096,
        "high": 8192,
        "off": 0,
    }[thinking]
