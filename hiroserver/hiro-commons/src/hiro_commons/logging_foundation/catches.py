"""The silent-catch scan: every broad `except` that drops its error, so nothing escapes the log by habit.

    from hiro_commons.logging_foundation.catches import silent_catches
    assert not silent_catches(Path("src/myapp"))

A broad `except` (bare, `Exception`, `BaseException`) must log (a logger's method, or the backend kit's `failed()`) or
raise again somewhere in its own code: an error it swallows is lost for good. ruff's S110 and S112 catch the plainest
form (`except: pass`, `except: continue`); this scan catches the rest (`except Exception: return None`). ruff's own
blind-except rule can't tell `failed()` is a log line, so the scan is ours.

Every Hiro League repo runs it: each app through the backend kit's contract, CodeHiro in its tests, the core in
hiro-commons' tests over each of its packages.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

_BROAD = {"Exception", "BaseException"}
# A logger's methods, the backend kit's failed(), and a logging handler's own way to report its failure (handleError:
# a handler can't log through itself)
_LOG_CALLS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log", "fineinfo", "failed", "handleError"}


def _broad(kind: ast.expr | None) -> bool:
    if kind is None:
        return True  # a bare `except:`
    if isinstance(kind, ast.Name):
        return kind.id in _BROAD
    if isinstance(kind, ast.Attribute):
        return kind.attr in _BROAD
    if isinstance(kind, ast.Tuple):
        return any(_broad(k) for k in kind.elts)
    return False


def _keeps_the_error(body: list[ast.stmt], calls: frozenset[str] | set[str] = frozenset(_LOG_CALLS)) -> bool:
    """The handler raises, or logs (a logger's method, or errors.failed), somewhere in its own code."""
    todo: list[ast.AST] = list(body)
    while todo:
        node = todo.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue  # code defined here runs later, if ever
        if isinstance(node, ast.Raise):
            return True
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else ""
            if name in calls:
                return True
        todo.extend(ast.iter_child_nodes(node))
    return False


def is_test(path: Path) -> bool:
    """A test module (tests that sit beside the code, as the core's do, are left out of a scan that asks)."""
    return path.name.startswith("test_") or path.name == "conftest.py" or "tests" in path.parts


def silent_catches(package: Path, *, skip: Iterable[str] = ("migrations",), tests: bool = True,
                   log_calls: Iterable[str] = ()) -> list[tuple[Path, int]]:
    """Every broad `except` in the package's code that drops its error: where it is. Folders whose name starts with
    one of `skip` are left out (generated migrations); `tests=False` leaves test modules out too. `log_calls` names a
    package's own helpers that log the error they are given (the SDK's workers' `report`)."""
    found = []
    skipped = tuple(skip)
    calls = _LOG_CALLS | set(log_calls)
    for path in sorted(Path(package).rglob("*.py")):
        rel = path.relative_to(package)
        if any(part.startswith(skipped) for part in rel.parts) or (not tests and is_test(rel)):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        found += [(path, node.lineno) for node in ast.walk(tree)
                  if isinstance(node, ast.ExceptHandler) and _broad(node.type) and not _keeps_the_error(node.body, calls)]
    return found
