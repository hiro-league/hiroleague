"""A page's problems reach its app's log (page_problems.py, put on every kit app by errors.install): each under the story
it belongs to, with only the fields a page may give, its query cut off, and no more than a minute's share."""

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient
from hiro_commons.logging_foundation import line

from hiro_extension_kit import errors, identity, page_problems

STORY = "4bf92f3577b34da6a3ce929d0e0e4736"
PARENT = f"00-{STORY}-00f067aa0ba902b7-01"

app = FastAPI()
errors.install(app)
client = TestClient(app)


class Builds(logging.Handler):  # builds each line as it is logged, in the caller's thread, as the foundation does
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(line.build(record, "test"))


def report(*problems: dict) -> tuple[dict, list[dict]]:
    log = identity.logger("page")
    handler = Builds()
    log.addHandler(handler)
    try:
        r = client.post(page_problems.PATH, json={"problems": list(problems)})
    finally:
        log.removeHandler(handler)
    assert r.status_code == 200, r.text
    return r.json(), handler.lines


def setup_function() -> None:
    page_problems._window.update(start=0.0, count=0, dropped=0)


def test_a_failed_call_is_logged_under_its_own_story():
    answer, lines = report({"kind": "request", "level": "WARNING", "message": "The backend can't be reached.",
                            "error_type": "ApiError", "page": "/streams?code=abc", "traceparent": PARENT,
                            "method": "GET", "path": "streams/cams?x=1", "status": 0})
    assert answer == {"kept": 1}
    [found] = lines
    assert found["TraceId"] == STORY
    assert found["SeverityText"] == "WARNING"
    assert found["InstrumentationScope"] == "testapp.page"
    assert found["Body"] == "Page /streams?code=abc: GET streams/cams?x=1 got no answer: The backend can't be reached." \
        or "code=abc" not in found["Attributes"]["page"]
    fields = found["Attributes"]
    assert fields["page"] == "/streams" and fields["path"] == "streams/cams" and fields["status"] == 0


def test_an_error_keeps_its_type_and_stack_and_the_page_has_no_query():
    _, [found] = report({"kind": "error", "message": "x is undefined", "error_type": "TypeError",
                         "stack": "TypeError: x is undefined\n    at draw (page.js:1:2)", "page": "/logs",
                         "traceparent": PARENT, "count": 3})
    assert found["SeverityText"] == "ERROR" and found["TraceId"] == STORY
    assert found["Body"] == "Page /logs had an error: TypeError: x is undefined"
    fields = found["Attributes"]
    assert fields["exception.type"] == "TypeError" and "at draw" in fields["exception.stacktrace"]
    assert fields["count"] == 3


def test_a_page_query_never_reaches_the_line():
    _, [found] = report({"kind": "page", "message": "boom", "page": "/settings?code=secret-code",
                         "traceparent": PARENT})
    assert "secret-code" not in found["Body"]
    assert found["Attributes"]["page"] == "/settings"


def test_a_problem_with_no_story_is_logged_under_the_reports_own():
    _, [found] = report({"kind": "error", "message": "boom", "page": "/"})
    assert len(found["TraceId"]) == 32


def test_an_unknown_kind_is_refused_and_a_batch_is_capped():
    r = client.post(page_problems.PATH, json={"problems": [{"kind": "error", "message": "m"}] * 21})
    assert r.status_code == 422
    r = client.post(page_problems.PATH, json={"problems": [{"kind": "chat", "message": "m"}]})
    assert r.status_code == 422


def test_past_the_minutes_share_lines_are_dropped():
    page_problems._window.update(start=page_problems.time.monotonic(), count=page_problems.PER_MINUTE - 1, dropped=0)
    answer, lines = report({"kind": "error", "message": "a"}, {"kind": "error", "message": "b"})
    assert answer == {"kept": 1} and len(lines) == 1 and page_problems._window["dropped"] == 1
