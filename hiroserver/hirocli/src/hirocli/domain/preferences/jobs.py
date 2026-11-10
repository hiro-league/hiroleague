"""Hiro's own AI jobs and the AI profiles they use (Phase 7b step 5).

Each of the core's own jobs (chat, memory retrieval, knowledge answering, …) points at ONE AI profile
(``prefs.ai.profiles``) through its own preference field (``JobPreset.path``). The profile carries the
model and its tuning (thinking, temperature, max tokens, context window, instructions) and a fallback
chain, so tuning profiles are gone: what used to be "a model setting + a tuning profile" is now one pick.

``JOB_PRESETS`` is the code table of every job:

- ``path`` — the preference field holding the job's AI profile id (``None`` = not set);
- ``profile_id`` / ``label`` — the id and name of the profile made for the job by default (the
  one-time v3 → v4 conversion, onboarding); such a profile carries ``preset=<job id>`` so the admin
  shows "Default", hides Delete and offers Restore default;
- ``falls_back_to`` — the job whose model is used when this job's field is null (chat-like jobs → chat;
  graph small steps → graph extraction; eval retrieval → eval answer; rewrite → knowledge; chat and
  reading pictures → nothing, i.e. off);
- ``temperature`` / ``max_tokens`` / ``thinking`` — the preset tuning (the old tuning presets' values),
  used for a default profile, for Restore default, and when the job borrows another job's model.

An AI profile's limits (``max_cost_day`` / ``max_per_hour``) never stop these jobs: their calls are
counted in AI usage only (decided with the owner).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from .defaults import ThinkingLevel

if TYPE_CHECKING:
    from .models_ai import AiProfile

JobId = Literal[
    "chat",
    "memory",
    "knowledge",
    "rewrite",
    "graph_extraction",
    "graph_small",
    "eval_answer",
    "eval_judge",
    "eval_retrieval",
    "vision",
]


@dataclass(frozen=True)
class JobPreset:
    """One of Hiro's own AI jobs (module notes)."""

    id: str
    path: str
    profile_id: str
    label: str
    falls_back_to: str | None
    temperature: float
    max_tokens: int
    thinking: ThinkingLevel | None


# The old tuning presets' values, kept per job (balanced_chat, memory_extraction, knowledge_answering,
# knowledge_rewrite, graphiti_extraction, graphiti_small; the eval jobs used knowledge_answering).
# Vision used a hard-coded 0.7 / 4096 in services/vision_service.py.
JOB_PRESETS: dict[str, JobPreset] = {
    p.id: p
    for p in (
        JobPreset("chat", "llm.chat_profile", "hiro-chat", "Hiro's chat", None, 0.3, 2048, None),
        JobPreset("memory", "memory.retrieval.profile", "hiro-memory", "Memory retrieval", "chat", 0.0, 8192, "low"),
        JobPreset(
            "knowledge", "knowledge.answering.profile", "hiro-knowledge", "Knowledge answering", "chat", 0.2, 1600, None
        ),
        # Reasoning off on purpose: a reasoning model would spend the budget thinking and never emit
        # the structured JSON the rewrite needs.
        JobPreset(
            "rewrite",
            "knowledge.answering.rewrite_profile",
            "hiro-rewrite",
            "Knowledge query rewrite",
            "knowledge",
            0.0,
            1024,
            "off",
        ),
        JobPreset(
            "graph_extraction", "graph.extraction_profile", "hiro-graph-extraction", "Graph extraction", "chat", 0.0,
            4096, "off",
        ),
        JobPreset(
            "graph_small", "graph.small_profile", "hiro-graph-small", "Graph small steps", "graph_extraction", 0.0,
            2048, "off",
        ),
        JobPreset("eval_answer", "graph.eval.answer_profile", "hiro-eval-answer", "Eval: answer", "chat", 0.2, 1600, None),
        JobPreset("eval_judge", "graph.eval.judge_profile", "hiro-eval-judge", "Eval: judge", "chat", 0.2, 1600, None),
        JobPreset(
            "eval_retrieval", "graph.eval.retrieval_profile", "hiro-eval-retrieval", "Eval: retrieval", "eval_answer",
            0.2, 1600, None,
        ),
        JobPreset("vision", "llm.vision_profile", "hiro-vision", "Reading pictures", None, 0.7, 4096, None),
    )
}


def job_preset(job: str) -> JobPreset:
    """The job's preset; ValueError for a job id the core doesn't have."""
    preset = JOB_PRESETS.get(job)
    if preset is None:
        raise ValueError(f"unknown job {job!r} (jobs: {', '.join(JOB_PRESETS)})")
    return preset


def job_profile_ref(prefs: Any, job: str) -> str | None:
    """The AI profile id the job's preference field holds (None when not set)."""
    node: Any = prefs
    for part in job_preset(job).path.split("."):
        node = getattr(node, part, None)
        if node is None:
            return None
    value = str(node).strip()
    return value or None


def preset_profile(job: str, model: str, *, label: str | None = None) -> "AiProfile":
    """A job's default profile for ``model`` with the preset tuning (validates the model)."""
    from .models_ai import AiProfile

    preset = job_preset(job)
    return AiProfile(
        label=label or preset.label,
        model=model,
        thinking=preset.thinking,
        temperature=preset.temperature,
        max_tokens=preset.max_tokens,
        preset=preset.id,
    )


def restore_preset_tuning(profile: "AiProfile") -> "AiProfile":
    """``profile`` with its job preset's tuning back (thinking, temperature, max tokens, no context
    window, no instructions); the model, limits, fallback and name are kept. ValueError when the
    profile wasn't made as a job's default."""
    if not profile.preset:
        raise ValueError(f"AI profile {profile.label!r} isn't a job's default profile (no preset)")
    preset = job_preset(profile.preset)
    return profile.model_copy(
        update={
            "thinking": preset.thinking,
            "temperature": preset.temperature,
            "max_tokens": preset.max_tokens,
            "num_ctx": None,
            "instructions": "",
        }
    )


def unique_profile_id(existing: Any, wanted: str) -> str:
    """``wanted``, or ``wanted-2``, ``wanted-3``… when the id is taken in ``existing``."""
    if wanted not in existing:
        return wanted
    n = 2
    while f"{wanted}-{n}" in existing:
        n += 1
    return f"{wanted}-{n}"


__all__ = [
    "JOB_PRESETS",
    "JobId",
    "JobPreset",
    "job_preset",
    "job_profile_ref",
    "preset_profile",
    "restore_preset_tuning",
    "unique_profile_id",
]
