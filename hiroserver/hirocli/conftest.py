"""Pytest session-wide configuration for hirocli.

Ensures the shared structlog pipeline is initialized once before any test
imports modules that call ``log.fineinfo(...)`` / ``log.info(...)``. Without
``Logger.setup()`` the lazy-bound logger resolves to ``BoundLoggerFilteringAtNotset``,
which lacks the custom ``fineinfo`` method and raises ``AttributeError`` at runtime.
"""

from __future__ import annotations

from hiro_commons.log import Logger

Logger.set_level("DEBUG")
Logger.setup(console=False)
