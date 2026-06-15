"""Guard the query-rewrite prompt against the json_mode structured-output requirement.

The rewrite node builds its own System/Human messages and calls ``with_structured_output_compat``.
For DeepSeek thinking mode that wrapper falls back to method=json_mode, which never sees the
pydantic field descriptions — so the editable prompt MUST itself name every ``QueryRewrite`` field,
or the model would emit JSON missing those fields. This test fails loudly if a field is added to
the schema without being described in the default prompt.
"""

from __future__ import annotations

from hirocli.domain.preferences import DEFAULT_KNOWLEDGE_REWRITE_PROMPT
from hirocli.services.knowledge.agent.helpers import QueryRewrite


def test_default_rewrite_prompt_describes_every_query_rewrite_field() -> None:
    for field_name in QueryRewrite.model_fields:
        assert field_name in DEFAULT_KNOWLEDGE_REWRITE_PROMPT, (
            f"DEFAULT_KNOWLEDGE_REWRITE_PROMPT must mention `{field_name}` so json_mode "
            "(DeepSeek thinking) gets the JSON shape — pydantic field descriptions never reach it."
        )


def test_default_rewrite_prompt_mentions_json() -> None:
    # OpenAI-compatible json_object mode (DeepSeek) requires the word "json" in the prompt.
    assert "json" in DEFAULT_KNOWLEDGE_REWRITE_PROMPT.lower()
