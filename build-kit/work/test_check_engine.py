"""check-engine.sh: a part's "-<path>" entries leave a folder out of what the part reads."""

import shutil
import subprocess
from pathlib import Path

import hiro_work as hw

ENGINE = Path(__file__).resolve().parent.parent / "check-engine.sh"

CHECK_SH = r"""#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/../../hiroleague/build-kit/check-engine.sh" "$@"
part "frontend: leaves memory out" "frontend @hiroleague:ui-kit/src/lib -@hiroleague:ui-kit/src/lib/memory @hiroleague:ui-kit/scripts" true
part "frontend: reads all" "frontend @hiroleague:ui-kit/src/lib @hiroleague:ui-kit/scripts" true
check_done
"""


def sh(*args, cwd):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def commit_all(repo: Path) -> None:
    sh("git", "add", "-A", cwd=repo)
    sh("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "x", cwd=repo)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def check(app: Path) -> str:
    out = sh(hw.bash(), "scripts/check.sh", cwd=app)
    assert out.returncode == 0, out.stdout + out.stderr
    return out.stdout


def test_a_left_out_folder_does_not_start_the_part(tmp_path):
    core, app = tmp_path / "hiroleague", tmp_path / "app"
    (core / "build-kit").mkdir(parents=True)
    shutil.copy(ENGINE, core / "build-kit" / "check-engine.sh")
    write(core / "ui-kit/src/lib/ui/a.ts", "a")
    write(core / "ui-kit/src/lib/memory/m.ts", "m")
    write(core / "ui-kit/scripts/s.js", "s")
    write(app / "frontend/x.txt", "x")
    write(app / "scripts/check.sh", CHECK_SH)
    for repo in (core, app):
        sh("git", "init", "-q", cwd=repo)
        commit_all(repo)

    first = check(app)
    assert "all passed" in first

    # Nothing changed: both parts passed on these files
    assert "nothing to check" in check(app)

    # A change under the left-out folder: only the part that reads it runs
    write(core / "ui-kit/src/lib/memory/m.ts", "m2")
    out = check(app)
    assert "frontend: leaves memory out: skipped" in out
    assert "started: frontend: reads all" in out

    # A change elsewhere in the kit: both run
    write(core / "ui-kit/src/lib/ui/a.ts", "a2")
    out = check(app)
    assert "started: frontend: leaves memory out" in out
    assert "started: frontend: reads all" in out
