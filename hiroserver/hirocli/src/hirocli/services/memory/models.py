"""Chat memory retrieval-agent model builder (memory-eval-vs-chat-parity, Phase 2).

Mirrors ``services/eval/models.build_eval_retrieval_model`` but for the CHAT recall loop
(``memory.retrieval.*``): resolve the configured model + tuning, then build a LangChain chat model.
Returns ``(None, "")`` when unconfigured/unavailable so the recall node degrades gracefully (the
turn simply proceeds without memory) instead of raising.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hiro_commons.log import Logger

log = Logger.get("SVC.MEMORY.MODEL")


def build_memory_retrieval_model(
    prefs: Any,
    workspace_path: Path,
    *,
    credential_store: Any = None,
) -> tuple[Any | None, str]:
    """Build the CHAT retrieval-agent model (``memory.retrieval.model`` → ``llm.default_chat``).

    ``prefs`` is the live preferences snapshot (avoids a per-turn ``preferences.json`` reload).
    Returns ``(model, model_id)`` — the prefixed ``provider:model`` id is threaded to the loop so its
    LLM cost is priced onto the recall ledger node — or ``(None, "")`` when no chat model is
    configured/available."""
    try:
        from hirocli.domain.model_factory import create_chat_model
        from hirocli.domain.preferences import resolve_memory_retrieval_llm

        spec = resolve_memory_retrieval_llm(prefs, workspace_path, credential_store=credential_store)
        if spec is None:
            log.warning("⚠️ memory — no chat model for the retrieval loop; recall skipped this turn")
            return None, ""
        model = create_chat_model(
            spec.model_id,
            workspace_path=workspace_path,
            temperature=spec.temperature,
            max_tokens=spec.max_tokens,
            thinking=spec.thinking,
        )
        return model, spec.model_id
    except Exception:
        log.warning("⚠️ memory — retrieval model unavailable", exc_info=True)
        return None, ""


__all__ = ["build_memory_retrieval_model"]
