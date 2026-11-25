"""What every app's tests are built on (backend kit, step 2): each app's tests/conftest.py and tests/fakes.py had a copy.

- `guard_network()`: tests reach nothing beyond this computer; a test that forgets a fake fails instead of reaching
  Home Assistant, Frigate or a paid provider. On Windows each local connection also starts from a port of its own.
- `RunLog`: every run kept in one log for the whole computer, with each failure's traceback.
- `CleanDatabases`: every test starts from empty, migrated databases.
- `wait_until()`: poll until something is true.
- `FakeCore` and `FakeLink`: the HiroLeague core as an app asks it (the family list, roles, `answers` for anything else,
  and other extensions' answers to `ask()`), held to what the app is approved for and to the person signed in, by the
  SDK's table (Permissions phase 8).
- `join_family()`, `ai_answer()`, `ai_profiles()`: someone added to the fake core's family list and synced; the core's AI
  answers (shared-code plan, step 1).

What every app's tests check of the app itself is contract.py.

Imported only by tests: it needs pytest, which an app installs as a dev tool.
"""

from __future__ import annotations

import asyncio
import asyncio.proactor_events
import asyncio.selector_events
import copy
import itertools
import random
import shutil
import socket
import sys
import textwrap
import time
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from hiro_channel_sdk.approvals import (ALWAYS, APP_METHODS, APPS_ASK, NEVER, NOT_ALLOWED, NOT_APPROVED,
                                        NOT_ON_ITS_OWN, OWNER_ONLY, PARAM_SIGNED_IN, PEOPLE_ACT, SIGN_IN_AGAIN,
                                        SITE_NAME, WORDS)
from hiro_channel_sdk.constants import (METHOD_AUTH_CODE, METHOD_AUTH_END, METHOD_EXTENSIONS_ASK, METHOD_PEOPLE_ADD, METHOD_PEOPLE_LIST,
                                        METHOD_PEOPLE_UPDATE, METHOD_ROLES_IMPORT_RIGHTS)

from .db import Database

# --- no network beyond this computer -----------------------------------------------------------------------------

LOCAL = {"127.0.0.1", "::1", "localhost"}

# Windows picks our side's port of a local connection, and keeps coming back to the lowest ones (49152…).
# With the port on the other side also used before, that pair of ports can belong to a connection closed
# seconds ago, which Windows still holds (TIME_WAIT, 2 minutes): the new connection then fails with "address
# in use" (WinError 10048; 52 through asyncio). A run makes hundreds of local connections (the fakes, and
# every new event loop connects to itself), so about one full run in ten had a test fail ("All connection
# attempts failed", "Cannot reach Home Assistant") and some runs hung for good (a new event loop waiting for
# its own connection). Found 2026-09-30 in HomeHiro. So on Windows each local connection starts from a port of
# our own, outside Windows' range (49152-65535), taken in a shuffled order: the same pair doesn't come back.
_OWN_PORTS = random.sample(range(20000, 40000), 20000)
_next_own = itertools.count()
_guarded = False


def _own_port(sock: socket.socket) -> None:
    if sys.platform != "win32" or sock.type != socket.SOCK_STREAM or sock.family not in (socket.AF_INET, socket.AF_INET6):
        return
    try:
        if sock.getsockname()[1]:
            return  # bound by its owner
    except OSError:  # not bound yet (Windows says so with an error)
        pass
    host = "127.0.0.1" if sock.family == socket.AF_INET else "::1"
    for _ in range(100):
        try:
            sock.bind((host, _OWN_PORTS[next(_next_own) % len(_OWN_PORTS)]))
            return
        except OSError:  # in use (another run, another program) or reserved by Windows: the next one
            continue


def _host(address) -> str:
    return address[0] if isinstance(address, tuple) else str(address)


def _refuse(address) -> RuntimeError:
    return RuntimeError(f"Tests may not use the network (tried {address}); use a fake instead")


