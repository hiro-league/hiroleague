"""Pytest session-wide configuration for hirocli.

Ensures the shared structlog pipeline is initialized once before any test
imports modules that call ``log.fineinfo(...)`` / ``log.info(...)``. Without
``Logger.setup()`` the lazy-bound logger resolves to ``BoundLoggerFilteringAtNotset``,
which lacks the custom ``fineinfo`` method and raises ``AttributeError`` at runtime.
"""

from __future__ import annotations

import os

from hiro_commons.log import Logger

# Force LangSmith tracing OFF for the whole test session. The eval runners wrap their
# work in ``traced_run`` spans (``knowledge_eval`` / ``memory_eval_<set>_ingestion`` /
# ``recall``), which is a no-op only when tracing is disabled. Tests drive the runners
# with fakes (no real LLM calls), so with tracing inherited from the dev shell each test
# posts a hollow, empty trace to LangSmith. Clearing the switches here (vs. only when
# unset) guarantees no test ever writes to LangSmith regardless of the developer's env;
# non-test runs are untouched since this only mutates the pytest process environment.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

Logger.set_level("DEBUG")
Logger.setup(console=False)
