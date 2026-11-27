r"""hiro-work docs: the docs desk, the fast lane for the standard's documents (hiro-docs standards/workflow.md,
"The docs desk").

A change to the standard's documents alone is no task. It is edited in the desk, a standing folder of hiro-docs
(C:\hiro\docs\hiro-docs, on the branch docs-desk), and published in one step:

    hiro-work docs open                    makes the desk when it is missing, brings it up to env0's dev, and says
                                           what is changed there
    hiro-work docs publish -m "<what>"     commits the changed documents, brings env0's hiro-docs up to them (every
                                           session reads them at once), pushes hiro-docs to GitHub (dev) and to Simone
                                           (main, which CodeHiro's Workflow Docs page reads), and tells CodeHiro
    hiro-work docs undo                    takes the last publish back, as a publish of its own

Only documents travel this way: standards/**/*.md and the page's document list (standards/docs.toml). Anything else
changed in the desk stops the publish: code goes through a task. Only hiro-docs moves; when another task's merged work
waits in it unshipped, the publish stops and lists it, until Michel says it may go along (--with-merged).
Standard library only.
"""

from __future__ import annotations

import argparse
import subprocess
import time
import tomllib
from pathlib import Path, PurePosixPath

import hiro_work as hw

REPO = "hiro-docs"
DESK = hw.ROOT / "docs" / REPO
BRANCH = "docs-desk"
INDEX = "standards/docs.toml"  # the documents CodeHiro's Workflow Docs page shows, and their tabs
# A publish's commit says so in its message: the next publish tells its own unshipped commits from another task's
TRAILER = "Docs-Desk: publish"
STEP = "docs"
PAGE = "http://code.hiro.local/workflow-docs"


def main_dir() -> Path:
    return hw.repo_dir(0, REPO)


def main_branch() -> str:
    return hw.main_of(REPO)


def is_document(path: str) -> bool:
    """What the desk publishes: a Markdown document of the standard, or the page's document list."""
    return path == INDEX or (path.startswith("standards/") and path.endswith(".md"))


