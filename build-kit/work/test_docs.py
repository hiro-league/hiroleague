"""hiro-work docs: the docs desk publishes documents only, moves hiro-docs alone, and stops for other merged work."""

import json
import subprocess

import pytest

import docs
import hiro_work as hw


def git(cwd, *args) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def house(tmp_path, monkeypatch):
    """env0's hiro-docs on dev with one document, GitHub and Simone as bare repos beside it, and a log of its own."""
    monkeypatch.setattr(hw, "ROOT", tmp_path)
    monkeypatch.setattr(hw, "LOGS", tmp_path / "logs")
    monkeypatch.setattr(hw, "EVENTS", tmp_path / "logs" / "events.jsonl")
    monkeypatch.setattr(docs, "DESK", tmp_path / "docs" / "hiro-docs")
    for bare in ("github.git", "simone.git"):
        git(tmp_path, "init", "-q", "--bare", "-b", "main", bare)
    main = tmp_path / "env0" / "hiro-docs"
    (main / "standards").mkdir(parents=True)
    git(main, "init", "-q", "-b", "dev")
    git(main, "config", "user.name", "t")
    git(main, "config", "user.email", "t@t")
    (main / "standards" / "rules.md").write_text("# Rules\n\n- one\n", "utf-8")
    (main / "standards" / "plans.md").write_text("# Plans\n", "utf-8")
    git(main, "add", "standards")
    git(main, "commit", "-q", "-m", "the standard")
    git(main, "remote", "add", "origin", str(tmp_path / "github.git"))
    git(main, "remote", "add", "server", str(tmp_path / "simone.git"))
    git(main, "push", "-q", "origin", "dev")
    git(main, "push", "-q", "server", "dev:main")
    return tmp_path


def run(*argv) -> int:
    return hw.main(["docs", *argv])


def events(house) -> list[dict]:
    log = house / "logs" / "events.jsonl"
    return [json.loads(line) for line in log.read_text("utf-8").splitlines()] if log.exists() else []


def shipped(house) -> tuple[str, str, str]:
    """env0's dev, GitHub's dev and Simone's main."""
    return (git(house / "env0" / "hiro-docs", "rev-parse", "dev"), git(house / "github.git", "rev-parse", "dev"),
            git(house / "simone.git", "rev-parse", "main"))


def test_open_makes_the_desk_on_its_own_branch_at_dev(house):
    assert run("open") == 0
    desk = house / "docs" / "hiro-docs"
    assert git(desk, "branch", "--show-current") == "docs-desk"
    assert git(desk, "rev-parse", "HEAD") == git(house / "env0" / "hiro-docs", "rev-parse", "dev")


def test_a_publish_puts_the_change_in_env0_on_github_and_on_simone_and_says_so(house):
    run("open")
    desk = house / "docs" / "hiro-docs"
    (desk / "standards" / "rules.md").write_text("# Rules\n\n- one\n- two\n", "utf-8")
    (desk / "standards" / "guides").mkdir()
    (desk / "standards" / "guides" / "ui.md").write_text("# UI rules\n", "utf-8")
    assert run("publish", "-m", "Rules: two") == 0
    main = house / "env0" / "hiro-docs"
    assert (main / "standards" / "rules.md").read_text("utf-8").endswith("- two\n")  # every session reads it
    assert (main / "standards" / "guides" / "ui.md").exists()
    here, github, simone = shipped(house)
    assert here == github == simone
    assert docs.TRAILER in git(main, "log", "-1", "--format=%B")
    last = events(house)[-1]
    assert (last["step"], last["ok"], last["commit"], last["subject"]) == ("docs", True, here, "Rules: two")
    assert sorted(last["files"]) == ["standards/guides/ui.md", "standards/rules.md"]


def test_anything_but_a_document_stops_the_publish_and_nothing_moves(house, capsys):
    run("open")
    desk = house / "docs" / "hiro-docs"
    before = shipped(house)
    (desk / "standards" / "rules.md").write_text("# Rules\n\n- changed\n", "utf-8")
    (desk / "standards" / "tools").mkdir()
    (desk / "standards" / "tools" / "guard.py").write_text("x = 1\n", "utf-8")
    assert run("publish", "-m", "x") == 1
    assert "standards/tools/guard.py" in capsys.readouterr().out
    assert shipped(house) == before
    assert git(desk, "rev-parse", "HEAD") == before[0]  # nothing committed


