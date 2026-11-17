"""The memory settings the engine reads. Their values live with the owner (the core's preferences,
EvalHiro's run snapshot); the classes live here so both parse them the same way."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

# Which facts recall shows: only those true now, or every fact with its time window.
KnowledgeGraphTemporalDefault = Literal["current", "all"]


class RetrievalAgentLimits(BaseModel):
    """Caps and clamp bounds for the agentic memory-retrieval loop (eval + chat parity)."""

    # SEARCH-turn budget: how many tool-bound turns the agent gets to search (one search_memory call
    # per turn, each up to max_parallel_searches sub-queries). The optional exit-B compose turn (a
    # tool-free final answer, only when the loop never stops on its own) is NOT counted, so total LLM
    # calls are at most max_agent_turns + 1. (Changed 2026-07-03 from "turns − 1 search turns, one
    # reserved for the answer" — that starved max_agent_turns=1 of ALL search turns. P9 rename: was
    # ``max_searches``; the counter advances per turn, not per dispatched search call.)
    max_agent_turns: int = Field(default=4, ge=1, le=10, title="Max agent turns", description="Tool-bound turns the agent gets to search (one search_memory call per turn, each up to max-parallel-searches sub-queries). The optional final compose turn isn't counted, so total LLM calls are at most this + 1.")
    # Sub-queries per single ``search_memory`` call (the decomposition fan-out). Enforced by the
    # tool against the configured value; one global value for eval and chat.
    max_parallel_searches: int = Field(default=3, ge=1, le=5, title="Max parallel searches", description="Sub-queries per search_memory call — global for eval and chat.")
    # "Num results" = how many memories one search fetches. The agent CHOOSES this per sub-query;
    # ``limit_default`` is used when it omits one, and the choice is clamped into
    # ``[limit_min, limit_max]`` (search_tool._run_one). Field names kept (limit_*) — only the
    # user-facing labels/tooltips renamed for clarity.
    limit_default: int = Field(default=20, ge=1, le=100, title="Num results default", description="Memories one search fetches when the agent doesn't request a specific number — its starting point.")
    limit_min: int = Field(default=10, ge=1, le=100, title="Num results min", description="Lower bound of the range the search tool clamps the agent's requested result count into.")
    limit_max: int = Field(default=40, ge=1, le=100, title="Num results max", description="Upper bound of the range the search tool clamps the requested result count into — also the ceiling the loop tells the agent it may raise up to.")
    hops_max: int = Field(default=3, ge=1, le=3, title="Hops max", description="Upper bound on graph expansion hops the tool accepts per search (1–3).")

    @model_validator(mode="after")
    def _coherent_limits(self) -> "RetrievalAgentLimits":
        if self.limit_min > self.limit_default or self.limit_default > self.limit_max:
            raise ValueError("Num results must satisfy min ≤ default ≤ max")
        return self

