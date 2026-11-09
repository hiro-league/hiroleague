"""Phase 7a: the ask runner — answer shape, the fallback walk (failure, budget, local_only),
busy plan tools, and the counting behind the limits — against fake chat models."""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from hirocli.domain.preferences import AiPreferences, WorkspacePreferences
from hirocli.services.ai_ask import AskError, AskRequest, register_plan_tool
from hirocli.services.ai_ask import providers as providers_mod
from hirocli.services.ai_ask import runner as runner_mod
from hirocli.services.ai_ask.runner import AskRunner
from hirocli.services.ai_ask.usage import why_limited
from hirocli.services.ai_usage.store import ProfileUsage, UsageCall, profile_usage, read_rows, record_strict
from hirocli.services.plans.kinds import PLAN_KINDS, Answered
from hirocli.services.plans.provider import PlanToolProvider

GEMINI = "google:gemini-3.8-flash"
SCHEMA = {"type": "object", "properties": {"seen": {"type": "boolean"}}, "required": ["seen"]}


def _spent(path: Path, profile_id: str, cost: float | None, now: datetime | None = None) -> None:
    """One answered ask of ``profile_id`` in AI usage (Phase 7b: ``ai_calls``)."""
    record_strict(path, UsageCall(kind="question", source="home", use="ask", profile_id=profile_id, cost=cost or 0.0), now)


class FakeStore:
    def is_configured(self, provider_id: str) -> bool:
        return True

    def get(self, provider_id: str) -> None:
        return None


class FakeChat:
    """Just enough of a LangChain chat model: structured output with include_raw."""

    def __init__(self, reply: str = '{"seen": true}', *, parsed: Any = "auto", fail: Exception | None = None) -> None:
        self.reply = reply
        self.parsed = json.loads(reply) if parsed == "auto" else parsed
        self.fail = fail
        self.messages: list[Any] = []
        self.schema: Any = None

    def with_structured_output(self, schema: Any, include_raw: bool = False, **kwargs: Any) -> "_Structured":
        self.schema = schema
        return _Structured(self)

    async def ainvoke(self, messages: list[Any]) -> AIMessage:
        self.messages = messages
        if self.fail is not None:
            raise self.fail
        return AIMessage(
            content=self.reply,
            usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
        )


class _Structured:
    def __init__(self, chat: FakeChat) -> None:
        self.chat = chat

    async def ainvoke(self, messages: list[Any]) -> dict[str, Any]:
        raw = await self.chat.ainvoke(messages)
        return {"raw": raw, "parsed": self.chat.parsed, "parsing_error": None}


@pytest.fixture
def chats(monkeypatch: pytest.MonkeyPatch) -> dict[str, FakeChat]:
    built: dict[str, FakeChat] = {}

    def build(model_id: str, **kwargs: Any) -> FakeChat:
        return built[model_id]

    monkeypatch.setattr(providers_mod, "build_chat_model_from_tuning", build)
    monkeypatch.setattr(runner_mod, "_credential_store", lambda path: FakeStore())
    # Never the real plan tools (they may be installed on this machine) nor a real local server.
    monkeypatch.setattr(providers_mod, "_PLAN_TOOLS", {})
    monkeypatch.setattr(providers_mod, "_DEFAULTS_LOADED", True)
    monkeypatch.setattr(runner_mod.local_servers, "prepare", _no_prepare)
    return built


async def _no_prepare(*args: Any, **kwargs: Any) -> None:
    return None


def _prefs(profiles: dict[str, dict[str, Any]], uses: dict[str, str | None] | None = None) -> WorkspacePreferences:
    full = {pid: {"label": pid.title(), **p} for pid, p in profiles.items()}
    return WorkspacePreferences(ai=AiPreferences.model_validate({"profiles": full, "uses": uses or {}}))


def _ask(runner: AskRunner, prefs: WorkspacePreferences, **kwargs: Any) -> Any:
    request = AskRequest(**{"prompt": "Is someone at the door?", "schema": SCHEMA, **kwargs})
    return asyncio.run(runner.ask(request, prefs=prefs))