def changed(folder: Path) -> list[str]:
    """The folder's changed, staged and new files (a renamed file's old and new names), .gitignore respected."""
    # Not hw.git: it strips the output, and a changed file's line starts with a space (" M path")
    out = subprocess.run(["git", "-C", str(folder), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
                         creationflags=hw.NO_WINDOW)
    if out.returncode != 0:
        raise hw.Stop(f"git status failed in {folder}:\n{(out.stderr or out.stdout).strip()[-800:]}")
    parts = out.stdout.split("\0")
    files: list[str] = []
    i = 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if len(entry) < 4:
            continue
        files.append(entry[3:])
        if entry[0] in "RC" or entry[1] in "RC":  # a rename or a copy: its other name is the next field
            if i < len(parts) and parts[i]:
                files.append(parts[i])
            i += 1
    return sorted(set(files))


def tip(folder: Path, ref: str) -> str:
    return hw.git(folder, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}", check=False)


def has_desk() -> bool:
    return (DESK / ".git").exists()


def bring_up(say: bool = True) -> str | None:
    """The desk, moved up to env0's dev when dev has commits it lacks. Returns why it couldn't (the desk's own
    changes are in the files dev changed), else None."""
    main = main_branch()
    if hw.is_ancestor(DESK, main, "HEAD"):
        return None
    out = subprocess.run(["git", "-C", str(DESK), "merge", "--ff-only", "-q", main], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", check=False, creationflags=hw.NO_WINDOW)
    if out.returncode == 0:
        if say:
            hw.say(f"  the desk moved up to {main} ({tip(DESK, 'HEAD')[:8]})")
        return None
    return (out.stderr or out.stdout).strip()[-600:]


def ensure_desk() -> None:
    """Make the desk when it is missing: a worktree of env0's hiro-docs on its own branch, starting at dev."""
    if has_desk():
        return
    DESK.parent.mkdir(parents=True, exist_ok=True)
    hw.git(main_dir(), "worktree", "prune")
    hw.git(main_dir(), "worktree", "add", "-q", "-B", BRANCH, str(DESK), main_branch())
    hw.say(f"The docs desk is made: {DESK} (branch {BRANCH}, at {main_branch()}).")


def cmd_open(a) -> None:
    ensure_desk()
    why = bring_up()
    files = changed(DESK)
    hw.say(f"The docs desk: {DESK}")
    if why:
        hw.say(f"  It is behind {main_branch()}, and its own changes are in the same files: the publish merges them.")
    if not files:
        hw.say("  Nothing is changed there. Edit the documents under standards\\, then: hiro-work docs publish -m "
               "\"<what changed>\"")
        return
    hw.say("  Changed, not published:")
    for f in files:
        hw.say(f"    {f}" + ("" if is_document(f) else "   (not a document: the desk doesn't publish it)"))


def check_index(folder: Path) -> None:
    """The page's document list, read as CodeHiro reads it: a broken one would leave the page with no documents."""
    path = folder / INDEX
    if not path.exists():
        return
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise hw.Stop(f"{INDEX} can't be read: {exc}") from exc
    tabs = data.get("tab")
    if not isinstance(tabs, list) or not tabs:
        raise hw.Stop(f"{INDEX} lists no tab ([[tab]]).")
    tab_ids: set[str] = set()
    doc_ids: set[str] = set()
    for t in tabs:
        tid = t.get("id") if isinstance(t, dict) else None
        if not isinstance(tid, str) or not tid or not isinstance(t.get("title"), str) or not t["title"]:
            raise hw.Stop(f"{INDEX}: every tab has an id and a title.")
        if tid in tab_ids:
            raise hw.Stop(f"{INDEX}: two tabs are called '{tid}'.")
        tab_ids.add(tid)
        docs = t.get("doc")
        if not isinstance(docs, list) or not docs:
            raise hw.Stop(f"{INDEX}: the tab '{tid}' lists no document ([[tab.doc]]).")
        for d in docs:
            did = d.get("id") if isinstance(d, dict) else None
            if not all(isinstance(d.get(k), str) and d[k] for k in ("id", "title", "path")):
                raise hw.Stop(f"{INDEX}: every document of '{tid}' has an id, a title and a path.")
            if did in doc_ids:
                raise hw.Stop(f"{INDEX}: two documents are called '{did}'.")
            doc_ids.add(did)
            rel = PurePosixPath(d["path"])
            if rel.is_absolute() or ".." in rel.parts or not (folder / rel).is_file():
                raise hw.Stop(f"{INDEX}: '{did}' names {d['path']}, which isn't a file in hiro-docs.")


def is_publish(folder: Path, sha: str) -> bool:
    return TRAILER in hw.git(folder, "log", "-1", "--format=%B", sha, check=False)


def unshipped(main: Path) -> list[tuple[str, str]]:
    """The commits env0's dev holds that GitHub or Simone lacks: (sha, subject), the oldest first. Stops when either
    holds commits dev lacks: pushes are fast-forward only."""
    branch = main_branch()
    for remote, ref, where in (("origin", f"origin/{branch}", "GitHub"), ("server", "server/main", "Simone")):
        out = subprocess.run(["git", "-C", str(main), "fetch", "-q", remote], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", check=False, creationflags=hw.NO_WINDOW)
        if out.returncode != 0:
            raise hw.Stop(f"{where} can't be reached, so nothing is published (git fetch {remote}):\n"
                          f"{(out.stderr or out.stdout).strip()[-600:]}")
        if tip(main, ref) and not hw.is_ancestor(main, ref, branch):
            raise hw.Stop(f"{where} has hiro-docs commits this PC lacks ({ref}): bring them here first, and tell "
                          "Michel. Nothing is published.")
    seen: dict[str, str] = {}
    for ref in (f"origin/{branch}", "server/main"):
        spec = f"{ref}..{branch}" if tip(main, ref) else branch
        for line in hw.git(main, "log", "--reverse", "--format=%H%x09%s", spec).splitlines():
            sha, _, subject = line.partition("\t")
            seen.setdefault(sha, subject)
    return list(seen.items())


def push(main: Path) -> list[str]:
    """hiro-docs to GitHub (dev) and to Simone (main); returns what failed, in words."""
    branch = main_branch()
    failed = []
    for remote, spec, where in (("origin", branch, "GitHub"), ("server", f"{branch}:main", "Simone")):
        out = subprocess.run(["git", "-C", str(main), "push", "-q", remote, spec], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", check=False, creationflags=hw.NO_WINDOW)
        if out.returncode != 0:
            lines = (out.stderr or out.stdout).strip().splitlines()
            failed.append(f"{where}: {lines[-1] if lines else 'the push failed'}"[:300])
    return failed


def publish(message: str | None, with_merged: bool) -> None:
    if not has_desk():
        raise hw.Stop("There is no docs desk yet: hiro-work docs open")
    started = time.monotonic()
    main, branch = main_dir(), main_branch()
    files = changed(DESK)
    others = [f for f in files if not is_document(f)]
    if others:
        raise hw.Stop("The desk publishes documents only (standards/**/*.md and " + INDEX + "). Also changed there:\n  "
                      + "\n  ".join(others) + "\nCode goes through a task: take these out of the desk first.")
    if hw.git(main, "branch", "--show-current") != branch:
        raise hw.Stop(f"env0's hiro-docs isn't on {branch}: nothing is published until it is.")
    if hw.git(main, "status", "--porcelain", "--untracked-files=no"):
        raise hw.Stop("env0's hiro-docs has changed files of its own: nothing is published until they are gone.")
    waiting = unshipped(main)
    mine_waiting = [w for w in waiting if is_publish(main, w[0])]
    theirs = [w for w in waiting if w not in mine_waiting]
    if theirs and not with_merged:
        raise hw.Stop("Other merged work waits in hiro-docs, and a publish would push it too:\n  "
                      + "\n  ".join(f"{sha[:8]} {subject}" for sha, subject in theirs)
                      + "\nNothing is published. With Michel's OK for these: hiro-work docs publish --with-merged ...")
    if not files and hw.is_ancestor(DESK, "HEAD", branch) and not waiting:
        raise hw.Stop("Nothing to publish: the desk has no changed document.")
    sha = None
    if files:
        if not (message or "").strip():
            raise hw.Stop("Say what changed: hiro-work docs publish -m \"<what changed>\" (the page's history shows "
                          "it).")
        check_index(DESK)
        bring_up()  # dev's new commits first, when the desk's changes are in other files: the history stays a line
        hw.git(DESK, "add", "--", *files)
        hw.git(DESK, "commit", "-q", "-m", message.strip(), "-m", TRAILER)
        sha = tip(DESK, "HEAD")
    if not hw.is_ancestor(DESK, branch, "HEAD"):
        # dev changed the same files since the desk last followed it: a real merge
        out = subprocess.run(["git", "-C", str(DESK), "merge", "--no-edit", "-q", branch], capture_output=True,
                             text=True, encoding="utf-8", errors="replace", check=False, creationflags=hw.NO_WINDOW)
        if out.returncode != 0:
            hw.git(DESK, "merge", "--abort", check=False)
            raise hw.Stop(f"{branch} changed the same lines since the desk last followed it. The change is committed "
                          f"in the desk ({(sha or '')[:8]}), not published. In {DESK}: git merge {branch}, settle the "
                          "conflict, commit, then publish again.")
        check_index(DESK)
    new = tip(DESK, "HEAD")
    old = tip(main, branch)
    if new != old:
        hw.git(main, "merge", "--ff-only", "-q", BRANCH)
    shipped = hw.git(main, "diff", "--name-only", f"{old}..{new}").splitlines() if new != old else []
    failed = push(main)
    subject = hw.git(main, "log", "-1", "--format=%s", new)
    hw.event(task=None, env=None, repo=REPO, step=STEP, phase="end", ok=not failed,
             seconds=round(time.monotonic() - started, 1), commit=new, subject=subject, files=shipped,
             **({"error": "; ".join(failed)[:300]} if failed else {}))
    if failed:
        raise hw.Stop(f"In force on this PC ({new[:8]}: every session reads it), but not pushed:\n  "
                      + "\n  ".join(failed) + "\nPublish again to push it.")
    hw.say(f"Published {new[:8]}: {subject}")
    for f in shipped:
        hw.say(f"  {f}")
    if theirs:
        hw.say(f"  with {len(theirs)} merged commit(s) that waited in hiro-docs")
    hw.say(f"In force on this PC, on GitHub ({branch}) and on Simone: {PAGE}")


def cmd_undo(a) -> None:
    if not has_desk():
        raise hw.Stop("There is no docs desk yet: hiro-work docs open")
    if changed(DESK):
        raise hw.Stop("The desk has changes not published: publish them or take them out first.")
    why = bring_up()
    if why:
        raise hw.Stop(f"The desk can't follow {main_branch()}:\n{why}")
    last = tip(DESK, "HEAD")
    if not is_publish(DESK, last):
        raise hw.Stop("The last change to hiro-docs isn't a docs publish: it is undone through a task.")
    subject = hw.git(DESK, "log", "-1", "--format=%s", last)
    hw.git(DESK, "revert", "--no-commit", last)
    try:
        publish(a.message or f"Undo: {subject}", a.with_merged)
    except hw.Stop:
        if tip(DESK, "HEAD") == last:  # nothing was committed: leave the desk as it was
            hw.git(DESK, "revert", "--abort", check=False)
        raise


def cmd_docs(a) -> None:
    if a.what == "open":
        cmd_open(a)
    elif a.what == "publish":
        publish(a.message, a.with_merged)
    else:
        cmd_undo(a)


def add_parser(sub) -> None:
    p = sub.add_parser("docs", help="the docs desk: open, publish -m \"<what changed>\", undo",
                       formatter_class=argparse.RawDescriptionHelpFormatter, description=__doc__.split("\n\n", 1)[1])
    p.add_argument("what", choices=["open", "publish", "undo"])
    p.add_argument("-m", "--message", help="publish: what changed, in a few words (the page's history shows it)")
    p.add_argument("--with-merged", action="store_true",
                   help="publish: also push other tasks' merged work that waits in hiro-docs (Michel's OK)")
    p.set_defaults(func=cmd_docs)
