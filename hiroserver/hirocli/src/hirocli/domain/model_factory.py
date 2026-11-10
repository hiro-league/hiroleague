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
from .model_http import ProviderCallPolicy, openai_http_kwargs
from .preferences import ModelTuning, ThinkingLevel
from .workspace import workspace_id_for_path

if TYPE_CHECKING:
    from langchain_core.documents.compressor import BaseDocumentCompressor
    from langchain_core.embeddings import Embeddings
    from langchain_core.language_models.chat_models import BaseChatModel

logger = logging.getLogger(__name__)


def _http_settings(workspace_path: Path) -> tuple[float | None, ProviderCallPolicy]:
    """Workspace HTTP settings for model calls: keepalive window + timeout/retry policy.

    Read here (model_factory already receives ``workspace_path``) so the ``llm.*`` HTTP prefs reach
    the client build without threading params through every caller. Best-effort: a prefs read /
    validation hiccup falls back to the defaults rather than blocking model construction. Returns
    ``(None, default policy)`` on any failure (model_http applies the keepalive default)."""
    try:
        from .preferences.io import load_preferences

        prefs = load_preferences(workspace_path)
        return float(prefs.llm.http_keepalive_s), ProviderCallPolicy.from_prefs(prefs)
    except Exception:
        logger.warning(
            "⚠️ model factory — could not read the llm HTTP preferences; using defaults",
            exc_info=True,
        )
        return None, ProviderCallPolicy()


def _api_model_id(canonical_id: str) -> str:
    parts = canonical_id.split(":", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Invalid canonical model id (expected provider:model): {canonical_id!r}")
    return parts[1]


def _local_server_spec(cat: ModelCatalog, workspace_path: Path, model_id: str) -> ModelSpec | None:
    """A local server's model with no catalog row, as the server last reported it (else a bare row).

    Phase 7b step 5: Hiro's jobs build their model from an AI profile, which may name any model a
    local server (LM Studio / Ollama) reports — as ``services/ai_ask/targets.resolve_target`` does.
    """
    from .discovered_models import DiscoveredModel, discovered_model_spec, get_discovered_model

    provider_id, _, name = model_id.partition(":")
    prov = cat.get_provider(provider_id)
    if prov is None or prov.hosting != "local" or not name:
        return None
    seen = get_discovered_model(workspace_path, model_id)
    return discovered_model_spec(
        seen
        or DiscoveredModel(
            provider_id=provider_id, name=name, display_name=name, vision=True, reasoning=False, loaded=False
        )
    )


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
    spec: ModelSpec | None = None,
) -> BaseChatModel:
    """Build a chat model and map provider-neutral tuning to provider kwargs.

    ``spec`` overrides the catalog lookup: a model a local server reports with no catalog row
    (Phase 7a, ``discovered_models.discovered_model_spec``) is built from its synthetic row.
    """
    cat = get_model_catalog()
    spec = spec or cat.get_model(model_id) or _local_server_spec(cat, workspace_path, model_id)
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
    # Workspace keepalive window for the warm-connection HTTP clients wired below (cloud providers),
    # and the timeout/retry policy every cloud branch applies (llm.request_timeout_s / max_retries).
    keepalive_s, policy = _http_settings(workspace_path)

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
        # re-handshake on its first call. streaming=True → wires both sync + async clients; the
        # client's read timeout is the workspace policy's, and the SDK retries per the policy.
        kwargs.update(openai_http_kwargs(streaming=True, keepalive_s=keepalive_s, policy=policy))
        kwargs["max_retries"] = policy.max_retries
        return init_chat_model(
            api_model,
            **kwargs,
        )

    if pid == "anthropic":
        key = store.get_api_key("anthropic")
        if not key:
            raise ValueError("Anthropic API key missing (keyring or ANTHROPIC_API_KEY).")
        # No temperature: the anthropic 2.x SDK speaks API version 2026-10-21, which rejects
        # temperature/top_p/top_k on every model (and Claude 4.7+ rejected non-default values
        # even before). Thinking depth is steered with adaptive thinking + effort instead.
        kwargs = {
            "model_provider": "anthropic",
            "api_key": key,
            "max_tokens": effective.max_tokens,
            "callbacks": cb,
            # Workspace timeout/retry policy instead of the SDK's own 600s / 2 retries.
            "timeout": policy.timeout_s,
            "max_retries": policy.max_retries,
        }
        kwargs.update(_anthropic_thinking_kwargs(effective.thinking, spec))
        return init_chat_model(
            api_model,
            **kwargs,
        )

    if pid == "google":
        key = store.get_api_key("google")
        if not key:
            raise ValueError("Google API key missing (keyring or GOOGLE_API_KEY).")
        # No temperature: Gemini deprecated temperature/top_p/top_k on Jul 21, 2026 (ignored now,
        # documented to become a 400 on future models). Every catalog Gemini row is 3.5+.
        kwargs = {
            "model_provider": "google_genai",
            "google_api_key": key,
            "max_output_tokens": effective.max_tokens,
            "callbacks": cb,
            # Workspace timeout/retry policy. langchain-google-genai's defaults were no timeout and
            # 6 attempts, which hung chat turns for minutes during a Gemini 503 spell (2026-11-06).
            # Its max_retries is google-genai's ``attempts`` (first try included) → policy.attempts.
            "timeout": policy.timeout_s,
            "max_retries": policy.attempts,
        }
        kwargs.update(_google_thinking_kwargs(effective.thinking, spec))
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
        ds_kwargs.update(openai_http_kwargs(streaming=True, keepalive_s=keepalive_s, policy=policy))
        ds_kwargs["max_retries"] = policy.max_retries
        return ChatDeepSeek(**ds_kwargs)

    if pid == "lm_studio":
        from langchain_openai import ChatOpenAI

        cred = store.get("lm_studio")
        prov = cat.get_provider("lm_studio")
        base_url = (getattr(cred, "base_url", None) or (prov.default_base_url if prov else None) or "").rstrip("/")
        if not base_url:
            raise ValueError("LM Studio base_url missing for chat model")
        # The stored endpoint is the server root (provider_check_endpoint probes {base}/v1/models), but
        # the OpenAI client appends /chat/completions to base_url itself: LM Studio needs the /v1 prefix
        # (found un-hiding LM Studio for Phase 7a; the hidden provider had never been used for chat).
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"
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


