"""Pytest session-wide configuration for hirocli.

Ensures the shared structlog pipeline is initialized once before any test
imports modules that call ``log.fineinfo(...)`` / ``log.info(...)``. Without
``Logger.setup()`` the lazy-bound logger resolves to ``BoundLoggerFilteringAtNotset``,
which lacks the custom ``fineinfo`` method and raises ``AttributeError`` at runtime.
"""

from __future__ import annotations

import os
import signal

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


def pytest_configure(config) -> None:
    """In a pytest-xdist worker, ignore SIGINT, as scripts/run-tests.sh does for the main process.

    The phantom console Ctrl-C that onnxruntime's handler sends mid-suite (run-tests.sh says why) reaches every
    process on the console, and a worker doesn't inherit the main process's SIG_IGN: in parallel runs every worker
    died of a KeyboardInterrupt about 80% through. Workers still stop with the run: Ctrl-Break or closing the
    terminal ends the main process, and xdist ends its workers.
    """
    if hasattr(config, "workerinput"):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
