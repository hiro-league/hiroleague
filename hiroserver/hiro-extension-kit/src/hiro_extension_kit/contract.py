"""What every app's tests check of the app itself, written once (shared-code plan, step 1).

The kit's features are tested in the kit (hiro-extension-kit/tests). What only the app can show is that it is wired as
the kit expects: its test setup is safe, its routes all have a rule and declare their answers, its frontend's types are
fresh, its workers can run, its migrations match its models and lose nothing on a copy, it writes files only through
the kit and logs to its data folder, and the kit's routes are there. Each app had these tests in its own copy; now its
tests/test_contract.py is a few lines. It also proves that nothing escapes the app's log: each safety net of the logging
foundation catches its failure into the app's file (the self-test), the crashed-route handler is wired, the watchdog
runs, and no broad `except` drops an error without a log line, a re-raise or `failed()`:

    from hiro_extension_kit.contract import AppContract
    from nethiro.app import WORKERS
    from nethiro.main import app

    class TestContract(AppContract):
        app = app
        workers = WORKERS
        generated_ts = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "api" / "generated.ts"
        not_json = {("GET", "/api/adguard-lists/{name}.txt")}  # the app's own routes that answer something else

pytest collects the class's tests as the app's. It needs the app's tests/conftest.py as every app has it: its own data
folder under the system's temp folder, OUTPUTS=off, and `testing.guard_network()`.

Imported only by tests: it needs pytest, which an app installs as a dev tool.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import socket
import sys
import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, ClassVar

import pytest
from hiro_channel_sdk.constants import METHOD_CORE_INFO
from hiro_commons.logging_foundation.catches import silent_catches

# The kit's own routes that answer something other than JSON, or nothing (an app mounts some or all of them).
KIT_NOT_JSON: frozenset[tuple[str, str]] = frozenset({
    ("GET", "/api/events"),  # Server-Sent Events (notices.py)
    ("GET", "/api/logs/files/{name}"),  # a log file, to download (logs_api.py)
    ("GET", "/api/logs/llm/{rid}/pictures/{n}"),  # a picture sent with an LLM request (llm/requests_api.py)
    ("GET", "/api/auth/start"),  # a redirect to HiroLeague's sign-in page (auth/api.py)
    ("GET", "/api/auth/hiro"),  # back from HiroLeague with a one-time code, a redirect into the app
    ("POST", "/api/auth/logout"),
    ("GET", "/api/auth/signout"),  # HiroLeague's Sign out passes through, a redirect back there
})

# The kit's routes every app on the kit mounts: sign-in and who is asking, Settings → HiroLeague, the app switcher,
# its pages' problems.
KIT_ROUTES: tuple[tuple[str, str], ...] = (
    ("GET", "/api/me"), ("GET", "/api/auth/start"), ("GET", "/api/users"), ("GET", "/api/roles"),
    ("GET", "/api/hiroleague"), ("GET", "/api/apps"), ("POST", "/api/page-problems"),
)


def _loose(schema: dict | None) -> bool:
    if not schema:
        return True
    if schema.get("type") == "object" and "properties" not in schema and schema.get("additionalProperties") in (True, {}):
        return True
    if schema.get("type") == "array":
        return _loose(schema.get("items"))
    return False


class AppContract:
    """Subclass it as `TestContract` in the app's tests, with the class attributes below set (pytest collects a class
    whose name starts with Test; this one's doesn't, so the kit's own tests don't run it)."""

    # The app's FastAPI app (main.app). Its background services stay off: no TestClient `with`.
    app: ClassVar[Any]
    # The app's background services (app.WORKERS).
    workers: ClassVar[Iterable[Any]] = ()
    # The frontend's API types file scripts/api_types.py writes; a backend without its frontend (the Docker check) skips.
    generated_ts: ClassVar[Path | None] = None
    # The app's own routes that answer something other than JSON, or nothing; each must still exist.
    not_json: ClassVar[set[tuple[str, str]]] = set()
    # JSON the app passes on as it comes from elsewhere; each must still exist.
    passed_on: ClassVar[set[tuple[str, str]]] = set()
    # The kit's routes the app must mount (an app with its own sign-in, StudyHiro, names fewer).
    kit_routes: ClassVar[tuple[tuple[str, str], ...]] = KIT_ROUTES
    # The rule for a route; None: the route has none. The kit's guard, unless the app has its own.
    rule_for: ClassVar[Callable[[str, str], Any] | None] = None
    # Whether the app sends or speaks anything (WhatsApp, voices): its tests must then run with OUTPUTS=off. False for an
    # app with no OUTPUTS setting because it sends nothing (TrainHiro).
    sends: ClassVar[bool] = True

    # --- helpers ---

    @classmethod
    def _spec(cls) -> dict[str, Any]:
        return cls.app.openapi()

    @classmethod
    def _operations(cls):
        for path, ops in cls._spec()["paths"].items():
            for method, op in ops.items():
                ok = next((r for code, r in op["responses"].items() if code.startswith("2")), {})
                schema = ((ok.get("content") or {}).get("application/json") or {}).get("schema")
                yield method.upper(), path, schema

    @classmethod
    def _rule_for(cls) -> Callable[[str, str], Any]:
        if cls.rule_for is not None:
            return cls.rule_for
        from .auth.guard import rule_for

        return rule_for

    # --- the test setup itself: its own database, outputs off, no network ---

    def test_uses_its_own_database_in_a_temp_folder(self):
        """Never a real app's: a shell set up for a test server points DATA_DIR at a copy of the family's database."""
        from . import db, identity

        data_dir = identity.app().data_dir
        assert Path(tempfile.gettempdir()).resolve() in data_dir.parents, data_dir
        assert data_dir in Path(db.engine.url.database or "").resolve().parents
        if "DATA_DIR" in os.environ:
            assert Path(os.environ["DATA_DIR"]).resolve() == data_dir

    def test_outputs_are_off(self):
        if not self.sends:
            pytest.skip("the app sends and speaks nothing")
        from .extension import ext

        assert ext().outputs is False

    def test_http_to_the_lan_is_refused(self):
        import httpx

        with pytest.raises(Exception, match="may not use the network"):
            httpx.get("http://192.168.1.11:8123/api/", timeout=2)

    def test_a_websocket_to_the_lan_is_refused(self):
        import websockets

        async def connect():
            async with websockets.connect("ws://192.168.1.11:8123/api/websocket", open_timeout=2):
                pass

        with pytest.raises(Exception, match="may not use the network"):
            asyncio.run(connect())

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows picks the ports that collided")
    def test_local_connections_start_from_ports_of_their_own(self):
        """Windows' own choice made a connection that was still held (TIME_WAIT): a test failed or a run hung."""
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen()
            with socket.create_connection(server.getsockname()) as plain:  # socket.connect
                assert 20000 <= plain.getsockname()[1] < 40000
            a, b = socket.socketpair()  # what every new event loop makes
            with a, b:
                assert 20000 <= b.getsockname()[1] < 40000

        async def through_asyncio():
            server = await asyncio.start_server(lambda _r, w: w.close(), "127.0.0.1", 0)
            _, writer = await asyncio.open_connection(*server.sockets[0].getsockname())
            port = writer.get_extra_info("sockname")[1]
            writer.close()
            server.close()
            await server.wait_closed()
            return port

        assert 20000 <= asyncio.run(through_asyncio()) < 40000

    # --- the outside systems it reaches ---

    def test_every_outside_system_it_reaches_is_declared_and_gated(self):
        """A test environment's switchboard holds only where a client asks it (hiro-docs workflow.md, "The
        switchboard"). So: every system the app declares (`Extension(systems=...)`) is one the switchboard knows; each
        one it reaches itself has a `switchboard.gate("<system>", ...)` call in its code (the core checks AI, voices
        and WhatsApp for every app); and the code asks the switchboard about no system the app doesn't declare."""
        import re

        from hiro_commons.switchboard import SYSTEMS

        from . import identity
        from .extension import ext
        from .switchboard import THROUGH_CORE

        declared = set(ext().systems)
        assert declared - set(SYSTEMS) == set(), f"not systems of the switchboard (it has: {', '.join(SYSTEMS)})"
        asks = re.compile(r"switchboard\.(gate|reaches|writes|mode)\(\s*[\"'](\w+)[\"']")
        gated: set[str] = set()
        asked: set[str] = set()
        for path in identity.app().package.rglob("*.py"):
            for how, system in asks.findall(path.read_text(encoding="utf-8")):
                asked.add(system)
                if how == "gate":
                    gated.add(system)
        assert declared - THROUGH_CORE - gated == set(),             "declared in Extension(systems=...), but no client calls switchboard.gate for it"
        assert asked - declared == set(), "the code asks the switchboard about these: declare them in Extension(systems=...)"

    # --- the stories it names ---

    def test_every_story_it_names_is_declared_and_every_declared_one_is_named(self):
        """The logging plan's phase 6a: a story is listed only when its feature names it with a declared name. So every
        name the code gives (`story.named("<name>", ...)`, a round's `story_name="<name>"`) is in
        `Extension(stories=...)`, every declared story is named somewhere in the code, and each belongs to this app
        (its name starts with the app's own: "net.health_checks")."""
        import re

        from . import identity
        from .extension import ext

        declared = {d.name for d in ext().stories}
        assert all(n.startswith(f"{ext().name}.") for n in declared), f"a story's name starts with '{ext().name}.'"
        names = re.compile(r"""(?:story\.named\(|story_name\s*=)\s*["']([a-z0-9_.]+)["']""")
        named: set[str] = set()
        for path in identity.app().package.rglob("*.py"):
            named |= set(names.findall(path.read_text(encoding="utf-8")))
        assert named - declared == set(), "named in the code but not declared in Extension(stories=...)"
        assert declared - named == set(), "declared in Extension(stories=...) but never named in the code"

    # --- what it asks the owner to approve ---

    def test_what_it_asks_to_do_on_its_own_is_understood_and_says_why(self):
        """Permissions phase 8: each thing the app asks to do on its own (`Extension(asks=...)`) is a permission the
        SDK knows (approvals.ASKABLE: one the core doesn't know is never approved), says why in a line for the owner,
        and an ask of another app names it (`to`). An app that declares none yet (None) is left as it is."""
        from hiro_channel_sdk.approvals import APPS_ASK, ASKABLE

        from .extension import ext

        asks = ext().asks
        if asks is None:
            pytest.skip("the app doesn't declare what it asks yet (Extension.asks is None)")
        assert [a.permission for a in asks if a.permission not in ASKABLE] == [], f"not one of {sorted(ASKABLE)}"
        assert [a.permission for a in asks if not a.why.strip()] == [], "say why, in a line for the owner"
        assert [a for a in asks if a.permission == APPS_ASK and not (a.to or "").strip()] == [], \
            "an ask of another app names it: ask(APPS_ASK, why, to='home')"

    # --- the port it serves on ---

    def test_it_declares_the_port_it_listens_on(self):
        """The core points its web proxy at the port the app declares (sites.claim): the one its app.env gives the shared
        image (build-kit/Dockerfile starts uvicorn on APP_PORT). Shared-code plan, step 2: the port moved from each
        app's Dockerfile to app.env."""
        from . import identity
        from .extension import ext

        app_env = identity.app().package.parents[2] / "app.env"  # <repo>/backend/src/<app> → <repo>/app.env
        if not app_env.exists():
            pytest.skip("no app.env here (the Docker check builds the backend alone)")
        facts = dict(line.split("=", 1) for line in app_env.read_text(encoding="utf-8").splitlines()
                     if line and not line.startswith("#") and "=" in line)
        assert facts.get("APP") == identity.app().name
        assert int(facts["APP_PORT"]) == ext().port

    # --- the app's routes ---

    def test_every_route_has_a_rule(self):
        rule_for = self._rule_for()
        missing = sorted(f"{m} {p}" for m, p, _ in self._operations() if p.startswith("/api/") and rule_for(m, p) is None)
        assert missing == [], "give these routes a rule in the app's extension.py RULES"

    def test_a_rule_under_a_personal_action_says_whose_the_record_is(self):
        """A grant for their own things reaches a route only through its rule's whose (hiro_commons.rules); a rule
        without one would let a grant for their own reach nothing, or, worse, be read as everyone's. Permissions
        phase 5."""
        if self.rule_for is not None:
            pytest.skip("the app keeps its own route check")
        from .auth.guard import rules_without_whose, unknown_lookups
        from .extension import ext

        assert rules_without_whose(ext().rules) == [], \
            "these rules' actions are personal: give each a whose (by_person, by_lookup or LIST)"
        assert unknown_lookups(ext().rules) == [], "these rules name a lookup nobody registered (auth.whose.register)"

    def test_a_list_route_takes_the_reach_it_filters_by(self):
        """A route whose rule is LIST is handed "own" or "all" (auth.whose.listed) and must take it, or a grant for
        their own things would show everyone's."""
        if self.rule_for is not None:
            pytest.skip("the app keeps its own route check")
        from .auth.guard import lists_without_reach

        assert lists_without_reach(self.app.routes) == [], \
            "these list routes don't take the reach: add `reach: Reach = Depends(listed)`"

    def test_every_json_route_declares_its_answer(self):
        """So the frontend's types can be generated from the API description, and a changed answer shows up there
        instead of breaking a page silently (review step 5)."""
        loose = {(m, p) for m, p, schema in self._operations() if _loose(schema)}
        assert loose - KIT_NOT_JSON - self.not_json - self.passed_on == set(), \
            "these routes answer JSON without a declared model"

    def test_the_apps_exceptions_still_exist(self):
        known = {(m, p) for m, p, _ in self._operations()}
        assert (self.not_json | self.passed_on) - known == set(), "an exception names a route that is gone"

    def test_the_kits_routes_are_mounted(self):
        known = {(m, p) for m, p, _ in self._operations()}
        assert set(self.kit_routes) - known == set()

    def test_who_is_asking_answers(self):
        """Sign-in off (the tests' AUTH=off): everyone is the owner, so /api/me answers."""
        if ("GET", "/api/me") not in self.kit_routes:
            pytest.skip("the app has its own sign-in")
        from fastapi.testclient import TestClient

        r = TestClient(self.app).get("/api/me")
        assert r.status_code == 200, r.text
        assert r.json()["owner"] is True

    def test_a_request_carries_its_story_into_the_core(self, monkeypatch):
        """The logging plan's one id: a page request that brings a W3C traceparent continues that story, its request
        to the core carries the same id (the SDK's frame), and the answer names it (errors.install puts the kit's
        stories middleware on the app)."""
        from fastapi.testclient import TestClient

        from .hiroleague import link
        from .testing import FakeCore

        core = FakeCore()
        core.answers[METHOD_CORE_INFO] = {"name": "HiroLeague", "version": "0.0.0"}
        monkeypatch.setattr(link, "client", core)
        story_id = "4bf92f3577b34da6a3ce929d0e0e4736"
        r = TestClient(self.app).post("/api/hiroleague/test", headers={"traceparent": f"00-{story_id}-00f067aa0ba902b7-01"})
        assert r.status_code == 200, r.text
        assert r.headers.get("traceparent", "").split("-")[1:2] == [story_id], "call errors.install(app) in create_app"
        carried = core.frames[-1].routing.metadata.get("traceparent", "")
        assert carried.split("-")[1:2] == [story_id], "the request to the core lost the page's story"

    # --- the frontend's types ---

    def test_no_two_models_share_a_name(self):
        """Two models with one name (a second UserIn, RunOut) made FastAPI name both after their modules, and the
        frontend's type silently disappeared (2026-09-29, twice)."""
        from .api_types import clashes

        assert clashes(self._spec()) == []

    def test_the_frontend_types_are_up_to_date(self):
        from .api_types import generate

        out = self.generated_ts
        if out is None or not out.exists():
            pytest.skip("no frontend here (the Docker check builds the backend alone)")
        assert out.read_text(encoding="utf-8") == generate(self._spec()), (
            f"{out.name} is out of date: run `uv run python scripts/api_types.py` in the backend")

    # --- its workers ---

    def test_every_service_is_a_worker_that_can_be_kept_running(self):
        """The loop calls `run()` with no arguments: a worker whose own `run` wants some crash-loops forever (the
        automation engine did, 2026-09-29)."""
        from hiro_channel_sdk.workers import Worker

        for w in self.workers:
            assert isinstance(w, Worker), w
            inspect.signature(w.run).bind()  # raises TypeError when it needs arguments

    # --- its migrations ---

    def test_the_migrations_tried_on_a_copy_lose_nothing(self, tmp_path):
        """A deploy's trial (predeploy.py): the app's own migrations, on a copy of its database at head."""
        from . import db, predeploy

        copy = tmp_path / "copy.db"
        predeploy.copy_db(Path(db.engine.url.database or ""), copy)
        before, problems, _took = predeploy.trial(copy, tmp_path / "trial")
        assert problems == []
        assert "setting" in before  # the kit's table: the copy was the app's migrated database
        assert not (tmp_path / "trial").exists()

    def test_the_models_match_the_migrations(self):
        """A model change needs its migration: autogenerate would write nothing."""
        from alembic import command
        from alembic.config import Config

        from . import db

        db.migrate()  # this run's own database, at the newest migration
        cfg = Config()
        cfg.set_main_option("script_location", str(db.MIGRATIONS))
        command.check(cfg)  # fails when autogenerate would write anything

    # --- files and logs ---

    def test_no_module_writes_a_file_directly(self):
        """Every write goes through hiro_extension_kit/files.py, so none can leave a torn file."""
        import re

        from . import identity

        src = identity.app().package
        # files.write_bytes(...) is the way, under any name ending in `files` (StudyHiro imports it as `kit_files`)
        direct = re.compile(r"(?<!files)\.write_(bytes|text)\(")
        found = [f"{p.relative_to(src)}:{n}" for p in src.rglob("*.py") if p.name != "files.py"
                 for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if direct.search(line)]
        assert not found, f"write through hiro_extension_kit.files instead: {found}"

    # --- nothing escapes the log (the logging foundation's safety nets) ---

    def test_every_safety_net_catches_its_failure_into_the_log(self):
        """The foundation's self-test, on the app's own setup: an uncaught error in the main thread and in another, a
        failing finalizer, a failed task on a loop started as the app starts its own (`events.bind()`), a warning, a
        library's problem and the web server's, with their tracebacks; faulthandler on; a child's output in its file."""
        from hiro_commons import logging_foundation

        from . import events

        bound = events._loop
        try:
            results = logging_foundation.self_test(startup=events.bind)
        finally:
            events._loop = bound
        missing = [net for net, ok in results.items() if not ok]
        assert not missing, f"these failures didn't reach the app's log: {missing}"

    def test_a_crashed_route_is_answered_and_logged_with_its_traceback(self):
        """errors.install(app) is wired: the app's handler answers an unexpected error, and its line carries the
        traceback."""
        import json

        from hiro_commons import logging_foundation
        from starlette.requests import Request

        from .errors import AppError

        handlers = self.app.exception_handlers
        assert AppError in handlers and Exception in handlers, "call errors.install(app) in create_app"
        word = f"contract-crash-{os.getpid()}-{id(self)}"
        try:
            raise KeyError(word)
        except KeyError as exc:
            request = Request({"type": "http", "method": "GET", "path": "/api/contract-crash", "headers": [], "query_string": b""})
            answer = asyncio.run(handlers[Exception](request, exc))
        assert answer.status_code == 500
        logging_foundation.flush()
        where = logging_foundation.where()
        assert where is not None
        lines = [json.loads(t) for _d, p in logging_foundation.daily.files(*where)[:2]
                 for t in p.read_text(encoding="utf-8").splitlines() if word in t]
        assert lines and "Traceback" in lines[0].get("Attributes", {}).get("exception.stacktrace", "")

    def test_the_watchdog_runs(self):
        """It logs what blocks the event loop, and where (watchdog.py)."""
        from .watchdog import Watchdog

        assert any(isinstance(w, Watchdog) for w in self.workers), "put hiro_extension_kit.watchdog.watchdog in WORKERS"

    def test_no_catch_drops_an_error(self):
        """A broad `except` (bare, Exception, BaseException) logs, raises again or calls `failed()`: an error it swallows
        is lost for good. (ruff's blind-except rule can't tell `failed()` is a log line, so the kit checks it.)"""
        from . import identity

        package = identity.app().package
        found = [f"{path.relative_to(package)}:{line}" for path, line in silent_catches(package)]
        assert not found, f"these catches drop the error: log it (errors.failed), or raise it again: {found}"

    def test_the_app_logs_to_its_data_folder(self):
        """The app sets the kit's logging up on its own data folder when its app module loads (the files themselves,
        and that nothing escapes them, are the kit's tests)."""
        from hiro_commons import logging_foundation

        from . import identity

        me = identity.app()
        where = logging_foundation.where()  # the logging foundation, set up through logs.py
        assert where is not None and (where[0].resolve(), where[1]) == ((me.data_dir / "logs").resolve(), me.name)