def test_an_ask_on_the_uses_profile_answers_json_with_tokens_cost_and_counts(tmp_path: Path, chats: dict[str, FakeChat]) -> None:
    chats[GEMINI] = FakeChat()
    prefs = _prefs({"camera": {"model": GEMINI, "instructions": "Answer from the picture only."}}, {"home:ask": "camera"})
    answer = _ask(AskRunner(tmp_path), prefs, use="home:ask", pictures=[b"\xff\xd8jpeg"], picture_labels=["Front door"])

    assert json.loads(answer.text) == {"seen": True}
    assert (answer.profile_id, answer.profile_name, answer.provider, answer.model) == ("camera", "Camera", "google", "gemini-3.8-flash")
    assert (answer.tokens_in, answer.tokens_out, answer.tokens, answer.plan) == (100, 20, 120, False)
    assert answer.cost == pytest.approx(100 * 0.75 / 1e6 + 20 * 3.75 / 1e6)
    assert answer.estimate is None and answer.notes == []
    assert [t["status"] for t in answer.tries] == ["ok"]
    assert set(answer.to_dict()) == {
        "text", "profile_id", "profile_name", "provider", "model", "plan", "ms", "tokens", "tokens_in",
        "tokens_out", "cost", "estimate", "notes", "tries",
    }
    # Label, picture (Gemini image part with its resolution), then the words with the instructions.
    parts = chats[GEMINI].messages[0].content
    assert parts[0] == {"type": "text", "text": "Front door"}
    assert parts[1]["type"] == "image" and parts[1]["media_resolution"] == "MEDIA_RESOLUTION_MEDIUM"
    assert parts[2]["text"].endswith("Answer from the picture only.")
    assert chats[GEMINI].schema["title"] == "answer"  # an untitled schema gets a name
    assert profile_usage(tmp_path, "camera").asks_today == 1


def test_a_failing_profile_passes_to_its_fallback_and_says_so(tmp_path: Path, chats: dict[str, FakeChat]) -> None:
    chats[GEMINI] = FakeChat(fail=RuntimeError("503 overloaded"))
    chats["lm_studio:qwen3-vl-8b"] = FakeChat('{"seen": false}')
    prefs = _prefs({"a": {"model": GEMINI, "fallback": "b"}, "b": {"model": "lm_studio:qwen3-vl-8b"}})
    answer = _ask(AskRunner(tmp_path), prefs, profile_id="a")

    assert answer.profile_id == "b" and json.loads(answer.text) == {"seen": False}
    assert answer.cost is None  # a home PC
    assert [t["status"] for t in answer.tries] == ["failed", "ok"]
    assert "503 overloaded" in answer.tries[0]["error"] and answer.notes[0].startswith("A:")
    assert profile_usage(tmp_path, "a").asks_today == 0


def test_over_budget_moves_on_and_every_profile_over_budget_is_budget(tmp_path: Path, chats: dict[str, FakeChat]) -> None:
    chats[GEMINI] = FakeChat()
    chats["ollama:gemma4:e4b"] = FakeChat()
    _spent(tmp_path, "a", 0.50)
    prefs = _prefs({"a": {"model": GEMINI, "max_cost_day": 0.25, "fallback": "b"}, "b": {"model": "ollama:gemma4:e4b"}})
    answer = _ask(AskRunner(tmp_path), prefs, profile_id="a")
    assert answer.profile_id == "b"
    assert [t["status"] for t in answer.tries] == ["skipped", "ok"] and "$0.25 for today" in answer.notes[0]

    _spent(tmp_path, "b", None)
    capped = _prefs(
        {"a": {"model": GEMINI, "max_cost_day": 0.25, "fallback": "b"}, "b": {"model": "ollama:gemma4:e4b", "max_per_hour": 2}}
    )
    with pytest.raises(AskError) as err:
        _ask(AskRunner(tmp_path), capped, profile_id="a")
    assert err.value.code == "budget" and len(err.value.tries) == 2


def test_local_only_skips_api_profiles(tmp_path: Path, chats: dict[str, FakeChat]) -> None:
    chats["ollama:gemma4:e4b"] = FakeChat()
    prefs = _prefs({"a": {"model": GEMINI, "fallback": "b"}, "b": {"model": "ollama:gemma4:e4b"}})
    answer = _ask(AskRunner(tmp_path), prefs, profile_id="a", local_only=True)
    assert answer.profile_id == "b" and answer.tries[0]["status"] == "skipped"

    with pytest.raises(AskError) as err:
        _ask(AskRunner(tmp_path), _prefs({"a": {"model": GEMINI}}), profile_id="a", local_only=True)
    assert err.value.code == "failed"


