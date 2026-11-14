"""What every app's tests check of the app itself, written once (shared-code plan, step 1).

The kit's features are tested in the kit (hiro-extension-kit/tests). What only the app can show is that it is wired as
the kit expects: its test setup is safe, its routes all have a rule and declare their answers, its frontend's types are
fresh, its workers can run, its migrations match its models and lose nothing on a copy, it writes files only through
the kit and logs to its data folder, and the kit's routes are there. Each app had these tests in its own copy; now its
tests/test_contract.py is a few lines:

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

# The kit's routes every app on the kit mounts: sign-in and who is asking, Settings → HiroLeague, the app switcher.
KIT_ROUTES: tuple[tuple[str, str], ...] = (
    ("GET", "/api/me"), ("GET", "/api/auth/start"), ("GET", "/api/users"), ("GET", "/api/roles"),
    ("GET", "/api/hiroleague"), ("GET", "/api/apps"),
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

    # --- the app's routes ---

    def test_every_route_has_a_rule(self):
        rule_for = self._rule_for()
        missing = sorted(f"{m} {p}" for m, p, _ in self._operations() if p.startswith("/api/") and rule_for(m, p) is None)
        assert missing == [], "give these routes a rule in the app's extension.py RULES"

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

    def test_the_app_logs_to_its_data_folder(self):
        """The app sets the kit's logging up on its own data folder when its app module loads (the files themselves,
        and that nothing escapes them, are the kit's tests)."""
        import logging
        from logging.handlers import RotatingFileHandler

        from . import identity

        me = identity.app()
        files = {h.baseFilename for h in logging.getLogger().handlers if isinstance(h, RotatingFileHandler)}
        assert {str(me.data_dir / "logs" / f"{me.name}.log"), str(me.data_dir / "logs" / f"{me.name}-errors.log")} <= files