def test_other_merged_work_waiting_in_hiro_docs_stops_it_until_it_may_go_along(house, capsys):
    run("open")
    main, desk = house / "env0" / "hiro-docs", house / "docs" / "hiro-docs"
    # another task merged a doc change into env0's dev; no deploy has pushed it
    (main / "standards" / "plans.md").write_text("# Plans\n\nmerged by a task\n", "utf-8")
    git(main, "commit", "-q", "-am", "A task's merged change")
    before = shipped(house)
    (desk / "standards" / "rules.md").write_text("# Rules\n\n- mine\n", "utf-8")
    assert run("publish", "-m", "Rules: mine") == 1
    out = capsys.readouterr().out
    assert "A task's merged change" in out and "--with-merged" in out
    assert shipped(house) == before
    assert run("publish", "-m", "Rules: mine", "--with-merged") == 0
    here, github, simone = shipped(house)
    assert here == github == simone != before[0]
    assert "merged by a task" in (main / "standards" / "plans.md").read_text("utf-8")
    assert git(main, "log", "--merges", "--oneline") == ""  # the desk followed dev first: the history is a line


def test_a_publish_that_wasnt_pushed_is_the_desks_own_and_goes_with_the_next(house, monkeypatch):
    run("open")
    desk = house / "docs" / "hiro-docs"
    (desk / "standards" / "rules.md").write_text("# Rules\n\n- first\n", "utf-8")
    # Only this patch is taken back: monkeypatch.undo() would also undo the suite's own (no inherited GIT_* variables),
    # and under a commit's hook the test's git commands would then act on the committing repo
    with monkeypatch.context() as m:
        m.setattr(docs, "push", lambda main: ["GitHub: the push failed"])
        assert run("publish", "-m", "Rules: first") == 1  # in force here, not pushed
    assert run("publish") == 0  # no new change, no --with-merged: only its own commit waited
    here, github, simone = shipped(house)
    assert here == github == simone


def test_dev_changing_the_same_lines_keeps_the_change_in_the_desk_and_says_how_to_settle_it(house, capsys):
    run("open")
    main, desk = house / "env0" / "hiro-docs", house / "docs" / "hiro-docs"
    (main / "standards" / "rules.md").write_text("# Rules\n\n- theirs\n", "utf-8")
    git(main, "commit", "-q", "-am", "A task's change to the same line")
    git(main, "push", "-q", "origin", "dev")
    git(main, "push", "-q", "server", "dev:main")
    before = shipped(house)
    (desk / "standards" / "rules.md").write_text("# Rules\n\n- mine\n", "utf-8")
    assert run("publish", "-m", "Rules: mine") == 1
    assert "git merge dev" in capsys.readouterr().out
    assert shipped(house) == before
    assert git(desk, "status", "--porcelain") == ""  # the merge was called off; the change is a commit in the desk


def test_nothing_changed_is_nothing_to_publish(house, capsys):
    run("open")
    assert run("publish", "-m", "x") == 1
    assert "Nothing to publish" in capsys.readouterr().out


def test_a_document_list_that_names_a_missing_file_stops_the_publish(house, capsys):
    run("open")
    desk = house / "docs" / "hiro-docs"
    (desk / "standards" / "docs.toml").write_text(
        '[[tab]]\nid = "rules"\ntitle = "Rules"\n[[tab.doc]]\nid = "rules"\ntitle = "Rules"\npath = "standards/gone.md"\n',
        "utf-8")
    assert run("publish", "-m", "The list") == 1
    assert "standards/gone.md" in capsys.readouterr().out
    (desk / "standards" / "docs.toml").write_text(
        '[[tab]]\nid = "rules"\ntitle = "Rules"\n[[tab.doc]]\nid = "rules"\ntitle = "Rules"\npath = "standards/rules.md"\n',
        "utf-8")
    assert run("publish", "-m", "The list") == 0


def test_undo_takes_the_last_publish_back_as_a_publish_of_its_own(house, capsys):
    run("open")
    main, desk = house / "env0" / "hiro-docs", house / "docs" / "hiro-docs"
    (desk / "standards" / "rules.md").write_text("# Rules\n\n- one\n- two\n", "utf-8")
    run("publish", "-m", "Rules: two")
    assert run("undo") == 0
    assert (main / "standards" / "rules.md").read_text("utf-8") == "# Rules\n\n- one\n"
    assert git(main, "log", "-1", "--format=%s") == "Undo: Rules: two"
    here, github, simone = shipped(house)
    assert here == github == simone
    capsys.readouterr()
    # what a task merged is never undone from the desk
    (main / "standards" / "plans.md").write_text("# Plans\n\ntask\n", "utf-8")
    git(main, "commit", "-q", "-am", "A task's merged change")
    assert run("undo") == 1
    assert "isn't a docs publish" in capsys.readouterr().out


def test_sweep_doesnt_call_the_desk_a_stray_worktree(house, monkeypatch, capsys):
    run("open")
    monkeypatch.setattr(hw, "REPOS", ["hiro-docs"])
    import plan
    monkeypatch.setattr(plan, "whole_branches", lambda: {})
    hw.cmd_sweep(None)
    assert "worktree outside" not in capsys.readouterr().out
