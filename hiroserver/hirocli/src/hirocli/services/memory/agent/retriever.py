"""Surface-neutral entrypoint for the memory retrieval loop (Phase 0 seam).

Both eval (``runner_memory``) and chat (the ``memory_recall`` node) call
:meth:`MemoryRetriever.retrieve` instead of :func:`run_retrieval` directly, so the per-surface loop
flags (``history`` / ``allow_abstain``) live at ONE call boundary rather than being threaded through
each caller. Phase 0 keeps this a thin forwarder; later phases give it the per-surface config
building (caps / prompt / model resolution) so eval and chat can diverge without touching the loop.
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage

from hirocli.domain.preferences import RetrievalAgentLimits
from hirocli.services.memory.agent import retrieval_agent
from hirocli.services.memory.agent.retrieval_agent import RetrievalResult
from hirocli.services.memory.graphiti_conversation import GraphitiConversationMemory


class MemoryRetriever:
    """Surface-neutral seam over :func:`run_retrieval` (see design: Chat retrieval — Phase 0)."""

    @staticmethod
    async def retrieve(
        query: str,
        *,
        memory: GraphitiConversationMemory,
        limits: RetrievalAgentLimits,
        prompt_text: str,
        model: BaseChatModel,
        user_id: int,
        character_id: str,
        model_id: str = "",
        history: list[AnyMessage] | None = None,
        allow_abstain: bool = False,
    ) -> RetrievalResult:
        """Run the bounded retrieval loop for ``query``; forwards to :func:`run_retrieval`.

        ``history`` / ``allow_abstain`` default to eval behavior (see
        :func:`retrieval_agent.run_retrieval`), so an eval call with defaults is byte-identical to
        calling ``run_retrieval`` directly. Dispatched through the module (not a bound import) so a
        test monkeypatching ``retrieval_agent.run_retrieval`` is honored.
        """
        return await retrieval_agent.run_retrieval(
            question=query,
            memory=memory,
            limits=limits,
            prompt_text=prompt_text,
            model=model,
            user_id=user_id,
            character_id=character_id,
            model_id=model_id,
            history=history,
            allow_abstain=allow_abstain,
        )


__all__ = ["MemoryRetriever"]
