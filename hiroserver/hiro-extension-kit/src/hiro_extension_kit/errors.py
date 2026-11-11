"""The app's errors: the types, the one way to log a caught one, and the one place that turns every
error into an HTTP answer. The rule: each app's docs/backend-best-practices.md, section 5.

Every expected error is an `AppError`: its message is for the user, its `status` the HTTP answer.

| Error                         | Status | When                                                        |
|-------------------------------|--------|-------------------------------------------------------------|
| `Invalid`                     | 400    | the request breaks one of the app's rules                   |
| `NotFound`                    | 404    | what it names doesn't exist                                 |
| `Busy`                        | 409    | something that needs the same thing is running already      |
| `Unavailable`                 | 503    | not possible right now (not set up, the database is busy)   |
| `OutsideError`                | 502    | an outside system failed; one subclass per system, defined  |
|                               |        | by the app's client for it (HA, Frigate, the core's AI...)  |

Anything else is unexpected: a 500 whose traceback is logged. Every answer is
`{"detail": "<what went wrong, in words>"}`, like FastAPI's own HTTPException.
"""

import functools
import inspect
import logging
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, TypeVar

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from . import identity


F = TypeVar("F", bound=Callable[..., Any])


class AppError(Exception):
    """An error the app expects. The message is shown to the user as is."""

    status = 500

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        if status is not None:
            self.status = status


class Invalid(AppError):
    """The request breaks one of the app's rules (400)."""

    status = 400


class NotFound(AppError):
    """What the request names doesn't exist (404)."""

    status = 404


class NotSignedIn(AppError):
    """The app doesn't know who is asking: not signed in (401)."""

    status = 401


class NotAllowed(AppError):
    """The user is known, but their role doesn't allow this (403)."""

    status = 403


class Busy(AppError):
    """Something that needs the same thing is running already (409)."""

    status = 409


class Conflict(AppError):
    """What the request would save was changed elsewhere since it was read (409)."""

    status = 409


class Unavailable(AppError):
    """Not possible right now: not set up yet, the database is busy (503)."""

    status = 503


class OutsideError(AppError):
    """An outside system failed (502). Each system has its own subclass, raised only by its client."""

    status = 502


def database_busy(exc: BaseException) -> bool:
    """SQLite's "database is locked": another write held it past the busy timeout. Worth a retry."""
    cause = exc.orig if isinstance(exc, OperationalError) else exc
    return isinstance(cause, sqlite3.OperationalError) and "locked" in str(cause)


def expected(exc: BaseException) -> bool:
    return isinstance(exc, AppError) or database_busy(exc)


def failed(logger: logging.Logger, what: str, exc: BaseException) -> None:
    """Log a caught error, once, where it was caught: an expected one as a one-line WARNING, anything
    else as an ERROR with its traceback."""
    if expected(exc):
        logger.warning("%s: %s", what, str(exc) or type(exc).__name__)
    else:
        logger.error("%s: %s: %s", what, type(exc).__name__, exc, exc_info=exc)


def guarded(logger: logging.Logger, what: str) -> Callable[[F], F]:
    """For callbacks that must never raise into their caller: another library's thread (paho)
    or a hook the app calls in a loop. A failure is logged with `failed()`, and the call returns None."""

    def wrap(fn: F) -> F:
        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def run_async(*args: Any, **kwargs: Any) -> Any:
                try:
                    return await fn(*args, **kwargs)
                except Exception as exc:
                    failed(logger, what, exc)
                    return None

            return run_async  # type: ignore[return-value]

        @functools.wraps(fn)
        def run(*args: Any, **kwargs: Any) -> Any:
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                failed(logger, what, exc)
                return None

        return run  # type: ignore[return-value]

    return wrap


# What reading an answer can raise when it isn't what was expected.
UNREADABLE = (ValueError, KeyError, IndexError, TypeError, AttributeError)


@contextmanager
def translate(error: Callable[[str], AppError], message: str,
              catch: tuple[type[BaseException], ...] = UNREADABLE) -> Iterator[None]:
    """Turn what reading an outside system's answer can raise (not JSON, a missing field, a picture
    that doesn't decode: pass the library's own error in `catch`) into that system's error."""
    try:
        yield
    except catch as exc:
        raise error(f"{message} ({type(exc).__name__}: {exc})") from exc


def install(app: FastAPI) -> None:
    # The app's logger is read here, not when the module loads: an app's config.py may raise these errors, and it is
    # read before the app can say which app it is (identity.setup needs the config's folders).
    log = identity.logger("errors")

    async def expected_answer(request: Request, exc: Exception) -> JSONResponse:
        status = exc.status if isinstance(exc, AppError) else 500
        if status >= 500:  # an outside system failed, or it's unavailable: worth a line in the errors log
            failed(log, f"{request.method} {request.url.path}", exc)
        return JSONResponse({"detail": str(exc) or type(exc).__name__}, status_code=status)

    async def database(request: Request, exc: Exception) -> JSONResponse:
        if database_busy(exc):
            failed(log, f"{request.method} {request.url.path}: the database is busy", exc)
            return JSONResponse({"detail": "The database is busy. Try again in a moment."}, status_code=503)
        # Answered here: Starlette doesn't raise it again (it does for Exception), so log the traceback.
        log.error("%s %s failed: %s: %s", request.method, request.url.path, type(exc).__name__, exc, exc_info=exc)
        return _unexpected_answer(exc)

    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Starlette raises it again after this answer, so uvicorn logs the traceback ("Exception in ASGI
        # application", in <app>-errors.log); this line says which request it was.
        log.error("%s %s failed: %s: %s", request.method, request.url.path, type(exc).__name__, exc)
        return _unexpected_answer(exc)

    app.add_exception_handler(AppError, expected_answer)
    app.add_exception_handler(OperationalError, database)
    app.add_exception_handler(Exception, unexpected)


def _unexpected_answer(exc: Exception) -> JSONResponse:
    app = identity.app()
    return JSONResponse({"detail": f"{app.title} hit an unexpected error ({type(exc).__name__}). "
                                   f"The details are in {app.name}-errors.log."}, status_code=500)
