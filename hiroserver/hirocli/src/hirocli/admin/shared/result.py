"""Uniform service return type for admin services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass
class Result(Generic[T]):
    """Service outcome: success with optional data, or failure with a message."""

    ok: bool
    data: T | None = None
    error: str | None = None

    @staticmethod
    def success(data: T | None = None) -> Result[T]:
        return Result(ok=True, data=data, error=None)

    @staticmethod
    def failure(message: str) -> Result[T]:
        return Result(ok=False, data=None, error=message)

    # Alias matching guidelines wording (§1.3 "Result.fail").
    fail = failure
