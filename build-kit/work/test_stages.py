"""A deploy's stages, from the lines its scripts print: the core's (with the check engine's parts), an app's (Docker's
build, the migrations' trial, Compose's start), a failure, and lines it doesn't know."""

from stages import Stages


class Run:
    """Feeds a deploy's lines, the clock moving one second per line; keeps what was emitted as (phase, step, ok,
    seconds)."""

    def __init__(self, repo: str):
        self.t = 1000.0
        self.got: list[tuple] = []
        self.tests: dict[str, int] = {}  # each stage's count of tests, when it ended with one
        self.stages = Stages(repo, self.emit, clock=lambda: self.t)

    def emit(self, *, step, phase, at, ok=None, seconds=None, tests=None):
        self.got.append((phase, step, ok, seconds) if phase == "end" else (phase, step, at))
        if tests is not None:
            self.tests[step] = tests

    def feed(self, text: str):
        for line in text.strip("\n").splitlines():
            self.t += 1
            self.stages.line(line)
        return self

    def ends(self):
        return [(step, ok) for phase, step, *rest in self.got if phase == "end" for ok in rest[:1]]

    def starts(self):
        return [step for phase, step, *_ in self.got if phase == "start"]


CORE = """
remote: hiroleague: deploying 4c70d67 as release 20261116T102145Z-4c70d67
remote: hiroleague: installing the admin UI's packages (npm ci)
remote: added 175 packages in 2s
remote: hiroleague: running the checks (scripts/check.sh)
remote: check: 2 part(s) in 2 lane(s), at most 2 at once: admin_frontend hiroserver
remote:     started: admin_frontend: svelte-check
remote:     started: hiroserver: hirocli tests
remote:
remote: ==> admin_frontend: svelte-check
remote: svelte-check found 0 errors and 0 warnings
remote:     passed in 11 s
remote:
remote: ==> hiroserver: hirocli tests
remote: bringing up nodes...
remote: ........................................................................ [ 96%]
remote: ...                                                                      [100%]
remote: 75 passed in 3.10s
remote:     passed in 30 s
remote: hiroleague: building the admin UI
remote: hiroleague: copying the databases
remote: hiroleague: starting 20261116T102145Z-4c70d67
remote: hiroleague: deployed 20261116T102145Z-4c70d67: http://127.0.0.1:18080/status answers.
"""


def test_the_core_deploy_times_each_stage_and_each_check_part_by_the_engine_s_own_time():
    r = Run("hiroleague").feed(CORE)
    r.stages.close(True)
    assert r.starts() == [
        "Install the admin UI's packages", "Run the checks", "Check: admin_frontend: svelte-check",
        "Check: hiroserver: hirocli tests", "Build the admin UI", "Copy the databases", "Start the new release",
    ]
    assert ("end", "Check: admin_frontend: svelte-check", True, 11.0) in r.got
    assert ("end", "Check: hiroserver: hirocli tests", True, 30.0) in r.got  # not pytest's "54 passed in 3.10s"
    assert all(ok for _, ok in r.ends())
    assert len(r.ends()) == len(r.starts())  # deployed ended the last one: close adds nothing
    # A part that ran tests ends with its count, as the check engine counts them; one that ran none, with none
    assert r.tests == {"Check: hiroserver: hirocli tests": 75}


def test_a_vitest_part_is_counted_from_its_total_colours_and_all():
    r = Run("hiroleague").feed("""
remote:     started: admin_frontend: unit tests
remote: ==> admin_frontend: unit tests
remote:  [32m✓[39m src/a.test.ts [2m([22m[2m8 tests[22m[2m)[22m 9ms
remote: [2m      Tests [22m [1m[32m416 passed[39m[22m[90m (416)[39m
remote:     passed in 14 s
""")
    assert r.tests == {"Check: admin_frontend: unit tests": 416}  # the total, not the file lines added to it


APP = """
remote: #1 [internal] load build definition from Dockerfile
remote: #1 DONE 0.0s
remote: #26 [ui-src 5/6] RUN --mount=type=cache,target=/root/.npm npm ci --prefer-offline
remote: #26 CACHED
remote: #28 [stage-1 11/12] RUN uv sync --frozen && uv run --no-sync python -m unittest discover -s tests
remote: #28 2.290 ....
remote: #28 9.100 Ran 237 tests in 9.1s
remote: #28 [stage-1 11/12] RUN uv sync --frozen && uv run --no-sync python -m unittest discover -s tests
remote: #28 DONE 15.7s
remote: #30 [ui 7/7] RUN npm run check && npm run build
remote: #30 DONE 51.9s
remote: homehiro: copying the database before the new version touches it
remote: homehiro: trying the new migrations on a copy
remote:  Container homehiro-homehiro-run-888421075156 Creating
remote: migrations-seconds=1
remote:  Container homehiro Recreate
remote:  Container homehiro Starting
remote: homehiro: deployed
"""


def test_an_app_deploy_times_the_build_the_steps_that_ran_in_it_and_each_stage_after_it():
    r = Run("homehiro").feed(APP)
    assert r.starts() == ["Build the image", "Run the Python tests", "Check and build the UI", "Copy the database",
                          "Try the migrations on a copy", "Start the new version"]
    assert ("end", "Run the Python tests", True, 15.7) in r.got  # Docker's own time
    assert ("end", "Check and build the UI", True, 51.9) in r.got
    # A step starts when Docker announced it, even one that printed nothing until its end
    assert ("start", "Check and build the UI", 1010.0) in r.got
    assert ("start", "Run the Python tests", 1005.0) in r.got
    assert "Install the Node packages" not in r.starts()  # cached: it didn't run
    assert all(ok for _, ok in r.ends()) and len(r.ends()) == 6
    assert r.tests == {"Run the Python tests": 237}  # unittest's own total, from the step's output


def test_a_failed_deploy_ends_its_stage_failed_and_what_still_runs_with_it():
    r = Run("nethiro").feed("""
remote: #5 [backend 5/10] RUN uv sync --frozen --no-dev
remote: #5 1.0 Resolved 80 packages
remote: nethiro: copying the database before the new version touches it
remote: nethiro: not deployed: the database couldn't be copied (above)
""")
    r.stages.close(False)
    assert ("Copy the database", False) in r.ends()
    assert ("Install the Python packages", False) in r.ends()  # never said DONE
    assert ("Build the image", True) in r.ends()


def test_a_retried_build_isn_t_a_failure_and_lines_it_doesn_t_know_change_nothing():
    r = Run("codehiro").feed("""
remote: #1 [internal] load build definition from Dockerfile
remote: codehiro: build failed (attempt 1), retrying in 10 s
remote: Something else entirely
remote: codehiro: something new it says
remote:  Container codehiro Recreate
remote: codehiro: deployed
""")
    assert r.ends() == [("Build the image", True), ("Start the new version", True)]
