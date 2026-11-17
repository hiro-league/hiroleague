"""Pytest session-wide configuration for hiro-memory (the same setup as the core's tests).

Initializes the shared structlog pipeline before any test imports modules that call ``log.fineinfo(...)``:
without ``Logger.setup()`` the lazy-bound logger lacks the custom ``fineinfo`` method and raises
``AttributeError``.
"""

from __future__ import annotations

import os
import signal

from hiro_commons.log import Logger

# Tests drive the engine with fakes; with tracing inherited from the dev shell, each ``traced_run`` span would
# post a hollow trace to LangSmith. Only the pytest process's environment changes.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

Logger.set_level("DEBUG")
Logger.setup(console=False)


def pytest_configure(config) -> None:
    """In a pytest-xdist worker, ignore SIGINT, as scripts/run-tests.sh does for the main process.

    onnxruntime's phantom console Ctrl-C reaches every process on the console, and a worker doesn't inherit the
    main process's SIG_IGN (see the core's ``hirocli/conftest.py``).
    """
    if hasattr(config, "workerinput"):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
