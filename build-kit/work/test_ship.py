"""ship.py: the new lines of the events log go to CodeHiro once each, by position, and wait while it can't be reached."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import ship


class Fake:
    """A stand-in for CodeHiro's POST /api/work/events: keeps what it took, answers as told."""

    def __init__(self):
        self.posts: list[list[dict]] = []
        self.status = 200
        self.refuse_id: str | None = None  # 400 for any post holding this id
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                ids = [e["id"] for e in body["events"]]
                code = fake.status
                if code == 200 and fake.refuse_id in ids:
                    code = 400
                if code == 200:
                    assert self.headers["X-Work-Key"] == "k"
                    fake.posts.append(body["events"])
                self.send_response(code)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/api/work/events"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def ids(self) -> list[str]:
        return [e["id"] for post in self.posts for e in post]


@pytest.fixture
def fake():
    f = Fake()
    yield f
    f.server.shutdown()


def write(path, *lines, partial: str = ""):
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")
        f.write(partial)


def test_new_lines_go_once_each_with_their_position(tmp_path, fake):
    log = tmp_path / "events.jsonl"
    write(log, {"step": "a", "phase": "start"}, {"step": "a", "phase": "end"}, partial='{"step": "b"')
    sender = ship.Sender(log, fake.url, "k", "pc")
    assert sender.once() == 2
    fid = ship.file_id(log)
    assert fake.ids[0] == f"pc:{fid}:0"
    assert fake.posts[0][1]["phase"] == "end"
    assert sender.once() == 0  # nothing new; the half-written line waits
    write(log, partial=', "phase": "start"}\n')
    assert sender.once() == 1
    assert fake.posts[-1][0]["step"] == "b"


def test_while_codehiro_cant_be_reached_the_lines_wait(tmp_path, fake):
    log = tmp_path / "events.jsonl"
    write(log, {"step": "a", "phase": "start"})
    sender = ship.Sender(log, "http://127.0.0.1:9/api/work/events", "k", "pc")
    with pytest.raises(OSError):
        sender.once()
    sender.url = fake.url
    assert sender.once() == 1


def test_a_log_made_again_starts_over_with_new_ids(tmp_path, fake):
    log = tmp_path / "events.jsonl"
    write(log, {"step": "a", "phase": "start"}, {"step": "a", "phase": "end"})
    sender = ship.Sender(log, fake.url, "k", "pc")
    sender.once()
    log.unlink()
    write(log, {"step": "z", "phase": "start"})
    assert sender.once() == 1
    assert fake.ids[-1].split(":")[1] != fake.ids[0].split(":")[1]


def test_a_refused_line_is_left_out_and_the_others_go(tmp_path, fake):
    log = tmp_path / "events.jsonl"
    write(log, {"step": "a", "phase": "start"}, {"step": "b", "phase": "start"})
    fake.refuse_id = f"pc:{ship.file_id(log)}:0"
    sender = ship.Sender(log, fake.url, "k", "pc")
    assert sender.once() == 2
    assert [e["step"] for e in fake.posts[-1]] == ["b"]
    assert "left out" in (tmp_path / "ship.log").read_text(encoding="utf-8")


def test_a_wrong_key_stops_the_sender(tmp_path, fake):
    log = tmp_path / "events.jsonl"
    write(log, {"step": "a", "phase": "start"})
    fake.status = 403
    with pytest.raises(ship.Refused):
        ship.Sender(log, fake.url, "k", "pc").once()


def test_only_one_sender_per_log(tmp_path):
    lock = tmp_path / "events.jsonl.ship.lock"
    with ship.only_one(lock) as first:
        with ship.only_one(lock) as second:
            assert (first, second) == (True, False)
    with ship.only_one(lock) as again:
        assert again


def test_no_key_sends_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ship, "KEY_FILE", tmp_path / "missing.key")
    assert ship.main(["--once", "--events", str(tmp_path / "events.jsonl")]) == 0
    assert "nothing is sent" in capsys.readouterr().out