def test_no_profile_failed_and_invalid(tmp_path: Path, chats: dict[str, FakeChat]) -> None:
    chats[GEMINI] = FakeChat(fail=RuntimeError("bad key"))
    prefs = _prefs({"a": {"model": GEMINI}}, {"home:ask": None})
    with pytest.raises(AskError) as err:
        _ask(AskRunner(tmp_path), prefs, use="home:ask")
    assert err.value.code == "no_profile"
    with pytest.raises(AskError) as err:
        _ask(AskRunner(tmp_path), prefs, profile_id="a")
    assert err.value.code == "failed" and "bad key" in err.value.message
    with pytest.raises(AskError) as err:
        _ask(AskRunner(tmp_path), prefs, profile_id="a", prompt="  ")
    assert err.value.code == "invalid"


def test_a_fenced_json_reply_still_reads(tmp_path: Path, chats: dict[str, FakeChat]) -> None:
    chats[GEMINI] = FakeChat('```json\n{"seen": true}\n```', parsed=None)
    answer = _ask(AskRunner(tmp_path), _prefs({"a": {"model": GEMINI}}), profile_id="a")
    assert json.loads(answer.text) == {"seen": True}


def test_pictures_to_a_model_without_eyes_pass_to_the_fallback(tmp_path: Path, chats: dict[str, FakeChat]) -> None:
    chats["deepseek:deepseek-v4-pro"] = FakeChat()
    chats[GEMINI] = FakeChat()
    prefs = _prefs({"a": {"model": "deepseek:deepseek-v4-pro", "fallback": "b"}, "b": {"model": GEMINI}})
    answer = _ask(AskRunner(tmp_path), prefs, profile_id="a", pictures=[b"jpeg"])
    assert answer.profile_id == "b" and "can't read pictures" in answer.tries[0]["error"]


class SlowClaude(PlanToolProvider):
    """The real plan tool (its line, busy, estimate) with the program run replaced by a wait."""

    def __init__(self) -> None:
        super().__init__(PLAN_KINDS["claude_code"])
        self.started = threading.Event()
        self.release = threading.Event()

    def _answer_now(self, call: Any, effort: str | None) -> Answered:
        self.started.set()
        self.release.wait(10)
        return Answered('{"seen": true}', 1000, 50, 1050, "claude-sonnet-5-5")


def test_a_busy_plan_tool_answers_busy_to_an_app_and_plan_tools_not_set_up_fall_back(
    tmp_path: Path, chats: dict[str, FakeChat]
) -> None:
    chats[GEMINI] = FakeChat()
    # No plan tool registered: a failure, so the fallback answers.
    prefs = _prefs({"plan": {"model": "codex:gpt-6.1-sol", "fallback": "api"}, "api": {"model": GEMINI}})
    answer = _ask(AskRunner(tmp_path), prefs, profile_id="plan")
    assert answer.profile_id == "api" and "aren't set up yet" in answer.tries[0]["error"]

    tool = SlowClaude()
    register_plan_tool("claude_code", tool)
    plan_prefs = _prefs({"plan": {"model": "claude_code:sonnet", "fallback": "api"}, "api": {"model": GEMINI}})

    async def scenario() -> None:
        runner = AskRunner(tmp_path)
        own = AskRequest(prompt="q", profile_id="plan", schema=SCHEMA, use="home:study", wait=False)
        first = asyncio.create_task(runner.ask(own, prefs=plan_prefs))
        await asyncio.to_thread(tool.started.wait, 5)
        with pytest.raises(AskError) as err:
            await runner.ask(AskRequest(prompt="q", profile_id="plan", schema=SCHEMA, use="home:study", wait=False), prefs=plan_prefs)
        assert err.value.code == "busy"  # never passed to the paid fallback
        tool.release.set()
        done = await first
        assert done.plan is True and done.profile_id == "plan" and done.cost is None
        assert done.tokens == 1050 and done.estimate is not None and done.estimate > 0  # priced as Sonnet on a key

    asyncio.run(scenario())


