"""Build LangChain chat models from catalog ids + workspace credential store."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from langchain.chat_models import init_chat_model
from langchain_ollama import ChatOllama

from .credential_store import CredentialStore
from .model_catalog import get_model_catalog
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
    credential_store: CredentialStore | None = None,
) -> BaseChatModel:
    """Resolve ``provider:api_id`` to a chat model with credentials injected.

    Raises ``ValueError`` if the model is unknown, not a chat model, or the provider
    is not configured for this workspace.
    """
    cat = get_model_catalog()
    spec = cat.get_model(model_id)
    if spec is None:
        raise ValueError(f"Unknown model id: {model_id}")
    if spec.model_kind != "chat":
        raise ValueError(f"Model {model_id} is not a chat model (kind={spec.model_kind})")

    wid = workspace_id or workspace_id_for_path(workspace_path)
    if wid is None:
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

    if pid == "openai":
        key = store.get_api_key("openai")
        if not key:
            raise ValueError("OpenAI API key missing (keyring or OPENAI_API_KEY).")
        return init_chat_model(
            api_model,
            model_provider="openai",
            api_key=key,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    if pid == "anthropic":
        key = store.get_api_key("anthropic")
        if not key:
            raise ValueError("Anthropic API key missing (keyring or ANTHROPIC_API_KEY).")
        return init_chat_model(
            api_model,
            model_provider="anthropic",
            api_key=key,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    if pid == "google":
        key = store.get_api_key("google")
        if not key:
            raise ValueError("Google API key missing (keyring or GOOGLE_API_KEY).")
        return init_chat_model(
            api_model,
            model_provider="google_genai",
            google_api_key=key,
            temperature=temperature,
            max_output_tokens=max_tokens,
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
            temperature=temperature,
            num_predict=max_tokens,
        )

    raise ValueError(f"Model factory does not support provider {pid!r} yet.")