def with_structured_output_compat(model: Any, schema: type | dict[str, Any], *, include_raw: bool = True) -> Any:
    """``with_structured_output`` that survives provider quirks; use instead of calling it raw.

    ``schema`` is a pydantic class or a JSON schema dict (Phase 7a's AI asks pass the extension's
    schema as a dict). The method per provider is ``structured_output_method``.
    """
    method = structured_output_method(model)
    if method is None:
        return model.with_structured_output(schema, include_raw=include_raw)
    return model.with_structured_output(schema, include_raw=include_raw, method=method)


def structured_output_method(model: Any) -> str | None:
    """The ``with_structured_output`` method a model needs, or None for langchain's default.

    DeepSeek thinking mode rejects the forced tool_choice that langchain's default
    function_calling method sends (API 400: "Thinking mode does not support this tool_choice").
    Dual-mode DeepSeek models built with thinking enabled (``build_chat_model_from_tuning`` sets
    ``extra_body.thinking.type='enabled'``) therefore fall back to ``json_mode`` — verified working
    against the live API. json_mode only guarantees valid JSON, NOT the schema: the caller's prompt
    MUST describe the expected JSON fields (field descriptions on the schema never reach the model in
    this mode). Claude 5.x rejects the FORCED tool_choice langchain's default function_calling
    method relies on, so langchain drops the force and the model may simply answer in text —
    OutputParserException (seen live 2026-11-06: Sonnet 5.5 with thinking off). Claude's native
    structured outputs (``json_schema``) enforce the schema itself; verified live on
    Opus/Sonnet/Haiku 5.5, thinking on and off, nested schemas included. Every other provider/mode
    keeps langchain's default method. Class-name check (not isinstance) so the provider packages
    stay lazy imports. (Split out of ``with_structured_output_compat`` for Phase 7a: the AI ask
    must know when json_mode is used, to put the schema in the prompt.)
    """
    if model.__class__.__name__ == "ChatDeepSeek":
        extra = getattr(model, "extra_body", None)
        thinking = (extra.get("thinking") or {}).get("type") if isinstance(extra, dict) else None
        if thinking == "enabled":
            return "json_mode"
    if model.__class__.__name__ == "ChatAnthropic":
        return "json_schema"
    return None


# Effort vocabulary shared by every provider, ordered low→high. Used to clamp the neutral
# ThinkingLevel onto whatever a given model accepts (catalog ``reasoning_efforts``). ``max`` is new
# with GPT-5.6/GPT-6, Claude 5.x and DeepSeek V4; ``minimal`` survives only on some Gemini models.
_EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max")


def _openai_reasoning_effort(thinking: ThinkingLevel | None, spec: ModelSpec) -> str | None:
    """Map the neutral ``ThinkingLevel`` onto a ``reasoning_effort`` the *model* accepts.

    OpenAI's effort vocabulary differs by model (GPT-6: low…max; Terra/Luna also accept ``none``;
    no GPT-5.6/6 model accepts ``minimal``). Sending an unsupported level 400s, so we clamp to the
    nearest value in the catalog ``reasoning_efforts``. ``off`` maps to an explicit ``none`` when the
    model has it, else omits the param so the model applies its own default effort. Models without
    a catalog vocabulary fall back to sending the level verbatim.
    """
    if thinking is None:
        return None
    supported = set(spec.reasoning_efforts)
    if not supported:
        return None if thinking == "off" else thinking
    if thinking == "off":
        return "none" if "none" in supported else None
    return _clamp_effort(thinking, supported)


