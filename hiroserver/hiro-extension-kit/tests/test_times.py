"""Times: an app stores UTC. SQLModel (0.0.46) maps every `datetime` field to its UTCDateTime type:
it refuses times without a zone, and hands every time back in UTC, also rows written without one.
The API then sends times with their zone, so the UI can't mistake them for local time.

Shared-code plan, step 1: HomeHiro's and NetHiro's tests each had this file; it is tested once, here, on the kit's own
table of users. (The kit needs SQLModel 0.0.46 for it: pyproject.toml.)"""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import StatementError
from sqlmodel import Session, delete

from hiro_extension_kit import errors
from hiro_extension_kit.auth import api
from hiro_extension_kit.db import engine
from hiro_extension_kit.auth.models import AppUser

WHEN = datetime(2026, 9, 27, 10, 30, tzinfo=UTC)


@pytest.fixture
def area():
    with Session(engine) as s:
        s.exec(delete(AppUser).where(AppUser.id == "times"))
        s.add(AppUser(id="times", name="Times", first_seen=WHEN, last_seen=WHEN))
        s.commit()
    yield
    with Session(engine) as s:
        s.exec(delete(AppUser).where(AppUser.id == "times"))
        s.commit()


def test_times_come_back_in_utc(area):
    with Session(engine) as s:
        back = s.get(AppUser, "times").first_seen
    assert back == WHEN and back.utcoffset() == timedelta(0)


def test_a_time_in_another_zone_is_stored_as_the_same_moment(area):
    cairo = WHEN.astimezone(timezone(timedelta(hours=3)))
    with Session(engine) as s:
        s.get(AppUser, "times").last_seen = cairo
        s.commit()
    with Session(engine) as s:
        assert s.get(AppUser, "times").last_seen == WHEN


def test_rows_written_without_a_zone_read_as_utc(area):
    with Session(engine) as s:
        s.exec(text("UPDATE appuser SET last_seen = '2026-09-27 10:30:00.000000' WHERE id = 'times'"))  # type: ignore[call-overload]
        s.commit()
    with Session(engine) as s:
        assert s.get(AppUser, "times").last_seen == WHEN


def test_a_time_without_a_zone_is_refused(area):
    with Session(engine) as s:
        s.get(AppUser, "times").last_seen = datetime(2026, 9, 27, 10, 30)  # noqa: DTZ001 - the point of the test
        with pytest.raises(StatementError, match="timezone"):
            s.commit()


def test_the_api_sends_times_with_their_zone(area):
    app = FastAPI()
    app.include_router(api.router)
    errors.install(app)
    users = {u["id"]: u for u in TestClient(app).get("/api/users").json()}  # sign-in off: the owner
    sent = users["times"]["last_seen"]
    assert sent.endswith("Z") or sent.endswith("+00:00")
    assert datetime.fromisoformat(sent) == WHEN


def test_times_in_words_are_12_hour_and_say_the_day():
    """The house format (CLAUDE.md, "Dates and times"), as the UI's lib/format/time.ts, for sentences."""
    from hiro_extension_kit.clock import spoken

    now = datetime(2026, 9, 29, 13, 20, tzinfo=UTC)
    assert spoken(datetime(2026, 9, 29, 13, 15, tzinfo=UTC), UTC, now) == "1:15 PM today"
    assert spoken(datetime(2026, 9, 29, 0, 5, tzinfo=UTC), UTC, now) == "12:05 AM today"
    assert spoken(datetime(2026, 9, 28, 23, 57, tzinfo=UTC), UTC, now) == "11:57 PM yesterday"
    assert spoken(datetime(2026, 9, 24, 9, 5, tzinfo=UTC), UTC, now) == "9:05 AM on Thu, Sep 24"
    assert spoken(datetime(2025, 12, 27, 9, 5, tzinfo=UTC), UTC, now) == "9:05 AM on Sat, Dec 27, 2025"
    cairo = timezone(timedelta(hours=3))
    assert spoken(datetime(2026, 9, 28, 22, 30, tzinfo=UTC), cairo, now) == "1:30 AM today"  # the home's own day
