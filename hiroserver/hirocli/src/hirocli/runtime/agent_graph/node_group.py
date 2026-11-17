"""NodeGroup — base class for the chat agent graph's cohesive node groups.

The ledger plumbing (auto-wrapping every ``*_node`` method, label prefixes, retry policies, ``mount``) is the memory
library's ``LedgerNodeGroup``, shared with the knowledge engine's node groups. This adds what the chat nodes share:
the ``AgentServices`` container and the preferences view.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hiro_memory.ledger.node_group import LedgerNodeGroup

from ...domain.preferences import DEFAULT_MAX_HISTORY_MESSAGES
from .preferences_view import PreferencesView

if TYPE_CHECKING:
    from .services import AgentServices

TRIMMED_MESSAGE_LIMIT = DEFAULT_MAX_HISTORY_MESSAGES


class NodeGroup(LedgerNodeGroup):
    """A chat node group: ledger plumbing (``LedgerNodeGroup``) plus ``AgentServices`` and the preferences view.

    The live ledger sink is ``services.ledger_sink`` (tests + hot-swap).
    """

    def __init__(self, services: "AgentServices") -> None:
        super().__init__(services)
        self.services = services
        self.prefs = PreferencesView(services.preferences, services.workspace_path)

    def _wrap_dynamic_node(self, node_name: str, fn):
        from hiro_memory.ledger import wrap_graph_callable

        return wrap_graph_callable(self, node_name, fn)
