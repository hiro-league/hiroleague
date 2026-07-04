"""Build LangChain chat models from catalog ids + workspace credential store."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain.chat_models import init_chat_model
from langchain.embeddings import init_embeddings
from langchain_ollama import ChatOllama

from .credential_store import CredentialStore
from .model_catalog import ModelCatalog, ModelSpec, get_model_catalog
from .model_http import openai_http_kwargs
from .preferences import ModelTuning, ThinkingLevel
from .workspace import workspace_id_for_path

if TYPE_CHECKING:
    from langchain_core.documents.compressor import BaseDocumentCompressor
    from langchain_core.embeddings import Embeddings
    from langchain_core.language_models.chat_models import BaseChatModel

logger = logging.getLogger(__name__)


def _http_keepalive_s(workspace_path: Path) -> float | None:
    """Workspace-configured provider keepalive window (``llm.http_keepalive_s``) for model_http.

    Read here (model_factory already receives ``workspace_path``) so the keepalive pref reaches the
    HTTP-client build without threading a param through every caller. Best-effort: a prefs read /
    validation hiccup falls back to the model_http default rather than blocking model construction —
    keepalive is perf tuning, not correctness. Returns ``None`` on any failure (helper applies the
    default)."""
    try:
        from .preferences.io import load_preferences

        return float(load_preferences(workspace_path).llm.http_keepalive_s)
    except Exception:
        logger.warning(
            "⚠️ model factory — could not read llm.http_keepalive_s; using default keepalive",
            exc_info=True,
        )
        return None


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
    num_ctx: int | None = None,
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
            num_ctx=num_ctx,
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
    # Workspace keepalive window for the warm-connection HTTP clients wired below (cloud providers).
    keepalive_s = _http_keepalive_s(workspace_path)

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
            # OpenAI rejects reasoning_effort + function tools on /v1/chat/completions
            # (400: "Please use /v1/responses instead") for GPT-5.x reasoning models.
            # Route reasoning models through the Responses API so tool-calling agents work.
            kwargs["use_responses_api"] = True
            kwargs["max_completion_tokens"] = effective.max_tokens
            effort = _openai_reasoning_effort(effective.thinking, spec)
            if effort is not None:
                kwargs["reasoning_effort"] = effort
        else:
            kwargs["temperature"] = effective.temperature
            kwargs["max_tokens"] = effective.max_tokens
        # Warm-keepalive HTTP clients (centralized in model_http) so a human-paced turn doesn't
        # re-handshake on its first call. streaming=True → wires both sync + async clients.
        kwargs.update(openai_http_kwargs(streaming=True, keepalive_s=keepalive_s))
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
        # NOTE: no warm-keepalive client here. google-genai's ASYNC path uses aiohttp and forwards
        # client_args into ``ClientSession.request(**args)`` alongside its own ``timeout=``, so any
        # httpx-shaped kwarg collides ("multiple values for keyword argument 'timeout'"). Left on
        # SDK defaults — see model_http for the full provider-coverage rationale.
        return init_chat_model(
            api_model,
            **kwargs,
        )

    if pid == "deepseek":
        # DeepSeek V4 is dual-mode (thinking / non-thinking) toggled per-request via
        # extra_body. We use the dedicated ChatDeepSeek wrapper (not a generic ChatOpenAI
        # shim) so reasoning_content round-trips across multi-turn tool calls (required, or
        # the API 400s) and DeepSeek cache/reasoning token usage is reported. Thinking mode
        # ignores temperature, so we only send it when reasoning is disabled.
        from langchain_deepseek import ChatDeepSeek

        key = store.get_api_key("deepseek")
        if not key:
            raise ValueError("DeepSeek API key missing (keyring or DEEPSEEK_API_KEY).")
        cred = store.get("deepseek")
        prov = cat.get_provider("deepseek")
        api_base = (cred.base_url if cred and cred.base_url else None) or (
            prov.default_base_url if prov else None
        )
        if not api_base:
            raise ValueError("DeepSeek api_base missing (catalog default_base_url).")
        ds_kwargs: dict[str, Any] = {
            "model": api_model,
            "api_base": api_base,
            "api_key": key,
            "max_tokens": effective.max_tokens,
            "callbacks": cb,
        }
        effort = _deepseek_reasoning_effort(effective.thinking, spec)
        if effort is None:
            # Non-thinking mode honors temperature; explicitly disable thinking.
            ds_kwargs["temperature"] = effective.temperature
            ds_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        else:
            ds_kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
            ds_kwargs["reasoning_effort"] = effort
        # DeepSeek is the langchain_openai family (ChatDeepSeek exposes http_client) — same
        # warm-keepalive policy as OpenAI chat.
        ds_kwargs.update(openai_http_kwargs(streaming=True, keepalive_s=keepalive_s))
        return ChatDeepSeek(**ds_kwargs)

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
        ollama_kwargs: dict[str, Any] = {
            "model": api_model,
            "base_url": base_url,
            "temperature": effective.temperature,
            "num_predict": effective.max_tokens,
            "callbacks": cb,
        }
        # Ollama defaults num_ctx to 2048 regardless of the model's real window, truncating
        # long-context local models. Only override when a tuning profile sets it (None = leave
        # Ollama's default — we never auto-max to the catalog window to avoid OOMing the KV cache).
        if effective.num_ctx is not None:
            ollama_kwargs["num_ctx"] = effective.num_ctx
        # ThinkingLevel was previously ignored for Ollama. ChatOllama exposes a *boolean* `reasoning`
        # (the Ollama `think` flag), not graded effort, so any enabled level maps to True. Gated on
        # the catalog `reasoning` feature so non-reasoning models aren't sent an unsupported flag.
        if spec.supports_reasoning():
            ollama_kwargs["reasoning"] = effective.thinking not in (None, "off")
        return ChatOllama(**ollama_kwargs)

    raise ValueError(f"Model factory does not support provider {pid!r} yet.")


def with_structured_output_compat(model: Any, schema: type, *, include_raw: bool = True) -> Any:
    """``with_structured_output`` that survives provider quirks; use instead of calling it raw.

    DeepSeek thinking mode rejects the forced tool_choice that langchain's default
    function_calling method sends (API 400: "Thinking mode does not support this tool_choice").
    Dual-mode DeepSeek models built with thinking enabled (``build_chat_model_from_tuning`` sets
    ``extra_body.thinking.type='enabled'``) therefore fall back to ``method='json_mode'`` —
    verified working against the live API. json_mode only guarantees valid JSON, NOT the schema:
    the caller's prompt MUST describe the expected JSON fields (field descriptions on the pydantic
    schema never reach the model in this mode). Every other provider/mode keeps langchain's
    default method. Class-name check (not isinstance) so langchain_deepseek stays a lazy import.
    """
    if model.__class__.__name__ == "ChatDeepSeek":
        extra = getattr(model, "extra_body", None)
        thinking = (extra.get("thinking") or {}).get("type") if isinstance(extra, dict) else None
        if thinking == "enabled":
            return model.with_structured_output(schema, include_raw=include_raw, method="json_mode")
    return model.with_structured_output(schema, include_raw=include_raw)


# OpenAI reasoning_effort vocabulary, ordered low→high effort. Used to clamp the neutral
# ThinkingLevel onto whatever a given model accepts (the set varies by GPT-5 generation).
_OPENAI_EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh")


def _openai_reasoning_effort(thinking: ThinkingLevel | None, spec: ModelSpec) -> str | None:
    """Map the neutral ``ThinkingLevel`` onto a ``reasoning_effort`` the *model* accepts.

    OpenAI's effort vocabulary differs by generation (GPT-5.0: minimal/low/medium/high;
    GPT-5.4+: none/low/medium/high/xhigh — no ``minimal``), and pro tiers accept ``high`` only.
    Sending an unsupported level 400s ("does not support 'minimal' with this model"), so we clamp
    to the nearest value in the catalog ``reasoning_efforts``. ``off`` maps to an explicit ``none``
    when the model has it, else omits the param so the model applies its own default effort. Models
    without a catalog vocabulary fall back to sending the level verbatim (legacy behavior).
    """
    if thinking is None:
        return None
    supported = set(spec.reasoning_efforts)
    if not supported:
        return None if thinking == "off" else thinking
    if thinking == "off":
        return "none" if "none" in supported else None
    return _clamp_openai_effort(thinking, supported)


def _clamp_openai_effort(desired: str, supported: set[str]) -> str | None:
    """Nearest supported OpenAI ``reasoning_effort`` to ``desired``; ties resolve to the higher.

    The tie-break-toward-higher is deliberate: it lands neutral ``minimal`` on ``low`` (not
    ``none``) for GPT-5.4+ models that dropped ``minimal``, and collapses sub-``high`` levels onto
    ``high`` for high-only pro tiers.
    """
    if desired in supported:
        return desired
    candidates = [e for e in supported if e in _OPENAI_EFFORT_ORDER]
    if desired not in _OPENAI_EFFORT_ORDER or not candidates:
        return None
    target = _OPENAI_EFFORT_ORDER.index(desired)
    return min(
        candidates,
        key=lambda e: (abs(_OPENAI_EFFORT_ORDER.index(e) - target), -_OPENAI_EFFORT_ORDER.index(e)),
    )


def _deepseek_reasoning_effort(
    thinking: ThinkingLevel | None,
    spec: ModelSpec,
) -> str | None:
    """Map ThinkingLevel → DeepSeek ``reasoning_effort``, or None to disable thinking.

    DeepSeek V4 is dual-mode and only exposes ``high``/``max`` effort (default ``high``),
    so we clamp: ``high`` → ``"max"``, any other enabled level → ``"high"``. ``None``/``off``
    (or a non-reasoning model) returns None → caller disables thinking and honors temperature.
    """
    if thinking in (None, "off") or not spec.supports_reasoning():
        return None
    return "max" if thinking == "high" else "high"


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


def catalog_embedding_dimensions(model_id: str) -> int:
    """Known output dimensions for bundled catalog embedding models."""
    return {
        "openai:text-embedding-3-small": 1536,
        "google:gemini-embedding-001": 768,
        "ollama:nomic-embed-text": 512,
    }.get(model_id, 1536)


def _embedding_init_provider(catalog_provider_id: str) -> str:
    """Map Hiro catalog ``provider_id`` to ``init_embeddings`` provider key."""
    return {
        "google": "google_genai",
    }.get(catalog_provider_id, catalog_provider_id)


def _embedding_provider_kwargs(
    catalog_provider_id: str,
    *,
    store: CredentialStore,
    cat: ModelCatalog,
    keepalive_s: float | None = None,
) -> dict[str, Any]:
    if catalog_provider_id == "openai":
        key = store.get_api_key("openai")
        if not key:
            raise ValueError("OpenAI API key missing (keyring or OPENAI_API_KEY).")
        # Warm-keepalive http_client (centralized in model_http) so a human-paced chat turn doesn't
        # re-handshake on every query embed (~1.7s cold-connect was observed for a 63-char query —
        # record count is irrelevant). streaming=False → sync client only (embed_documents is sync).
        return {"api_key": key, **openai_http_kwargs(streaming=False, keepalive_s=keepalive_s)}

    if catalog_provider_id == "google":
        key = store.get_api_key("google")
        if not key:
            raise ValueError("Google API key missing (keyring or GOOGLE_API_KEY).")
        # No warm-keepalive client: google-genai's aiohttp async path rejects httpx-shaped
        # client_args (see the chat branch / model_http). Left on SDK defaults.
        return {"google_api_key": key}

    if catalog_provider_id == "ollama":
        cred = store.get("ollama")
        prov = cat.get_provider("ollama")
        base_url = (cred.base_url if cred and cred.base_url else None) or (
            prov.default_base_url if prov else None
        )
        if not base_url:
            raise ValueError(
                "Ollama base_url missing; run: hiro provider endpoint ollama http://localhost:11434"
            )
        return {"base_url": base_url}

    if catalog_provider_id == "lm_studio":
        cred = store.get("lm_studio")
        base_url = getattr(cred, "base_url", None)
        if not base_url:
            raise ValueError("LM Studio base_url missing for embedding model")
        return {"base_url": base_url, "api_key": "lm-studio"}

    raise ValueError(f"Model factory does not support embedding provider {catalog_provider_id!r} yet.")


def create_embedding_model(
    model_id: str,
    *,
    workspace_path: Path,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> Embeddings:
    """Resolve ``provider:api_id`` to a LangChain Embeddings instance with credentials injected.

    Raises ``ValueError`` if the model is unknown, not an embedding model, or the provider
    is not configured for this workspace.
    """
    cat = get_model_catalog()
    spec = cat.get_model(model_id)
    if spec is None:
        raise ValueError(f"Unknown model id: {model_id}")
    if not spec.supports_kind("embedding"):
        raise ValueError(f"Model {model_id} is not an embedding model (kind={spec.model_kind})")

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
    provider_kwargs = _embedding_provider_kwargs(
        pid, store=store, cat=cat, keepalive_s=_http_keepalive_s(workspace_path)
    )

    # LM Studio is OpenAI-compatible but not a built-in init_embeddings provider key.
    if pid == "lm_studio":
        return init_embeddings(
            api_model,
            provider="openai",
            **provider_kwargs,
        )

    lc_provider = _embedding_init_provider(pid)
    return init_embeddings(f"{lc_provider}:{api_model}", **provider_kwargs)


def create_reranker(
    model_id: str,
    *,
    workspace_path: Path,
    workspace_id: str | None = None,
    top_n: int = 8,
    credential_store: CredentialStore | None = None,
) -> BaseDocumentCompressor:
    """Resolve a **cloud** catalog ``provider:model`` rerank id to a LangChain compressor.

    Mirrors ``create_embedding_model``: validate the catalog spec, pull the provider key from
    the workspace ``CredentialStore``, and return a ``BaseDocumentCompressor``. Local in-process
    rerankers are NOT handled here — they live in the knowledge local-reranker registry.

    Raises ``ValueError`` if the model is unknown, not a rerank model, or the provider is not
    configured for this workspace.
    """
    cat = get_model_catalog()
    spec = cat.get_model(model_id)
    if spec is None:
        raise ValueError(f"Unknown model id: {model_id}")
    if not spec.supports_kind("rerank"):
        raise ValueError(f"Model {model_id} is not a rerank model (kind={spec.model_kind})")

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
    # NOTE: the rerank wrappers (CohereRerank / VoyageAIRerank) expose only a pre-built ``client``
    # object, not an httpx ``http_client`` / ``client_args`` hook, so the centralized warm-keepalive
    # policy (model_http) can't be injected here without hand-constructing each vendor client. Left
    # on SDK defaults for now (rerank calls are short; the cold-connect cost is smaller than embed).
    if pid == "cohere":
        key = store.get_api_key("cohere")
        if not key:
            raise ValueError("Cohere API key missing (keyring or COHERE_API_KEY).")
        from langchain_cohere import CohereRerank

        return CohereRerank(model=api_model, top_n=top_n, cohere_api_key=key)

    if pid == "voyage":
        key = store.get_api_key("voyage")
        if not key:
            raise ValueError("Voyage API key missing (keyring or VOYAGE_API_KEY).")
        from langchain_voyageai import VoyageAIRerank

        # Voyage's compressor takes ``top_k`` (not ``top_n``).
        return VoyageAIRerank(model=api_model, top_k=top_n, voyage_api_key=key)

    raise ValueError(f"Model factory does not support rerank provider {pid!r} yet.")