def test_usage_counts_per_hour_and_day_and_limits_read_them(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    _spent(tmp_path, "p", 0.10, now=now)
    _spent(tmp_path, "p", 0.05, now=now)
    _spent(tmp_path, "p", None, now=now - timedelta(days=3))
    _spent(tmp_path, "other", 1.0, now=now)
    seen = profile_usage(tmp_path, "p", now=now)
    # Three days ago isn't today; another profile's asks don't count.
    assert (seen.asks_this_hour, seen.asks_today) == (2, 2)
    assert seen.cost_today == pytest.approx(0.15)

    from hirocli.domain.preferences import AiProfile

    api = AiProfile(label="A", model=GEMINI, max_cost_day=0.15)
    assert why_limited(api, "api", ProfileUsage(2, 0.15, 2)) is not None
    assert why_limited(api, "api", ProfileUsage(2, 0.14, 2)) is None
    local = AiProfile(label="L", model="ollama:gemma4:e4b", max_per_hour=2)
    note = why_limited(local, "local", ProfileUsage(2, 0.0, 2))
    assert note is not None and ("AM" in note or "PM" in note)
    assert why_limited(local, "api", ProfileUsage(2, 0.0, 2)) is None  # per hour counts for plan/local only


def test_try_it_on_a_draft_profile_answers_and_is_never_counted(tmp_path: Path, chats: dict[str, FakeChat]) -> None:
    from hirocli.domain.preferences import AiProfile
    from hirocli.services.ai_ask import DRAFT_PROFILE_ID

    chats[GEMINI] = FakeChat()
    draft = AiProfile(label="New camera profile", model=GEMINI)
    answer = asyncio.run(
        AskRunner(tmp_path).ask(AskRequest(prompt="q", schema=SCHEMA, who="admin"), prefs=_prefs({}), draft=draft)
    )
    assert (answer.profile_id, answer.profile_name) == (DRAFT_PROFILE_ID, "New camera profile")
    assert profile_usage(tmp_path, DRAFT_PROFILE_ID).asks_today == 0


# ── Phase 7b: what an ask leaves in AI usage ────────────────────────────────────────────────────


def test_an_answered_ask_is_counted_with_its_source_use_person_and_label(tmp_path: Path, chats: dict[str, FakeChat]) -> None:
    chats[GEMINI] = FakeChat()
    prefs = _prefs({"camera": {"model": GEMINI}}, {"home:ask": "camera"})
    _ask(AskRunner(tmp_path), prefs, use="home:ask", person_id="michel", label="Front door")

    (row,) = read_rows(tmp_path, datetime.now(UTC) - timedelta(hours=2), datetime.now(UTC) + timedelta(hours=1))
    assert (row["kind"], row["source"], row["use_id"], row["profile_id"], row["profile_name"]) == (
        "question", "home", "ask", "camera", "Camera",
    )
    assert (row["provider"], row["model"], row["billing"], row["person_id"], row["label"], row["result"]) == (
        "google", "gemini-3.8-flash", "api", "michel", "Front door", "ok",
    )
    assert (row["requests"], row["tokens_in"], row["tokens_out"]) == (1, 100, 20)
    assert row["cost"] == pytest.approx(100 * 0.75 / 1e6 + 20 * 3.75 / 1e6)


def test_a_fallback_answer_is_fell_back_and_an_unanswered_ask_is_failed(tmp_path: Path, chats: dict[str, FakeChat]) -> None:
    chats[GEMINI] = FakeChat(fail=RuntimeError("503 overloaded"))
    chats["lm_studio:qwen3-vl-8b"] = FakeChat('{"seen": false}')
    prefs = _prefs({"a": {"model": GEMINI, "fallback": "b"}, "b": {"model": "lm_studio:qwen3-vl-8b"}, "c": {"model": GEMINI}})
    runner = AskRunner(tmp_path)
    _ask(runner, prefs, profile_id="a")
    with pytest.raises(AskError):
        _ask(runner, prefs, profile_id="c")

    rows = read_rows(tmp_path, datetime.now(UTC) - timedelta(hours=2), datetime.now(UTC) + timedelta(hours=1))
    got = sorted((r["profile_id"], r["billing"], r["result"], r["source"], r["use_id"]) for r in rows)
    # Try it (no use) is the core's own: source hiro, use try_it.
    assert got == [("b", "local", "fell back", "hiro", "try_it"), ("c", "api", "failed", "hiro", "try_it")]
    # A failed ask never spends a profile's limits.
    assert profile_usage(tmp_path, "c").asks_today == 0
