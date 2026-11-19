"""Point every Hiro League repo's git hooks at this folder (core.hooksPath), in every environment.

    python build-kit/git-hooks/install.py           # install (safe to run again)
    python build-kit/git-hooks/install.py --check   # say which repos have them, change nothing
    python build-kit/git-hooks/install.py --remove  # back to each repo's own .git/hooks

The hooks path is env0's core, `C:/hiro/env0/hiroleague/build-kit/git-hooks`, the one core folder every repo reads
the build kit from (hiro-docs standards/README.md, "Checkouts"). env1 to env5 are git worktrees of env0's repos and
share their config, so one setting per repo covers every environment; the loop below still looks at each folder, so
a repo that isn't a worktree of env0 gets its own.

hiro-work should run this when it makes an environment (`hiro-work init`, after its worktrees are added) and at the end
of `start` for a new repo; until then, run it by hand after `hiro-work init`.

Standard library only.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(os.environ.get("HIRO_ROOT", r"C:\hiro"))
# Every repo an environment holds, as hiro-work lists them: the core, the apps of build-kit/work/apps.toml, aicam, hiro-docs.
_APPS = tomllib.loads((Path(__file__).resolve().parents[1] / "work" / "apps.toml").read_text(encoding="utf-8"))["app"]
REPOS = ["hiroleague", *(a["repo"] for a in _APPS), "aicam", "hiro-docs"]
HOOKS = (ROOT / "env0" / "hiroleague" / "build-kit" / "git-hooks").as_posix()


def git(folder: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(folder), *args], check=False, capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else ""


def main(argv: list[str]) -> int:
    mode = argv[0] if argv else "--install"
    if mode not in ("--install", "--check", "--remove"):
        print(__doc__)
        return 2
    if mode == "--install" and not Path(HOOKS).is_dir():
        print(f"{HOOKS} isn't there yet (env0's core is behind): merge the change that adds it first.")
        return 1
    seen: set[str] = set()
    for env in range(6):
        for repo in REPOS:
            d = ROOT / f"env{env}" / repo
            if not (d / ".git").exists():
                continue
            common = Path(d, git(d, "rev-parse", "--git-common-dir")).resolve().as_posix().lower()
            if common in seen:
                continue
            seen.add(common)
            now = git(d, "config", "--get", "core.hooksPath")
            if mode == "--check":
                other = f" ({now})" if now and now != HOOKS else ""
                print(f"{'ok     ' if now == HOOKS else 'missing'}  env{env} {repo}{other}")
            elif mode == "--remove":
                if now:
                    git(d, "config", "--unset", "core.hooksPath")
                    print(f"removed  env{env} {repo}")
            elif now != HOOKS:
                git(d, "config", "core.hooksPath", HOOKS)
                print(f"set      env{env} {repo}")
            else:
                print(f"ok       env{env} {repo}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