def _clamp_effort(desired: str, supported: set[str]) -> str | None:
    """Nearest supported effort to ``desired``; ties resolve to the higher.

    The tie-break-toward-higher is deliberate: it lands neutral ``minimal`` on ``low`` (not
    ``none``) for models that dropped ``minimal``.
    """
    if desired in supported:
        return desired
    candidates = [e for e in supported if e in _EFFORT_ORDER]
    if desired not in _EFFORT_ORDER or not candidates:
        return None
    target = _EFFORT_ORDER.index(desired)
    return min(
        candidates,
        key=lambda e: (abs(_EFFORT_ORDER.index(e) - target), -_EFFORT_ORDER.index(e)),
    )


def _lowest_effort(supported: list[str]) -> str | None:
    """Lowest catalog effort that still means "thinking on" (skips ``none``)."""
    ordered = sorted(
        (e for e in supported if e in _EFFORT_ORDER and e != "none"), key=_EFFORT_ORDER.index
    )
    return ordered[0] if ordered else None


# DeepSeek V4 effort values are none/low/high/max (``low`` added Aug 13, 2026; ``none`` = thinking
# off, which we express through extra_body instead). Neutral levels map onto the enabled ones.
_DEEPSEEK_EFFORT = {"minimal": "low", "low": "low", "medium": "high", "high": "max"}


def _deepseek_reasoning_effort(
    thinking: ThinkingLevel | None,
    spec: ModelSpec,
) -> str | None:
    """Map ThinkingLevel → DeepSeek ``reasoning_effort``, or None to disable thinking.

    ``minimal``/``low`` → ``low``, ``medium`` → ``high``, ``high`` → ``max``. ``None``/``off`` (or a
    non-reasoning model) returns None → caller disables thinking and honors temperature.
    """
    if thinking in (None, "off") or not spec.supports_reasoning():
        return None
    return _DEEPSEEK_EFFORT.get(thinking, "high")


def _google_thinking_kwargs(thinking: ThinkingLevel | None, spec: ModelSpec) -> dict[str, Any]:
    """Map ThinkingLevel → Gemini ``thinking_level`` clamped to what the model accepts.

    Gemini 3.5+ only documents ``thinking_level`` (``thinking_budget`` is gone from the docs), and
    the level set differs per model: ``minimal`` returns an error on 3.8 Flash and 4 Argon. These
    models cannot turn thinking fully off, so ``off`` maps to the model's lowest level.
    """
    if thinking is None or not spec.supports_reasoning():
        return {}
    efforts = list(spec.reasoning_efforts)
    if thinking == "off":
        lowest = _lowest_effort(efforts)
        return {"thinking_level": lowest} if lowest else {}
    if not efforts:
        return {"thinking_level": thinking}
    level = _clamp_effort(thinking, set(efforts))
    return {"thinking_level": level} if level else {}


def _anthropic_thinking_kwargs(thinking: ThinkingLevel | None, spec: ModelSpec) -> dict[str, Any]:
    """Map ThinkingLevel → Claude adaptive thinking + ``effort`` (sent as ``output_config.effort``).

    Every current Claude model (5.x) uses adaptive thinking; ``enabled`` + ``budget_tokens`` is a
    400 on them. Depth is steered with ``effort`` (low…max). ``off`` uses the model's
    ``thinking_off_type`` ("disabled" / "between_tools") where it has one; models that cannot turn
    thinking off (Opus 5.5, Fable 5.1) get adaptive thinking at their lowest effort instead.
    ``None`` sends nothing, so the model applies its own default (adaptive, default effort).
    """
    if thinking is None or not spec.supports_reasoning():
        return {}
    efforts = list(spec.reasoning_efforts)
    if thinking == "off":
        if spec.thinking_off_type:
            # "disabled"/"between_tools" are only accepted at effort <= high; the model's default
            # effort (medium/high) satisfies that, so no effort is sent alongside.
            return {"thinking": {"type": spec.thinking_off_type}}
        effort = _lowest_effort(efforts)
    else:
        effort = _clamp_effort(thinking, set(efforts)) if efforts else thinking
    out: dict[str, Any] = {"thinking": {"type": "adaptive"}}
    if effort:
        out["effort"] = effort
    return out


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
    # Embeddings keep model_http's fixed 30s fast timeout; only the keepalive pref applies here.
    keepalive_s, _policy = _http_settings(workspace_path)
    provider_kwargs = _embedding_provider_kwargs(pid, store=store, cat=cat, keepalive_s=keepalive_s)

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
