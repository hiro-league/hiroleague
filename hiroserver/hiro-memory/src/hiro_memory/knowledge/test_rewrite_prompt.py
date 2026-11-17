"""Guard the query-rewrite prompt against the json_mode structured-output requirement.

The rewrite node builds its own System/Human messages and binds the schema with the owner's binder (the core's
``with_structured_output_compat``). For DeepSeek thinking mode that wrapper falls back to method=json_mode, which never sees the
pydantic field descriptions — so the editable prompt MUST itself name every ``QueryRewrite`` field,
or the model would emit JSON missing those fields. This test fails loudly if a field is added to
the schema without being described in the default prompt.
"""

from __future__ import annotations

from hiro_memory.knowledge.agent.helpers import QueryRewrite
from hiro_memory.knowledge.settings import (
    DEFAULT_KNOWLEDGE_ANSWERING_PROMPT,
    DEFAULT_KNOWLEDGE_REWRITE_PROMPT,
    KnowledgeSettings,
)


def test_default_rewrite_prompt_describes_every_query_rewrite_field() -> None:
    for field_name in QueryRewrite.model_fields:
        assert field_name in DEFAULT_KNOWLEDGE_REWRITE_PROMPT, (
            f"DEFAULT_KNOWLEDGE_REWRITE_PROMPT must mention `{field_name}` so json_mode "
            "(DeepSeek thinking) gets the JSON shape — pydantic field descriptions never reach it."
        )


def test_default_rewrite_prompt_mentions_json() -> None:
    # OpenAI-compatible json_object mode (DeepSeek) requires the word "json" in the prompt.
    assert "json" in DEFAULT_KNOWLEDGE_REWRITE_PROMPT.lower()


def test_bundled_default_prompts_load_and_back_the_settings() -> None:
    assert DEFAULT_KNOWLEDGE_REWRITE_PROMPT.strip()
    assert DEFAULT_KNOWLEDGE_ANSWERING_PROMPT.strip()
    settings = KnowledgeSettings()
    assert settings.rewrite.prompt == DEFAULT_KNOWLEDGE_REWRITE_PROMPT
    assert settings.answering.prompt == DEFAULT_KNOWLEDGE_ANSWERING_PROMPT