def guard_network() -> None:
    """Refuse every connection beyond this computer, for the rest of the process. Called once, at the top of an
    app's tests/conftest.py (a second call changes nothing)."""
    global _guarded
    if _guarded:
        return
    _guarded = True
    connect, connect_ex = socket.socket.connect, socket.socket.connect_ex

    def local_only(sock: socket.socket, address, *, check=connect):
        # Unix sockets and this computer (asyncio's own socket pairs use it) stay allowed.
        if sock.family in (socket.AF_INET, socket.AF_INET6) and _host(address) not in LOCAL:
            raise _refuse(address)
        _own_port(sock)
        return check(sock, address)

    socket.socket.connect = lambda self, address: local_only(self, address)  # type: ignore[method-assign]
    socket.socket.connect_ex = lambda self, address: local_only(self, address, check=connect_ex)  # type: ignore[method-assign]

    # asyncio (websockets, async httpx) connects without socket.connect on Windows, but every connection
    # first looks its address up, numbers included.
    getaddrinfo = socket.getaddrinfo

    def getaddrinfo_local(host, *args, **kwargs):
        if host is not None and (host.decode() if isinstance(host, bytes) else str(host)) not in LOCAL:
            raise _refuse(host)
        return getaddrinfo(host, *args, **kwargs)

    socket.getaddrinfo = getaddrinfo_local

    # ...but not for a numeric address: asyncio then connects straight through the loop's sock_connect
    # (ConnectEx on Windows), which every async connection ends up in.
    for loop_class in (asyncio.proactor_events.BaseProactorEventLoop, asyncio.selector_events.BaseSelectorEventLoop):
        loop_connect = loop_class.sock_connect

        async def sock_connect(self, sock, address, _check=loop_connect):
            if sock.family in (socket.AF_INET, socket.AF_INET6) and _host(address) not in LOCAL:
                raise _refuse(address)
            _own_port(sock)
            return await _check(self, sock, address)

        loop_class.sock_connect = sock_connect  # type: ignore[method-assign]

    # Pings (ICMP) and the DHCP check send without connecting.
    sendto = socket.socket.sendto

    def sendto_local(self, data, *args):
        address = args[-1]
        if self.family in (socket.AF_INET, socket.AF_INET6) and _host(address) not in LOCAL:
            raise _refuse(address)
        return sendto(self, data, *args)

    socket.socket.sendto = sendto_local  # type: ignore[method-assign]


# --- every run kept in one log -----------------------------------------------------------------------------------


