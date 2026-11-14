"""Test setup: pytest loads this before any test module here, so before a module of the kit reads which app it is.

The kit is told it is an app called `testapp`, with an empty data folder of this run's own (never a real app's:
the tests write log files and rows there). `identity.setup`, not the package's `setup`: that one also changes how the
SDK's workers log their failures, for the whole process, and the SDK's own tests run in the same process.

Shared-code plan, step 1: the kit's features (sign-in, the route check, the family copy, WhatsApp, voices, the core's AI,
the LLM requests log, the site name, predeploy) are tested here, once, instead of in every app. So `testapp` is also
an extension (`TEST_EXTENSION`, shaped like NetHiro's: System health, Logs, Settings; one AI use, one voice use), with
every table the kit ships, sign-in off and nothing sent unless a test turns them on, as an app's tests run.
"""

import shutil
import sys
import tempfile
from pathlib import Path

import pytest
from hiro_channel_sdk import ExtensionFeature, ExtensionUse, ExtensionVoiceUse

from hiro_extension_kit import extension, identity

DATA_DIR = Path(tempfile.mkdtemp(prefix="hiro-kit-tests-")).resolve()
identity.setup(name="testapp", title="TestApp", package=Path(__file__).parent, data_dir=DATA_DIR,
               static_dir=DATA_DIR / "static")
# (No testing.guard_network() here: these tests run in one process with the rest of the HiroLeague workspace, whose
# own tests don't expect it. test_testing.py checks the guard in a process of its own.)

from hiro_extension_kit.auth.access import right, see  # noqa: E402  (after identity: the kit's modules read it)
from hiro_extension_kit.auth.rules import Rule  # noqa: E402
from hiro_extension_kit.auth.rules import for_features as _r  # noqa: E402

FEATURES = [
    ExtensionFeature(id="status", name="System health", rights=[
        see("System health"),
        right("checks", "Change checks", "What is checked, machines, storage"),
        right("alerts", "Change alerts", "Alert rules and their tests"),
        right("network", "Network and DNS", "Blocking, sites, lookups, the traffic plan"),
        right("diagnose", "Run diagnostics", "Start and stop live sessions")]),
    ExtensionFeature(id="logs", name="Logs", rights=[see("TestApp's logs")]),
    ExtensionFeature(id="settings", name="Settings", rights=[right("change", "Change", "Connections and keys")]),
]
RULES = (
    Rule("/api/health", "public"),
    Rule("/api/me", "public"),
    Rule("/api/auth", "public"),
    Rule("/api/events", "signed_in"),
    Rule("/api/users", "owner"),
    Rule("/api/roles", "owner"),
    _r("/api/status", "status", "settings", methods=["GET"]),
    _r("/api/service-status/alerts", "status", methods=["POST", "PUT", "DELETE"], right="alerts"),
    _r("/api/service-status", "status"),
    _r("/api/logs", "logs"),
    _r("/api/settings", "settings"),
    _r("/api/hiroleague", "settings"),
    _r("/api/ai/uses", "settings"),
    _r("/api/ai", "settings", "status", methods=["GET"]),
)
PORT = 8199
TEST_EXTENSION = extension.Extension(
    name="test", version="0.0.1", description="The kit's own tests", repo="testapp", port=PORT, site_title="Test",
    site_icon="flask", features=FEATURES, rules=RULES,
    uses=[ExtensionUse(id="sites", name="Sorting sites", json=True)],
    voice_uses=[ExtensionVoiceUse(id="speak", name="Speak")],
    auth=False,  # every request is the owner; the tests of sign-in and roles turn it on (testing.auth)
    outputs=False,  # nothing is sent or spoken; a test that sends turns it on (testing.outputs)
    rights_from="home", rights_from_what="System health",
)
extension.setup(TEST_EXTENSION)


def _tables():
    """Every table the kit ships (each app's migrations make them; the kit has none of its own)."""
    from hiro_extension_kit.auth.models import AppUser, CorePerson, Role, WebSession
    from hiro_extension_kit.llm.models import LlmRequest
    from hiro_extension_kit.models import Setting

    return [Setting, CorePerson, Role, AppUser, WebSession, LlmRequest]


@pytest.fixture(autouse=True, scope="session")
def _the_test_database():
    """The kit ships no migrations (each app's make its tables): the tests' database gets the kit's tables directly."""
    from hiro_extension_kit import db, logs

    assert DATA_DIR in Path(db.engine.url.database or "").resolve().parents
    for model in _tables():
        model.__table__.create(db.engine, checkfirst=True)  # type: ignore[attr-defined]
    yield
    db.engine.dispose()
    logs.close()  # Windows can't delete an open file
    try:
        shutil.rmtree(DATA_DIR)
    except OSError as e:
        print(f"\nCould not remove the test data folder {DATA_DIR}: {e}", file=sys.stderr)


@pytest.fixture(autouse=True)
def _empty_tables():
    """Every test starts with empty tables, and with nothing the kit keeps in memory of the core (its AI and voice
    profiles as last read): a row or a list one test left is not there for the next."""
    from hiro_extension_kit import voices
    from hiro_extension_kit.llm import core_ai

    core_ai._known = core_ai.Known()
    voices._known = voices.Known()
    yield
    from sqlmodel import Session, delete

    from hiro_extension_kit import db

    with Session(db.engine) as session:
        for model in reversed(_tables()):  # sessions before their users
            session.exec(delete(model))  # type: ignore[call-overload]
        session.commit()


@pytest.fixture
def fake_core(monkeypatch):
    """A fake HiroLeague core (testing.FakeCore), in place of the link's client in family.py, whatsapp.py and
    voices.py: the family list, WhatsApp and the voice profiles. Nothing is sent: whatsapp.send stays behind outputs off
    unless a test turns them on."""
    from hiro_extension_kit import family, testing, voices, whatsapp

    core = testing.FakeCore()
    for module in (family, whatsapp, voices):
        monkeypatch.setattr(module, "link", testing.FakeLink(core))
    return core


@pytest.fixture
def fake_ai(monkeypatch):
    """A fake HiroLeague core answering the AI's questions (`ai.ask`, `ai.profiles`: testing.ai_answer and
    testing.ai_profiles), in place of the link's client in llm/profiles.py and llm/core_ai.py. Nothing is asked of a
    real AI."""
    from hiro_extension_kit import testing
    from hiro_extension_kit.llm import core_ai, profiles

    core = testing.FakeCore()
    core.answers.update({"ai.ask": testing.ai_answer(), "ai.profiles": testing.ai_profiles({"test:sites": None})})
    for module in (profiles, core_ai):
        monkeypatch.setattr(module, "link", testing.FakeLink(core))
    return core
