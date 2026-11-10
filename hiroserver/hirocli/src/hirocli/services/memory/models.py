"""Chat memory retrieval-agent model builder (memory-eval-vs-chat-parity, Phase 2).

Mirrors ``services/eval/models.build_eval_retrieval_model`` but for the CHAT recall loop
(``memory.retrieval.*``): resolve the memory job's AI profile (``memory.retrieval.profile``, else the
chat job's model with the memory preset tuning), then build a LangChain chat model.
Returns ``(None, "")`` when unconfigured/unavailable so the recall node degrades gracefully (the
turn simply proceeds without memory) instead of raising.

``MemoryRetrievalModelCache`` memoizes that build across turns — see its docstring for why.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hiro_commons.log import Logger

log = Logger.get("SVC.MEMORY.MODEL")


class MemoryRetrievalModelCache:
    """Cross-turn cache for the CHAT recall model (``memory.retrieval.profile`` → ``llm.chat_profile``).

    Fixes a per-turn hot-path cost (review C2): ``memory_recall`` previously rebuilt the model on
    EVERY message via ``create_chat_model`` — full provider-client + credential setup — then threw it
    away. Spec resolution (``resolve_memory_retrieval_llm``) is cheap (reads the live prefs snapshot);
    building the client is not. So we re-resolve the spec each turn and rebuild only when the resolved
    ``(profile, model_id, temperature, max_tokens, thinking, num_ctx)`` actually changes — which
    self-invalidates on any ``memory.retrieval.profile`` / ``llm.chat_profile`` / AI-profile edit.

    ``clear()`` drops the cached client so a credential/provider change rebinds it: the ``model_id``
    can be unchanged yet the stored client hold stale credentials, so the spec key alone would not
    self-invalidate. The agent manager calls ``clear()`` from its single memory-rebind choke point
    (``_attach_new_memory_service``), which fires on both memory-preference and providers changes.
    """

    def __init__(self) -> None:
        self._key: tuple[Any, ...] | None = None
        self._model: Any | None = None
        self._model_id: str = ""

    def get(
        self,
        prefs: Any,
        workspace_path: Path,
        *,
        credential_store: Any = None,
    ) -> tuple[Any | None, str]:
        """Return ``(model, model_id)`` for this turn, rebuilding only when the resolved spec changed.

        ``(None, "")`` when no chat model is configured/available — the recall node then proceeds
        without memory rather than raising. ``model_id`` is the prefixed ``provider:model`` id, threaded
        to the loop so its LLM cost prices onto the recall ledger node.
        """
        try:
            from hirocli.domain.preferences import resolve_memory_retrieval_llm

            spec = resolve_memory_retrieval_llm(
                prefs, workspace_path, credential_store=credential_store
            )
        except Exception:
            log.warning("⚠️ memory — retrieval model spec unavailable", exc_info=True)
            return None, ""

        if spec is None:
            # No model configured/available — drop any stale entry and degrade.
            self.clear()
            log.warning("⚠️ memory — no chat model for the retrieval loop; recall skipped this turn")
            return None, ""

        # Phase 7b step 5: the AI profile and its context window are part of the key (num_ctx now
        # reaches the model too, for local models).
        key = (spec.profile_id, spec.model_id, spec.temperature, spec.max_tokens, spec.thinking, spec.num_ctx)
        if self._model is not None and key == self._key:
            return self._model, self._model_id

        try:
            from hirocli.domain.model_factory import create_chat_model

            model = create_chat_model(
                spec.model_id,
                workspace_path=workspace_path,
                temperature=spec.temperature,
                max_tokens=spec.max_tokens,
                thinking=spec.thinking,
                num_ctx=spec.num_ctx,
                credential_store=credential_store,
            )
        except Exception:
            log.warning("⚠️ memory — retrieval model unavailable", exc_info=True)
            self.clear()
            return None, ""

        self._key, self._model, self._model_id = key, model, spec.model_id
        log.fineinfo("memory — retrieval model (re)built · %s", spec.model_id)
        return model, spec.model_id

    def clear(self) -> None:
        """Drop the cached client (forces a rebuild on the next ``get``) — used on credential change."""
        self._key = None
        self._model = None
        self._model_id = ""


__all__ = ["MemoryRetrievalModelCache"]