class RunLog:
    """A pytest plugin: every run is kept in one log for the whole computer, with each failure's traceback, so a run
    whose output was cut (`pytest -q | tail -1`), or whose worktree is gone, still says which test failed and why.
    (Twice on 2026-09-30 a run said only "1 failed" and the test was never known.)

    An app registers it in its conftest.py: `config.pluginmanager.register(RunLog(path))` in `pytest_configure`."""

    KEEP_BYTES = 2_000_000  # past this, the older half goes

    def __init__(self, path: Path) -> None:
        self.path = path
        self.started = time.monotonic()
        self.at = datetime.now().astimezone()
        self.running: str | None = None
        self.failures: list[str] = []

    def pytest_runtest_logstart(self, nodeid, location) -> None:
        self.running = nodeid

    def pytest_runtest_logreport(self, report) -> None:
        if report.failed:
            trace = "\n".join(report.longreprtext.splitlines()[-80:])
            self.failures.append(f"FAILED {report.nodeid} ({report.when})\n" + textwrap.indent(trace, "    "))

    def pytest_collectreport(self, report) -> None:
        if report.failed:
            self.failures.append(f"ERROR collecting {report.nodeid}\n" + textwrap.indent(report.longreprtext, "    "))

    def pytest_sessionfinish(self, session, exitstatus) -> None:
        import pytest

        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        stats = reporter.stats if reporter else {}
        counts = ", ".join(f"{len(stats[k])} {k}" for k in ("failed", "error", "passed", "skipped") if stats.get(k)) or "no tests"
        head = (f"{self.at.isoformat(timespec='seconds')}  {counts} in {time.monotonic() - self.started:.1f} s  "
                f"(exit {int(exitstatus)})  {Path.cwd()}  {' '.join(session.config.invocation_params.args)}")
        lines = [head, *self.failures]
        if int(exitstatus) == pytest.ExitCode.INTERRUPTED:
            lines.append(f"STOPPED during {self.running}")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size > self.KEEP_BYTES:
                kept = self.path.read_text(encoding="utf-8", errors="replace")[-self.KEEP_BYTES // 2:]
                self.path.write_text(kept[kept.find("\n") + 1:], encoding="utf-8")
            with self.path.open("a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n\n")
        except OSError as e:  # a run is never failed by its own log
            print(f"\nCould not keep this run in {self.path}: {e}", file=sys.stderr)
        else:
            if self.failures:
                print(f"\nFailures kept in {self.path}", file=sys.stderr)


# --- every test from empty, migrated databases --------------------------------------------------------------------


class CleanDatabases:
    """The app's databases, migrated once per run and copied to `clean`; `restore()` puts that copy back before each
    test, so what one test leaves can't affect another.

    `prepare()` refuses a database outside `data_dir` (the run's own folder): a shell set up for a test server points
    DATA_DIR at a copy of real data, and the tests delete whole tables."""

    def __init__(self, data_dir: Path, databases: Iterable[Database]) -> None:
        self.data_dir = data_dir
        self.databases = list(databases)
        self.clean = data_dir / "clean"

    def prepare(self) -> None:
        self.clean.mkdir(exist_ok=True)
        for d in self.databases:
            path = d.path.resolve()
            assert self.data_dir.resolve() in path.parents, f"tests would use {path}, not the test folder {self.data_dir}"
            d.migrate()
            d.engine.dispose()  # closes every connection, so the file is complete (WAL written back)
            shutil.copyfile(path, self.clean / path.name)

    def restore(self) -> None:
        for d in self.databases:
            d.engine.dispose()
            for leftover in (d.path.with_name(d.path.name + "-wal"), d.path.with_name(d.path.name + "-shm")):
                leftover.unlink(missing_ok=True)
            shutil.copyfile(self.clean / d.path.name, d.path)

    def close(self) -> None:
        for d in self.databases:
            d.engine.dispose()


# --- small helpers -----------------------------------------------------------------------------------------------


def auth(monkeypatch, on: bool) -> None:
    """Sign-in on or off for one test (the app's Extension.auth; its tests run with AUTH=off)."""
    from dataclasses import replace

    from . import extension

    monkeypatch.setattr(extension, "_extension", replace(extension.ext(), auth=on))


def outputs(monkeypatch, on: bool) -> None:
    """Sending on or off for one test (the app's Extension.outputs; its tests run with OUTPUTS=off)."""
    from dataclasses import replace

    from . import extension

    monkeypatch.setattr(extension, "_extension", replace(extension.ext(), outputs=on))


def wait_until(condition: Callable[[], Any], timeout: float = 5.0, what: str = "condition") -> Any:
    """Poll `condition` until it is truthy (returns its value) or fail after `timeout` seconds."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if value := condition():
            return value
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


# --- the HiroLeague core -----------------------------------------------------------------------------------------


def _answer(answer: Any, params: dict[str, Any]) -> Any:
    if callable(answer) and not isinstance(answer, BaseException):
        answer = answer(params)
    if isinstance(answer, BaseException):
        raise answer
    return copy.deepcopy(answer)


def _refused(code: str, message: str) -> Exception:
    from hiro_channel_sdk import ExtensionRequestError

    return ExtensionRequestError(code, message)


class FakeCore:
    """The HiroLeague core as an app asks it: the SDK client's `connected`, `request()` and `ask()`.

    `request()` answers people.* like the core's contract (hiro_channel_sdk.constants), refusals as
    ExtensionRequestError("invalid_params", reason), and `auth.code` for a code `sign_in_code()` handed out, with the
    person's proof (`token`). Other methods answer from `answers` (a dict, an exception to raise, or a function of the
    params that returns or raises one). Every request is kept in `asked`, with its timeout in `timeouts`, without the
    person's proof (`_signed_in`), which is kept in `signed_in` as (method, token).

    Permissions phase 8: every request and ask is first held to the SDK's table (approvals.APP_METHODS), as the core
    holds it: no app adds, renames or removes a role, nor gives or takes the Owner role (`not_allowed`); a method that
    needs a person (people.add, ai.uses.set...) answers by the person whose proof it carries (`sign_in_again` for a
    proof it never gave). `approved` is what the owner approved the app for: None (the default) is everything, as an
    app paired before approvals; a test sets a list of permissions (or (permission, subject) pairs: ("apps.ask",
    "home")), and a method needing one that isn't in it answers `not_approved`.

    `ask(to, method, params)` answers what another extension offers, from `extensions[to][method]` the same way; an
    extension in `away` (or not in `extensions`) is not connected, as the core answers. Kept in `asked` as
    ("ask:<method>", params). An app's tests/fakes.py sets its own defaults (the AI's answers, HomeHiro's).

    Each request and ask is also built as the SDK sends it, kept in `frames`: what the core would read, the story's
    id in its metadata included (the contract checks it)."""

    def __init__(self) -> None:
        self.connected = True
        self.asked: list[tuple[str, dict[str, Any]]] = []
        self.timeouts: list[float] = []
        self.answers: dict[str, Any] = {}
        self.extensions: dict[str, dict[str, Any]] = {}
        self.away: set[str] = set()
        self.status_detail: dict[str, Any] = {"core": {"name": "HiroLeague", "version": "0.2.0", "workspace": "default"}}
        self.roles: list[dict[str, Any]] = [{"role_id": "owner", "name": "Owner", "built_in": True},
                                            {"role_id": "adult", "name": "Adult", "built_in": False},
                                            {"role_id": "kid", "name": "Kid", "built_in": False}]
        self.people: list[dict[str, Any]] = []
        self.handlers: dict[str, Any] = {}  # the core's events the app listens to (the SDK's on_event)
        self.events: list[tuple[str, dict[str, Any]]] = []  # the events the app sent the core (send_event)
        self.frames: list[Any] = []  # each request as the SDK builds it (hiro_channel_sdk.extension.build_request)
        # Permissions phase 8: what the app is approved for (None: everything), the proofs given at sign-in (token ->
        # person id), the codes handed out (code -> person id), and each request's proof as (method, token)
        self.approved: list[str | tuple[str, str]] | None = None
        self.tokens: dict[str, str] = {}
        self.codes: dict[str, str] = {}
        self.signed_in: list[tuple[str, str]] = []
        self._n = 0

    def on_event(self, event_type: str, handler: Any) -> None:
        self.handlers[event_type] = handler

    async def send_event(self, event_type: str, data: dict[str, Any] | None = None) -> bool:
        """An event the app sends the core (hiroleague.tell_changed): kept when connected; False when not, as the SDK
        answers (events aren't queued)."""
        if not self.connected:
            return False
        self.events.append((event_type, dict(data or {})))
        return True

    def _frame(self, method: str, params: dict[str, Any]) -> None:
        from hiro_channel_sdk.extension import build_request

        self.frames.append(build_request(method, params, sender_id="app", direction="inbound"))

    def person(self, name: str, role_id: str = "adult", whatsapp: str = "", calls_them: str = "",
               role_ids: list[str] | None = None) -> dict[str, Any]:
        """Add someone to the core's list directly (as its admin or CLI would): one role, or several (`role_ids`)."""
        self._n += 1
        p = {"person_id": f"cp{self._n}", "name": name, "calls_them": calls_them, "whatsapp": whatsapp}
        self.people.append(p)
        self.give(p, role_ids or [role_id])
        return p

    def give(self, person: dict[str, Any], role_ids: list[str]) -> None:
        """Set the roles a person holds, as the core keeps them: in the roles' order, role_id the first."""
        order = [r["role_id"] for r in self.roles]
        held = sorted(dict.fromkeys(role_ids), key=lambda r: order.index(r) if r in order else len(order))
        person["role_ids"], person["role_id"] = held, held[0]

    def _refuse(self, reason: str):
        raise _refused("invalid_params", reason)

    def sign_in_code(self, person: dict[str, Any], code: str = "") -> str:
        """The core signs `person` in and hands the browser a one-time code for the app (`auth.code` redeems it)."""
        self._n += 1
        code = code or f"code{self._n}"
        self.codes[code] = person["person_id"]
        return code

    def _covers(self, permission: str, subject: str = "") -> bool:
        if self.approved is None:
            return True
        return permission in self.approved if not subject else (permission, subject) in self.approved

    def _not_approved(self, permission: str, subject: str = "") -> Exception:
        words = WORDS.get(permission, permission)
        return _refused(NOT_APPROVED, f"This app isn't approved to {words}. The owner approves it on HiroLeague's "
                                      "Extensions page.")

    def _hold(self, method: str, params: dict[str, Any], token: str) -> None:
        """The core's check of an app's ask (hirocli runtime/app_asks.py), on the SDK's table; methods the table
        doesn't name (an app's own test answers) pass."""
        need = APP_METHODS.get(method)
        if need is None or need.app == ALWAYS:
            return
        if need.app == NEVER:
            raise _refused(NOT_ALLOWED, "No app may do this: it is done in HiroLeague's admin.")
        if need.person is not None:
            person_id = self.tokens.get(token) if token else None
            if token and person_id is None:
                raise _refused(SIGN_IN_AGAIN, "Sign in again to do this.")
            if person_id is None:
                if self.approved is None:  # an app from before approvals, with no proof: as before
                    return
                raise _refused(SIGN_IN_AGAIN, "Sign in again to do this.")
            if not self._covers(PEOPLE_ACT):
                raise self._not_approved(PEOPLE_ACT)
            person = self._find(person_id)
            if "owner" in person["role_ids"]:
                return
            if need.person == OWNER_ONLY:
                raise _refused(NOT_ALLOWED, f"{person['name']} may not do this: only the owner can.")
            key = ".".join(need.person)
            if not any(key in (r.get("rights") or []) for r in self.roles if r["role_id"] in person["role_ids"]):
                raise _refused(NOT_ALLOWED, f"{person['name']} may not do this: their roles don't include it.")
            return
        if need.app == NOT_ON_ITS_OWN:
            if self.approved is not None:
                raise _refused(NOT_ALLOWED, "This app can't do this on its own: it notifies people through HiroLeague.")
            return
        subject = (str(params.get("to") or "").strip() if need.app == APPS_ASK
                   else f"{str(params.get('name') or '').strip().lower()}:{params.get('port')}" if need.app == SITE_NAME
                   else "")
        if not self._covers(need.app, subject):
            raise self._not_approved(need.app, subject)

    def _gives_or_takes_owner(self, person_id: str | None, params: dict[str, Any]) -> bool:
        new = params.get("role_ids") or ([params["role_id"]] if params.get("role_id") else None)
        if new is None:
            return False
        old = next((p for p in self.people if p["person_id"] == person_id), None) if person_id else None
        return ("owner" in new) != (old is not None and "owner" in old["role_ids"])

    def _find(self, person_id: str) -> dict[str, Any]:
        p = next((p for p in self.people if p["person_id"] == person_id), None)
        if p is None:
            self._refuse("That person isn't in the family list.")
        return p  # type: ignore[return-value]

    def _check(self, role_ids: list[str] | None, number: str | None, person_id: str | None) -> None:
        for role_id in role_ids or []:
            if not any(r["role_id"] == role_id for r in self.roles):
                self._refuse(f"There is no role {role_id!r}.")
        if number and (other := next((p for p in self.people if p["whatsapp"] == number and p["person_id"] != person_id), None)):
            self._refuse(f"{other['name']} already has that WhatsApp number.")

    async def ask(self, to: str, method: str, params: dict[str, Any] | None = None, *, timeout: float = 15.0) -> dict[str, Any]:
        from hiro_channel_sdk import ExtensionRequestError

        params = dict(params or {})
        self._frame(METHOD_EXTENSIONS_ASK, {"to": to, "method": method, "params": params, "timeout": timeout})
        self.asked.append((f"ask:{method}", params))
        self.timeouts.append(timeout)
        if not self.connected:
            raise ExtensionRequestError("not_connected", "not connected to the core")
        self._hold(METHOD_EXTENSIONS_ASK, {"to": to}, "")
        offers = self.extensions.get(to)
        if offers is None or to in self.away:
            raise ExtensionRequestError("not_connected", f"{to} isn't connected")
        if method not in offers:
            raise ExtensionRequestError("not_offered", f"{to} doesn't offer {method}")
        return _answer(offers[method], params)

    async def request(self, method: str, params: dict[str, Any] | None = None, *, timeout: float = 15.0) -> dict[str, Any]:
        params = dict(params or {})
        self._frame(method, params)
        token = str(params.pop(PARAM_SIGNED_IN, "") or "")  # the core takes the proof out before the method runs
        if token:
            self.signed_in.append((method, token))
        self.asked.append((method, params))
        self.timeouts.append(timeout)
        if not self.connected:
            raise _refused("not_connected", "not connected to the core")
        self._hold(method, params, token)
        if method in self.answers:
            return _answer(self.answers[method], params)
        if method == METHOD_AUTH_CODE:
            person_id = self.codes.pop(str(params.get("code") or ""), None)
            if person_id is None:
                raise _refused("invalid_code", "That code is unknown, used or expired.")
            p = self._find(person_id)
            role = next(r for r in self.roles if r["role_id"] == p["role_id"])
            self._n += 1
            proof = f"proof{self._n}"
            self.tokens[proof] = person_id
            return {"token": proof, "person_id": person_id, "name": p["name"], "role_id": p["role_id"],
                    "role_ids": list(p["role_ids"]), "role_name": role["name"]}
        if method == METHOD_AUTH_END:  # the person signed out of the app: their proof ends
            self.tokens.pop(str(params.get("token") or ""), None)
            return {}
        if method == METHOD_PEOPLE_LIST:
            # Phase 9a: each role with its line and its rights here (none until granted or imported)
            roles = [{"says": "", "rights": [], **r} for r in self.roles]
            return {"people": copy.deepcopy(self.people), "roles": copy.deepcopy(roles)}
        if method == METHOD_ROLES_IMPORT_RIGHTS:
            if "copy_from" in params:  # Phase 9b: rights copied from another extension: none in this fake
                return {"imported": []}
            if "renamed" in params:  # Permissions phase 6: the new keys beside each old one a role holds, like the core
                moved = []
                for r in self.roles:
                    held = list(r.get("rights") or [])
                    added = [k for old in held for k in params["renamed"].get(old, []) if k not in held]
                    if r["role_id"] != "owner" and added:
                        r["rights"] = held + list(dict.fromkeys(added))
                        moved.append(r["role_id"])
                return {"imported": moved}
            # Phase 9a: fills only roles with no rights here yet (and an empty line), like the core
            imported = []
            for role_id, entry in (params.get("roles") or {}).items():
                r = next((r for r in self.roles if r["role_id"] == role_id), None)
                if r is None or role_id == "owner":
                    continue
                if entry.get("says") and not r.get("says"):
                    r["says"] = entry["says"]
                if "rights" not in r:
                    r["rights"] = list(entry.get("rights") or [])
                    imported.append(role_id)
            return {"imported": imported}
        if method in (METHOD_PEOPLE_ADD, METHOD_PEOPLE_UPDATE) and self._gives_or_takes_owner(
                params.get("person_id") if method == METHOD_PEOPLE_UPDATE else None, params):
            raise _refused(NOT_ALLOWED, "No app gives or takes the Owner role: that is done in HiroLeague's admin.")
        if method == METHOD_PEOPLE_ADD:
            if not str(params.get("name") or "").strip():
                self._refuse("Name is empty.")
            role_ids = params.get("role_ids") or [params.get("role_id") or ""]
            self._check(role_ids, params.get("whatsapp"), None)
            p = self.person(params["name"], whatsapp=params.get("whatsapp") or "", calls_them=params.get("calls_them") or "",
                            role_ids=role_ids)
            return {"person": dict(p)}
        if method == METHOD_PEOPLE_UPDATE:
            p = self._find(params["person_id"])
            role_ids = params.get("role_ids") or ([params["role_id"]] if params.get("role_id") is not None else None)
            self._check(role_ids, params.get("whatsapp"), p["person_id"])
            for k in ("name", "calls_them", "whatsapp"):
                if params.get(k) is not None:
                    p[k] = params[k]
            if role_ids is not None:
                self.give(p, role_ids)
            return {"person": dict(p)}
        raise AssertionError(f"FakeCore: nothing answers {method}")


class FakeLink:
    """The app's `hiroleague.link` as its feature modules use it: its client, its settings store (the app's database
    unless a test hands one), and what Settings → HiroLeague reads."""

    def __init__(self, client: Any, settings: Any = None) -> None:
        from .hiroleague import AppDatabase

        self.client = client
        self.settings = settings if settings is not None else AppDatabase()
        self.followed: dict[str, Any] = {}  # resource -> the read that keeps its copy (follow.py); a test calls it

    def follow(self, resource: str, refresh: Any) -> Any:
        self.followed[resource] = refresh
        return lambda: self.followed.pop(resource, None)

    def status(self) -> dict[str, Any]:
        from .hiroleague import waiting_items

        return {"url": "ws://127.0.0.1:18082", "status": "connected" if self.client.connected else "disconnected",
                "error": None, "core": self.client.status_detail.get("core") if self.client.connected else None,
                "waiting": waiting_items(self.approval)}

    # What the owner approved the app for, as the link keeps it (Permissions phase 8): None, the core said nothing
    approval: Any = None

    def approved_for(self, permission: str, subject: str = "") -> bool:
        from .hiroleague import covers

        return covers(self.approval, permission, subject)

    async def ask(self, to: str, method: str, params: dict[str, Any] | None = None, *, timeout: float = 15.0) -> dict[str, Any]:
        from .hiroleague import ask_app

        return await ask_app(self.client, to, method, params, timeout=timeout)


class DictSettings:
    """A settings store of an app's own, as the link is handed one (hiroleague.py `use_settings`, CodeHiro's
    reports.db): plain get and put, "" taking a key away. `kept` is what it holds."""

    def __init__(self, **kept: str) -> None:
        self.kept = dict(kept)

    def get(self, key: str) -> str:
        return self.kept.get(key, "")

    def put(self, key: str, value: str) -> None:
        if value:
            self.kept[key] = value
        else:
            self.kept.pop(key, None)


def join_family(core: FakeCore, name: str, role_id: str = "adult", *, whatsapp: str = "",
                role_ids: list[str] | None = None) -> dict[str, Any]:
    """A new person in the fake core's family list, with one role or several (`role_ids`), and the app's copy synced
    (family.py). Returns the core person. (Shared-code plan, step 1: NetHiro's and TrainHiro's tests/fakes.py each had
    this.)"""
    import asyncio

    from . import family

    p = core.person(name, role_id, whatsapp, role_ids=role_ids)
    asyncio.run(family.sync())
    return p


# --- the core's AI, as `ai.ask` and `ai.profiles` answer (llm/profiles.py, llm/core_ai.py) ---------------------------
# Shared-code plan, step 1: HomeHiro's and NetHiro's tests/fakes.py each had these, apart only in their `uses`.

_AI_ANSWER: dict[str, Any] = {
    "text": '{"answer": "yes"}', "profile_id": "camera", "profile_name": "Camera questions", "provider": "google",
    "model": "gemini-3.8-flash", "plan": False, "ms": 1400, "tokens": 120, "tokens_in": 100, "tokens_out": 20,
    "cost": 0.0012, "estimate": None, "notes": [],
    "tries": [{"profile_id": "camera", "provider": "google", "model": "gemini-3.8-flash", "status": "ok", "ms": 1400}],
}
_AI_PROFILES: list[dict[str, Any]] = [
    {"id": "camera", "label": "Camera questions", "model": "google:gemini-3.8-flash", "model_label": "Gemini 3.8 Flash",
     "provider_label": "Google", "kind": "api", "max_cost_day": 1.0, "at_once": 2, "fallback": "camera-codex",
     "chain": ["camera", "camera-codex"], "today": {"asks": 41, "cost": 0.34, "this_hour": 3}},
    {"id": "camera-codex", "label": "Camera on Codex", "model": "codex:gpt-6.1-sol", "provider_label": "Codex",
     "kind": "plan", "max_per_hour": 30, "chain": ["camera-codex"], "today": {"asks": 2, "this_hour": 2}},
    {"id": "hh-wake1", "label": "Wake word check", "model": "google:gemini-3.5-flash-lite", "provider_label": "Google",
     "kind": "api", "max_cost_day": 0.2},
]


def ai_answer() -> dict[str, Any]:
    """`ai.ask`'s answer: the question answered by the "camera" profile (a fresh copy, for a test to change)."""
    return copy.deepcopy(_AI_ANSWER)


def ai_chat_answer(content: str = "", tool_calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """`ai.chat`'s answer: `ai_answer()`'s, with the next message (its words, or the tools it calls)."""
    answer = copy.deepcopy(_AI_ANSWER)
    answer["text"] = content
    answer["message"] = {"content": content, "tool_calls": copy.deepcopy(tool_calls or [])}
    return answer


def ai_profiles(uses: dict[str, str | None]) -> dict[str, Any]:
    """`ai.profiles`' answer: three profiles, and which one each of the app's uses (`"<extension>:<use>"`) points at."""
    return {"profiles": copy.deepcopy(_AI_PROFILES), "uses": dict(uses)}
