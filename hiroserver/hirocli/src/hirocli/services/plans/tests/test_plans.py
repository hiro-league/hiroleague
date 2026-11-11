"""Phase 7a Part B: plan tools — parsers, the strict schema, lines, sign-in and an ask against fake tools.

The fake tools are small Python scripts standing in for ``claude`` / ``codex`` (``cli.command`` is pointed at
them), so nothing here needs Node, npm, the real tools or a plan.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from hirocli.services.ai_ask.errors import AskError, ProviderFailed
from hirocli.services.ai_ask.providers import PlanCall
from hirocli.services.plans import cli, kinds, status, strict, updates
from hirocli.services.plans.kinds import PLAN_KINDS
from hirocli.services.plans.models import plan_models
from hirocli.services.plans.provider import Line, PlanToolProvider
from hirocli.services.plans.signin import SignIns

CLAUDE = PLAN_KINDS["claude_code"]
CODEX = PLAN_KINDS["codex"]

FAKE_CLAUDE = r'''
import json, os, sys
args = sys.argv[1:]
home = os.environ["CLAUDE_CONFIG_DIR"]
if args[:2] == ["auth", "status"]:
    print(json.dumps({"loggedIn": os.path.exists(os.path.join(home, "in")), "authMethod": "claude.ai",
                      "email": "owner@example.com", "subscriptionType": "max"}))
elif args[:2] == ["auth", "login"]:
    print("Open https://claude.ai/oauth/authorize?code=true&client_id=x", flush=True)
    code = sys.stdin.readline().strip()
    if code != "good-code":
        print("Invalid code"); sys.exit(1)
    open(os.path.join(home, "in"), "w").close()
    print("Login successful")
elif "-p" in args:
    prompt = sys.stdin.read()
    schema = json.loads(args[args.index("--json-schema") + 1]) if "--json-schema" in args else None
    assert "OPENAI_API_KEY" not in os.environ and "HIRO_SECRET" not in os.environ, "core secrets leaked"
    pictures = sorted(f for f in os.listdir(".") if f.endswith(".jpg"))
    tools = args[args.index("--tools") + 1] if "--tools" in args else None
    sources = args[args.index("--setting-sources") + 1] if "--setting-sources" in args else None
    print(json.dumps({"is_error": False, "result": "ok",
                      "structured_output": {"saw": len(pictures), "said": prompt[:20], "cwd": os.getcwd(), "tools": tools,
                                            "sources": sources, "files": sorted(os.listdir("."))},
                      "usage": {"input_tokens": 10, "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 0,
                                "output_tokens": 20},
                      "modelUsage": {"claude-sonnet-5-5": {}}}))
'''

FAKE_CODEX = r'''
import sys
args = sys.argv[1:]
if args[:2] == ["login", "--device-auth"]:
    print("Go to https://auth.openai.com/codex/device and enter ABCD-12345", flush=True)
    sys.exit(0)
if args[:2] == ["login", "status"]:
    print("Logged in using ChatGPT", file=sys.stderr)
'''


@pytest.fixture
def fake_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    scripts = {"claude_code": tmp_path / "claude.py", "codex": tmp_path / "codex.py"}
    scripts["claude_code"].write_text(FAKE_CLAUDE, encoding="utf-8")
    scripts["codex"].write_text(FAKE_CODEX, encoding="utf-8")
    monkeypatch.setattr(cli, "command", lambda ws, kind, args: [sys.executable, str(scripts[kind.id]), *args])
    monkeypatch.setenv("HIRO_SECRET", "must-not-reach-the-tool")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-must-not-reach-the-tool")
    return tmp_path / "ws"


def test_parsers_read_what_the_tools_print() -> None:
    s = CLAUDE.status(0, json.dumps({"loggedIn": True, "authMethod": "claude.ai", "email": "a@b.c", "subscriptionType": "max"}), "")
    assert (s.signed_in, s.account, s.plan, s.method) == (True, "a@b.c", "Max", "Claude account")
    assert CLAUDE.status(1, '{"loggedIn": false}', "").signed_in is False
    with pytest.raises(ValueError):
        CLAUDE.status(1, "not json", "")
    assert CODEX.status(0, "", "Logged in using ChatGPT").method == "ChatGPT"
    assert CODEX.status(1, "", "Not logged in").signed_in is False
    seen = CODEX.signin_text("\x1b[1mGo to https://auth.openai.com/device\x1b[0m\nCode: WXYZ-9876")
    assert (seen.link, seen.code) == ("https://auth.openai.com/device", "WXYZ-9876")
    blocked = CODEX.signin_text("Enable device code authorization in ChatGPT Security settings first")
    assert blocked.blocked
    a = CODEX.answered(0, '{"seen": null, "n": 1}', "model: gpt-6.1-sol\ntokens used\n 1,234\n", "x",
                       {"type": "object", "properties": {"seen": {"type": "boolean"}, "n": {"type": "integer"}}, "required": ["n"]})
    assert json.loads(a.text) == {"n": 1} and a.tokens_total == 1234 and a.model == "gpt-6.1-sol"
    with pytest.raises(kinds.AnswerUnreadable):
        CODEX.answered(1, "", "error: not signed in", "x", None)


def test_strict_closes_every_object_and_opens_the_answer_again() -> None:
    schema = {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "object", "properties": {"c": {"type": "integer"}}}},
              "required": ["a"]}
    closed = strict.closed(schema)
    assert closed["additionalProperties"] is False and closed["required"] == ["a", "b"]
    assert closed["properties"]["b"]["additionalProperties"] is False and "null" in closed["properties"]["b"]["type"]
    assert json.loads(strict.opened('{"a": "x", "b": null}', schema)) == {"a": "x"}


def test_updates_run_once_a_night_after_four() -> None:
    now = datetime(2026, 11, 8, 5, 0).astimezone()
    assert updates.due(None, now)
    assert updates.due(now - timedelta(days=1), now)
    assert not updates.due(now.replace(hour=4, minute=30), now)
    assert updates.next_run(now.replace(hour=3)).hour == 4
    assert updates.next_run(now).day == 9


def test_the_nightly_update_only_runs_where_plan_tools_are_used(tmp_path: Path) -> None:
    assert updates.updater.nightly_due(tmp_path, uses_plans=False) is False
    assert updates.updater.nightly_due(tmp_path, uses_plans=True) is True  # missing tools: install


def test_a_line_runs_at_once_waiting_asks_queue_and_an_apps_ask_is_busy() -> None:
    async def scenario() -> None:
        line = Line()
        await line.enter(1, wait=True, who="Codex")
        with pytest.raises(AskError) as err:
            await line.enter(1, wait=False, who="Codex")
        assert err.value.code == "busy"
        waiter = asyncio.create_task(line.enter(1, wait=True, who="Codex"))
        await asyncio.sleep(0.01)
        assert not waiter.done()
        line.leave()
        await asyncio.wait_for(waiter, 1)
        assert line.running == 1

    asyncio.run(scenario())


def test_claude_sign_in_takes_the_pasted_code_and_status_reads_it(fake_tools: Path) -> None:
    ws = fake_tools
    signins = SignIns()
    out = signins.begin(ws, CLAUDE)
    for _ in range(100):
        if out.link:
            break
        time.sleep(0.05)
        out = signins.state(ws, CLAUDE)
    assert out.state == "waiting" and out.takes_code and out.link.startswith("https://claude.ai/oauth/authorize")
    signins.send_code(ws, CLAUDE, "good-code")
    for _ in range(100):
        out = signins.state(ws, CLAUDE)
        if out.state != "waiting":
            break
        time.sleep(0.05)
    assert out.state == "done"
    seen = status.view(ws, CLAUDE)
    assert seen.status is not None and seen.status.signed_in and seen.status.plan == "Max"
    assert seen.ends_at is not None and seen.ends_at - seen.signed_in_at == timedelta(days=30)


def test_codex_device_sign_in_shows_link_and_code(fake_tools: Path) -> None:
    signins = SignIns()
    signins.begin(fake_tools, CODEX)
    for _ in range(100):
        out = signins.state(fake_tools, CODEX)
        if out.state != "waiting":
            break
        time.sleep(0.05)
    assert out.state == "done"  # the fake prints its code and finishes at once


def test_an_ask_on_claude_code_writes_pictures_in_its_own_folder_with_a_clean_env(fake_tools: Path) -> None:
    provider = PlanToolProvider(CLAUDE)
    call = PlanCall(
        model="sonnet", prompt="What is on the pictures?", pictures=[b"one", b"two"],
        schema={"type": "object", "properties": {"saw": {"type": "integer"}}}, thinking="off", timeout=30, wait=True,
        workspace_path=fake_tools,
    )
    result = asyncio.run(provider.answer(call))
    answer = json.loads(result.text)
    assert answer["saw"] == 2 and answer["said"].startswith("What is on the")
    assert (result.tokens_in, result.tokens_out, result.model) == (1010, 20, "claude-sonnet-5-5")
    assert result.estimate is not None and result.estimate > 0  # Sonnet's catalog price, cache read at its rate
    assert list((cli.work_folder(fake_tools)).iterdir()) == []  # the ask's folder is gone
    assert provider.effort(fake_tools, "sonnet", "off") == "low"  # Claude Code has no "off"


def test_an_ask_with_a_folder_runs_in_it_with_look_only_tools_and_leaves_it_untouched(fake_tools: Path, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("print('hi')", encoding="utf-8")
    call = PlanCall(model="sonnet", prompt="Review this", pictures=[], schema={"type": "object"}, thinking=None,
                    timeout=30, wait=True, workspace_path=fake_tools, folder=repo)
    answer = json.loads(asyncio.run(PlanToolProvider(CLAUDE).answer(call)).text)
    assert Path(answer["cwd"]).resolve() == repo.resolve()  # the tool starts in the folder…
    assert answer["tools"] == "Read,Glob,Grep" and answer["sources"] == "user"  # …may only look, and ignores its settings
    assert answer["files"] == ["main.py"] and sorted(p.name for p in repo.iterdir()) == ["main.py"]  # nothing added
    assert list(cli.work_folder(fake_tools).iterdir()) == []  # the ask's own folder is gone
    # Pictures and a folder never go together; a folder that is gone fails the ask so the walk moves on.
    both = PlanCall(model="sonnet", prompt="q", pictures=[b"x"], schema=None, thinking=None, timeout=5, wait=True,
                    workspace_path=fake_tools, folder=repo)
    with pytest.raises(ProviderFailed):
        asyncio.run(PlanToolProvider(CLAUDE).answer(both))
    gone = PlanCall(model="sonnet", prompt="q", pictures=[], schema=None, thinking=None, timeout=5, wait=True,
                    workspace_path=fake_tools, folder=tmp_path / "gone")
    with pytest.raises(ProviderFailed):
        asyncio.run(PlanToolProvider(CLAUDE).answer(gone))


def test_codex_keeps_its_schema_file_out_of_the_folder_it_reads(tmp_path: Path) -> None:
    ask, repo = tmp_path / "ask", tmp_path / "repo"
    ask.mkdir()
    repo.mkdir()
    args, _ = CODEX.question(ask, "gpt-6.1-sol", None, "Review", [], {"type": "object"}, repo)
    assert args[args.index("--output-schema") + 1] == str(ask / "schema.json") and (ask / "schema.json").exists()
    assert args[args.index("--sandbox") + 1] == "read-only" and list(repo.iterdir()) == []
    plain_args, _ = CODEX.question(ask, "gpt-6.1-sol", None, "Ask", [], {"type": "object"})
    assert plain_args[plain_args.index("--output-schema") + 1] == "schema.json"  # unchanged without a folder


def _missing_tool(ws: Path, kind: Any, args: Any) -> list[str]:
    raise cli.NotInstalled("Codex isn't installed yet")


def test_a_tool_that_isnt_there_fails_so_the_walk_moves_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "command", _missing_tool)
    call = PlanCall(model="gpt-6.1-sol", prompt="q", pictures=[], schema=None, thinking=None, timeout=5, wait=True,
                    workspace_path=tmp_path)
    with pytest.raises(ProviderFailed, match="isn't installed"):
        asyncio.run(PlanToolProvider(CODEX).answer(call))


def test_models_come_from_the_tools_own_files(tmp_path: Path) -> None:
    claude, _ = plan_models(tmp_path, "claude_code")
    assert [m.id for m in claude][:3] == ["haiku", "sonnet", "opus"]
    (cli.tool_home(tmp_path, CLAUDE) / ".claude.json").write_text(
        json.dumps({"additionalModelOptionsCache": [{"value": "claude-fable-5-1", "description": "Fable 5.1 · research"}]}),
        encoding="utf-8",
    )
    assert plan_models(tmp_path, "claude_code")[0][-1].name == "Fable 5.1"
    codex, problem = plan_models(tmp_path, "codex")
    assert codex == [] and problem
    (cli.tool_home(tmp_path, CODEX) / "models_cache.json").write_text(
        json.dumps({"models": [
            {"slug": "gpt-6.1-sol", "display_name": "GPT-6.1 Sol", "visibility": "list",
             "supported_reasoning_levels": [{"effort": "low"}, {"effort": "medium"}, {"effort": "high"}]},
            {"slug": "hidden", "visibility": "hide"},
        ]}),
        encoding="utf-8",
    )
    codex, problem = plan_models(tmp_path, "codex")
    assert [m.id for m in codex] == ["gpt-6.1-sol"] and problem is None
    provider = PlanToolProvider(CODEX)
    assert provider.effort(tmp_path, "gpt-6.1-sol", "off") == "low"  # no "none": its lowest
    assert provider.effort(tmp_path, "gpt-6.1-sol", "minimal") == "low"


def test_the_environment_keeps_nothing_of_the_cores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "secret")
    env = cli.environment(tmp_path, CODEX)
    assert "GOOGLE_API_KEY" not in env and env["CODEX_HOME"].endswith("codex") and env["DISABLE_AUTOUPDATER"] == "1"
