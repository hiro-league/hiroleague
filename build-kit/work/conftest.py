"""What every hiro-work test shares: nothing from the shell that runs it."""

import os

import pytest


@pytest.fixture(autouse=True)
def no_inherited_git(monkeypatch):
    """Drop the GIT_* variables the test run inherits, so a test's git commands act on its own tmp repo only.

    Why: a git hook, or a deploy, runs the check with GIT_DIR, GIT_WORK_TREE or GIT_INDEX_FILE set, and those win
    over `git -C <tmp>`. A test that ran `git init` and committed under Simone's deploy re-initialised the live
    bare repo as a work tree and put its commits on main.
    """
    for name in [n for n in os.environ if n.startswith("GIT_") and n != "GIT_EXEC_PATH"]:
        monkeypatch.delenv(name)
