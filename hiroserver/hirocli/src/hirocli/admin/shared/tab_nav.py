"""Shared navigation request for tabbed pages (guidelines §1.6)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TabNavRequest:
    """Parsed from URL query params by the page function.

    The page function signature declares FastAPI-style query params with defaults,
    then constructs a TabNavRequest and passes it to the controller.
    """

    tab: str | None = None
    filters: dict[str, str | None] = field(default_factory=dict)

    def filter_for(self, tab: str) -> dict[str, str | None]:
        """Returns filters only when this request targets the given tab."""
        if self.tab == tab:
            return {k: v for k, v in self.filters.items() if v is not None}
        return {}
