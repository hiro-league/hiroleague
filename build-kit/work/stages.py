"""A deploy's stages, read from its output as it streams, so the deploy times each one and CodeHiro's Work area shows
what a deploy did (the checks and each of their parts, the image build and the tests in it, the migrations tried on a
copy, the start) instead of one block.

It reads the lines the deploy scripts already print (git prints a hook's lines with "remote: " before them):

- the core's deploy (deploy/deploy.sh): "hiroleague: <what it does now>";
- an app's (build-kit/deploy.sh, CodeHiro's own deploy.sh): Docker's build first ("#12 [ui 5/7] RUN npm ci",
  "#12 2.31 <output>", "#12 DONE 15.7s"), then "<app>: <what it does now>", and Compose starting its container;
- the check engine, inside the core's deploy: "started: <part>", and when the part ends its block,
  "==> <part>" ... "passed in N s" or "FAILED in N s".

A line it doesn't know changes nothing, so a new line in a deploy script only goes untimed until a row is added here.
The stages are steps inside the deploy's "deploy" step (``parent: deploy``), named in plain words. A stage that ran tests
(a check part, the tests in an image's build) ends with how many it ran (``tests``), counted from what it printed as the
check engine counts them on the PC (check_events.count_tests).
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable

from check_events import count_tests

# A deploy script's line (after "<repo>: "), by how it starts -> the stage it begins. The longer prefix first.
STAGES = [
    ("another deploy is running", "Wait for another deploy"),
    ("installing the admin UI's packages", "Install the admin UI's packages"),
    ("installing the UI kit's packages", "Install the UI kit's packages"),
    ("running the checks", "Run the checks"),
    ("building the admin UI", "Build the admin UI"),
    ("installing into", "Install the release"),
    ("stopping", "Stop the service"),
    ("copying the databases", "Copy the databases"),
    ("copying the database", "Copy the database"),
    ("trying the new migrations", "Try the migrations on a copy"),
    ("starting the previous release", "Start the previous release"),
    ("starting", "Start the new release"),
    ("going back", "Go back to the previous version"),
]
# Words in a deploy script's line that say the stage running failed ("build failed (attempt 1), retrying" doesn't)
FAILED = ("failed", "not deployed", "did not answer", "doesn't answer", "INCOMPLETE")
# A Docker build step's command -> its name (the first that matches); a step not named here is part of the build only
RUNS = [
    ("unittest", "Run the Python tests"),
    ("pytest", "Run the Python tests"),
    ("npm run check", "Check and build the UI"),
    ("npm run build", "Build the UI"),
    ("npm ci", "Install the Node packages"),
    ("uv sync", "Install the Python packages"),
    ("apt-get", "Install the system packages"),
]
BUILD = "Build the image"
START = "Start the new version"

DOCKER_STEP = re.compile(r"^#(\d+) \[[^\]]+\] RUN (.*)$")
DOCKER_OUTPUT = re.compile(r"^#(\d+) \d+\.\d+ (.*)$")
DOCKER_DONE = re.compile(r"^#(\d+) DONE (\d+(?:\.\d+)?)s$")
DOCKER_OTHER = re.compile(r"^#(\d+) (CACHED|ERROR|CANCELED)\b")
DOCKER_ANY = re.compile(r"^#\d+ ")
CONTAINER = re.compile(r"^Container (\S+) (Recreate|Creating|Starting)$")
PART_STARTED = re.compile(r"^started: (.+)$")
PART_BLOCK = re.compile(r"^==> (.+)$")
PART_END = re.compile(r"^(passed|FAILED) in (\d+) s\b")

Emit = Callable[..., None]


def run_name(command: str) -> str | None:
    return next((name for word, name in RUNS if word in command), None)


class Stages:
    """Fed a deploy's lines (``line()``), it calls ``emit(step=, phase=, at=, ok=, seconds=)`` as each stage starts and
    ends (``at``: epoch seconds); ``close(ok)`` ends what still runs when the deploy ends."""

    def __init__(self, repo: str, emit: Emit, clock: Callable[[], float] = time.time):
        self.repo, self.emit, self.clock = repo, emit, clock
        self.stage: tuple[str, float] | None = None  # the deploy script's stage running now, since when
        self.failed = False  # it said it failed
        self.runs: dict[str, tuple[str, float]] = {}  # a Docker step's number -> its name, and when Docker announced it
        self.running: dict[str, float] = {}  # the named Docker steps running, since when
        self.parts: dict[str, float] = {}  # the check parts running, since when
        self.block: str | None = None  # the check part whose block is printing
        self.printed: list[str] = []  # that block's lines so far, for its count of tests
        self.output: dict[str, list[str]] = {}  # each named Docker step's output so far, for its count of tests
        self.built = False  # Docker's build began

    def _start(self, step: str, at: float | None = None) -> float:
        at = self.clock() if at is None else at
        self.emit(step=step, phase="start", at=at)
        return at

    def _end(self, step: str, since: float, ok: bool, seconds: float | None = None,
             printed: list[str] | None = None) -> None:
        now = self.clock()
        tests = count_tests("\n".join(printed)) if printed else 0
        self.emit(step=step, phase="end", at=now, ok=ok, seconds=round(now - since if seconds is None else seconds, 1),
                  **({"tests": tests} if tests else {}))

    def _next(self, step: str | None) -> None:
        """The deploy script's stage running now ends (as it said: failed or fine) and *step* begins."""
        if self.stage:
            self._end(self.stage[0], self.stage[1], not self.failed)
        self.failed = False
        self.stage = (step, self._start(step)) if step else None

    def line(self, raw: str) -> None:
        text = raw.removeprefix("remote:").strip()
        if not text:
            return
        if text.startswith(f"{self.repo}: "):
            said = text[len(self.repo) + 2:]
            if said.startswith("deployed"):
                self._next(None)
                return
            step = next((name for prefix, name in STAGES if said.startswith(prefix)), None)
            if step:
                self._next(step)
            elif any(w in said for w in FAILED) and "retrying" not in said:
                self.failed = True
            return
        if (m := CONTAINER.match(text)) and m.group(1) == self.repo:
            if not self.stage or self.stage[0] != START:
                self._next(START)
            return
        if DOCKER_ANY.match(text):
            self._docker(text)
            return
        if m := PART_STARTED.match(text):
            self.parts[m.group(1)] = self._start(f"Check: {m.group(1)}")
        elif m := PART_BLOCK.match(text):
            self.block, self.printed = m.group(1), []
        elif (m := PART_END.match(text)) and self.block in self.parts:
            self._end(f"Check: {self.block}", self.parts.pop(self.block), m.group(1) == "passed", float(m.group(2)),
                      self.printed)
            self.block, self.printed = None, []
        elif self.block:
            self.printed.append(text)

    def _docker(self, text: str) -> None:
        if not self.built:
            self.built = True
            self._next(BUILD)
        # A step starts when Docker announces it, but is only shown once it shows it runs (a cached one never does):
        # its first output line, or its DONE when it printed nothing
        if m := DOCKER_STEP.match(text):
            n, name = m.group(1), run_name(m.group(2))
            if name and n not in self.runs:  # Docker repeats a step's line when steps print side by side
                self.runs[n] = (name, self.clock())
        elif (m := DOCKER_OUTPUT.match(text)) and m.group(1) in self.runs:
            if m.group(1) not in self.running:
                name, announced = self.runs[m.group(1)]
                self.running[m.group(1)] = self._start(name, announced)
            self.output.setdefault(m.group(1), []).append(m.group(2))
        elif (m := DOCKER_DONE.match(text)) and m.group(1) in self.runs:
            n, seconds = m.group(1), float(m.group(2))
            name, announced = self.runs.pop(n)
            since = self.running.pop(n, None)
            if since is None:
                since = self._start(name, announced)
            self._end(name, since, True, seconds, self.output.pop(n, None))
        elif (m := DOCKER_OTHER.match(text)) and m.group(1) in self.runs:
            n = m.group(1)
            name, _ = self.runs.pop(n)
            if n in self.running:
                self._end(name, self.running.pop(n), m.group(2) != "ERROR", printed=self.output.pop(n, None))

    def close(self, ok: bool) -> None:
        """The deploy ended: what still runs ends with it, failed unless the deploy went live."""
        for n, since in list(self.running.items()):
            self._end(self.runs[n][0], since, ok)
        for part, since in list(self.parts.items()):
            self._end(f"Check: {part}", since, ok)
        self.running.clear()
        self.runs.clear()
        self.parts.clear()
        if self.stage:
            self.failed = self.failed or not ok
            self._next(None)

