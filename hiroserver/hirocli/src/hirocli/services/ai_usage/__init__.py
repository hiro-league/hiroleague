"""AI usage (Phase 7b): every paid AI call the core makes, counted per hour and kept for good.

``store`` owns the ``ai_calls`` table (record a call, read a range, a profile's counts for its
limits); ``view`` turns stored rows into what the AI usage page shows (names, not ids).
"""

from .store import (
    BILLINGS,
    HIRO_SOURCE,
    KINDS,
    RESULTS,
    ProfileUsage,
    UsageCall,
    profile_usage,
    read_rows,
    record,
    record_async,
)

__all__ = [
    "BILLINGS",
    "HIRO_SOURCE",
    "KINDS",
    "RESULTS",
    "ProfileUsage",
    "UsageCall",
    "profile_usage",
    "read_rows",
    "record",
    "record_async",
]
