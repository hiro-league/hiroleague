"""STT providers apply the workspace call policy in one retry layer (SDK retries off)."""

from __future__ import annotations

from hirocli.domain.model_http import ProviderCallPolicy, gemini_single_attempt_http_options
from hirocli.services.stt.gemini_provider import GeminiSTTProvider
from hirocli.services.stt.openai_provider import OpenAISTTProvider


def test_providers_default_to_the_default_policy() -> None:
    for cls in (GeminiSTTProvider, OpenAISTTProvider):
        assert cls(api_key="k")._policy == ProviderCallPolicy()


def test_providers_keep_the_given_policy() -> None:
    policy = ProviderCallPolicy(timeout_s=30, max_retries=0)
    for cls in (GeminiSTTProvider, OpenAISTTProvider):
        provider = cls(api_key="k", policy=policy)
        assert provider._policy.attempts == 1


def test_gemini_http_options_carry_the_timeout_in_ms_and_no_sdk_retry() -> None:
    opts = gemini_single_attempt_http_options(ProviderCallPolicy(timeout_s=30, max_retries=4))
    assert opts.timeout == 30_000
    assert opts.retry_options.attempts == 1
