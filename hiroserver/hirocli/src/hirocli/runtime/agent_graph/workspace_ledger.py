"""The core's run ledger: the memory engine's ``LedgerSink`` with the core's prices and AI usage.

Every ledger the core opens goes through here, so each node row is priced from the model catalog and
counted in the workspace's AI usage (Phase 7b), as before the ledger moved into ``hiro_memory``.
"""

from __future__ import annotations

from pathlib import Path

from hiro_memory.ledger import LedgerSink

from hirocli.domain.model_catalog import get_model_catalog
from hirocli.services.ai_usage.from_ledger import count_ledger_row


def workspace_ledger_sink(workspace_path: Path) -> LedgerSink:
    """A ledger for ``<workspace>/logs/graph.log`` that prices and counts every row."""
    return LedgerSink(workspace_path, catalog_loader=get_model_catalog, on_row=count_ledger_row)
