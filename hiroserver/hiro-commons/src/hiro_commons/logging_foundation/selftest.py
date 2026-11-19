"""The capture self-test: raise each kind of failure the safety nets catch, and check each reached the process's file.

Run in a process that is set up (an app's tests: its contract runs it on the app's own setup), it proves the nets are
wired there, not only that the foundation could wire them:

    results = logging_foundation.self_test(startup=events.bind)   # {"uncaught": True, "thread": True, ...}

`startup` is what the process runs first on its event loop (the backend kit's `events.bind()`, which calls
`watch_loop()`); the failed-task check runs it on a loop of its own, so the loop is watched as the process's own is.

Each check leaves one line of its own in the file, marked with a word no other line has. Nothing is crashed for real:
a native crash is checked by faulthandler being on and pointed at `crash.log`.
"""

from __future__ import annotations

import asyncio
import faulthandler
import gc
import json
import logging
import subprocess
import sys
import threading
import uuid
import warnings
from collections.abc import Callable
from typing import Any

NETS = ("uncaught", "thread", "unraisable", "task", "warning", "library", "web_server", "native_crash", "child")


def _boom(word: str) -> BaseException:
    try:
        raise RuntimeError(word)
    except RuntimeError as exc:
        return exc


class _FailsWhenCollected:
    def __init__(self, word: str) -> None:
        self.word = word

    def __del__(self) -> None:
        raise RuntimeError(self.word)


def _lines() -> list[dict[str, Any]]:
    from . import _state, daily

    f = _state.file
    if f is None:
        return []
    found = []
    for _day, path in daily.files(f.folder, f.name_)[:2]:  # today's, and yesterday's around midnight
        for text in path.read_text(encoding="utf-8").splitlines():
            try:
                found.append(json.loads(text))
            except ValueError:
                continue
    return found


def _has(lines: list[dict[str, Any]], word: str, *, traceback: bool = True) -> bool:
    for got in lines:
        text = json.dumps(got, ensure_ascii=False)
        if word in text:
            return not traceback or "Traceback" in str((got.get("Attributes") or {}).get("exception.stacktrace", ""))
    return False


def _failed_task(word: str, startup: Callable[[], Any] | None) -> None:
    async def fails() -> None:
        raise RuntimeError(word)

    async def main() -> None:
        if startup is not None:
            startup()
        task = asyncio.get_running_loop().create_task(fails(), name=f"selftest-{word}")
        await asyncio.sleep(0)  # it runs and fails
        await asyncio.sleep(0)
        del task  # nobody awaits it: "Task exception was never retrieved", when it is collected
        gc.collect()

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(main())
    finally:
        loop.close()
    gc.collect()


def run(startup: Callable[[], Any] | None = None) -> dict[str, bool]:
    """Each net's result: True when its failure reached the file."""
    from . import _state, child_log, flush

    if _state.file is None:
        raise RuntimeError("logging_foundation.self_test() before setup()")
    words = {net: f"selftest-{net}-{uuid.uuid4().hex[:8]}" for net in NETS}

    exc = _boom(words["uncaught"])
    sys.excepthook(type(exc), exc, exc.__traceback__)  # what Python calls for an exception nobody caught

    def dies() -> None:
        raise RuntimeError(words["thread"])

    t = threading.Thread(target=dies, name=words["thread"])
    t.start()
    t.join()

    _FailsWhenCollected(words["unraisable"])  # dropped at once: its __del__ raises where nothing can catch it
    gc.collect()

    _failed_task(words["task"], startup)

    # Warnings are captured when logging.captureWarnings(True) is on. A test runner (pytest) puts its own recorder in
    # warnings.showwarning for each test, so the warning goes through logging's own hook here, as it does in a process.
    captured = getattr(logging, "_warnings_showwarning", None) is not None
    with warnings.catch_warnings():
        warnings.simplefilter("always")
        if captured:
            warnings.showwarning = logging._showwarning  # type: ignore[attr-defined]
        warnings.warn(words["warning"], RuntimeWarning, stacklevel=1)

    logging.getLogger("selftest.library").warning("A library's problem: %s", words["library"], exc_info=_boom(words["library"]))
    logging.getLogger("uvicorn.error").error("Exception in ASGI application: %s", words["web_server"],
                                             exc_info=_boom(words["web_server"]))

    with child_log("selftest") as out:
        subprocess.run([sys.executable, "-c", f"import sys; print({words['child']!r}); sys.stderr.write('stderr too\\n')"],
                       stdout=out, stderr=out, check=False, timeout=60)
    child_text = "".join(p.read_text(encoding="utf-8")
                         for _d, p in _child_files())

    flush()
    lines = _lines()
    return {
        "uncaught": _has(lines, words["uncaught"]),
        "thread": _has(lines, words["thread"]),
        "unraisable": _has(lines, words["unraisable"]),
        "task": _has(lines, words["task"]),
        "warning": captured and _has(lines, words["warning"], traceback=False),
        "library": _has(lines, words["library"]),
        "web_server": _has(lines, words["web_server"]),
        "native_crash": faulthandler.is_enabled() and _state.crash_file is not None and not _state.crash_file.closed,
        "child": words["child"] in child_text and "stderr too" in child_text,
    }


def _child_files():
    from . import _state, daily

    f = _state.file
    assert f is not None
    return daily.files(f.folder, f"{f.name_}-selftest", daily.CHILD_SUFFIX)[:2]


def missing(results: dict[str, bool]) -> list[str]:
    """The nets whose failure didn't reach the file."""
    return [net for net, ok in results.items() if not ok]
