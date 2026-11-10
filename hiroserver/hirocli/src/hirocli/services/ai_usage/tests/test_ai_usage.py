"""Phase 7b: AI usage — the hourly store, Hiro's calls from the graph ledger, and the page's rows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hirocli.domain.preferences import AiPreferences, WorkspacePreferences
from hirocli.services.ai_usage.from_ledger import usage_call_from_ledger_row
from hirocli.services.ai_usage.store import UsageCall, profile_usage, read_rows, record, record_strict
from hirocli.services.ai_usage.view import page_rows

NOW = datetime(2026, 11, 9, 14, 30, tzinfo=UTC)


def _call(**kw: object) -> UsageCall:
    return UsageCall(**{"kind": "question", "source": "home", "use": "ask", "profile_id": "cam", **kw})  # type: ignore[arg-type]


def test_calls_alike_in_one_hour_add_up_into_one_row(tmp_path: Path) -> None:
    record_strict(tmp_path, _call(tokens_in=10, cost=0.01), NOW)
    record_strict(tmp_path, _call(tokens_in=5, cost=0.02), NOW + timedelta(minutes=20))
    record_strict(tmp_path, _call(label="Front door"), NOW)  # another label: another row
    record_strict(tmp_path, _call(), NOW + timedelta(hours=1))  # another hour: another row

    rows = read_rows(tmp_path, NOW - timedelta(hours=1), NOW + timedelta(hours=3))
    assert len(rows) == 3
    first = next(r for r in rows if r["hour"] == "2026-11-09T14:00:00Z" and r["label"] == "")
    assert (first["requests"], first["tokens_in"]) == (2, 15)
    assert first["cost"] == pytest.approx(0.03)


def test_a_range_takes_the_hours_it_overlaps(tmp_path: Path) -> None:
    record_strict(tmp_path, _call(), NOW)
    assert read_rows(tmp_path, NOW.replace(minute=0) + timedelta(hours=1), NOW + timedelta(hours=5)) == []
    # An end inside the hour still takes it (a half-hour time zone's midnight).
    assert len(read_rows(tmp_path, NOW - timedelta(hours=3), NOW.replace(minute=10))) == 1


def test_a_bad_call_is_refused_strictly_and_only_logged_otherwise(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        record_strict(tmp_path, _call(kind="poem"), NOW)
    record(tmp_path, _call(result="maybe"), NOW)  # logged, not raised
    assert read_rows(tmp_path, NOW - timedelta(days=1), NOW + timedelta(days=1)) == []


def test_limits_read_todays_answered_questions_of_the_profile_only(tmp_path: Path) -> None:
    record_strict(tmp_path, _call(cost=0.10), NOW)
    record_strict(tmp_path, _call(result="fell back", cost=0.05), NOW)
    record_strict(tmp_path, _call(result="failed"), NOW)
    record_strict(tmp_path, _call(kind="image", cost=1.0), NOW)  # an image profile with the same id
    record_strict(tmp_path, _call(cost=5.0), NOW - timedelta(days=2))
    seen = profile_usage(tmp_path, "cam", now=NOW)
    assert (seen.asks_today, seen.asks_this_hour) == (2, 2)
    assert seen.cost_today == pytest.approx(0.15)


def _ledger_row(**kw: object) -> dict[str, object]:
    return {"row_kind": "node", "run_id": "chat-m1", "node": "call_model", "status": "ok", "provider": "google",
            "model": "gemini-3.8-flash", "input_tokens": "1200", "output_tokens": "80", "elapsed_ms": "900",
            "cost_usd": "0.0012", **kw}


@pytest.mark.parametrize(
    ("node", "run_id", "kind", "use"),
    [
        ("call_model", "chat-m1", "question", "chat"),
        ("memory_recall", "chat-m1", "question", "memory"),
        ("graphiti_ingest/episode", "chat-m1", "question", "graph"),
        ("knowledge/embed_query", "knowledge-k1", "embedding", "knowledge"),
        ("knowledge/rerank", "chat-m1", "rerank", "knowledge"),
        ("knowledge/call_model", "chat-m1", "question", "knowledge"),
        ("tts", "chat-m1", "speech", "voice_replies"),
        ("stt", "chat-m1", "transcription", "voice_notes"),
        ("eval_judge", "memory_eval-1", "question", "eval"),
        ("call_model", "knowledge-k1", "question", "knowledge"),
    ],
)
def test_a_ledger_node_row_is_counted_under_hiro_with_its_kind_and_use(node: str, run_id: str, kind: str, use: str) -> None:
    call = usage_call_from_ledger_row(_ledger_row(node=node, run_id=run_id))
    assert call is not None
    assert (call.source, call.kind, call.use, call.billing, call.result) == ("hiro", kind, use, "api", "ok")
    assert (call.tokens_in, call.tokens_out, call.ms) == (1200, 80, 900)
    assert call.cost == pytest.approx(0.0012)


def test_run_rows_children_decisions_count_nothing_and_errors_are_failed() -> None:
    assert usage_call_from_ledger_row(_ledger_row(row_kind="run")) is None
    assert usage_call_from_ledger_row(_ledger_row(_no_fold=True)) is None
    assert usage_call_from_ledger_row(_ledger_row(model="")) is None
    failed = usage_call_from_ledger_row(_ledger_row(status="error", cost_usd=""))
    assert failed is not None and (failed.result, failed.cost) == ("failed", 0.0)
    local = usage_call_from_ledger_row(_ledger_row(provider="lm_studio", model="qwen3-8b"))
    assert local is not None and local.billing == "local"


def test_page_rows_read_names_and_keep_a_deleted_profiles_name(tmp_path: Path) -> None:
    record_strict(tmp_path, _call(profile_name="Camera checks", label="Front door"), NOW)
    record_strict(tmp_path, _call(profile_id="gone", profile_name="Old camera"), NOW)
    record_strict(tmp_path, UsageCall(kind="embedding", source="hiro", use="knowledge", provider="google", model="e1"), NOW)
    prefs = WorkspacePreferences(
        ai=AiPreferences.model_validate({"profiles": {"cam": {"label": "Cameras (renamed)", "model": "google:gemini-3.8-flash"}}})
    )
    rows = page_rows(tmp_path, prefs, NOW - timedelta(hours=1), NOW + timedelta(hours=1))
    by_profile = {r["profile"]: r for r in rows}
    assert set(by_profile) == {"Cameras (renamed)", "Old camera", "No profile"}
    cam = by_profile["Cameras (renamed)"]
    assert (cam["kind"], cam["source"], cam["use"], cam["label"], cam["person"]) == ("Question", "Home", "ask", "Front door", None)
    assert cam["hour"] == int(datetime(2026, 11, 9, 14, tzinfo=UTC).timestamp() * 1000)
    hiro = by_profile["No profile"]
    assert (hiro["kind"], hiro["source"], hiro["use"]) == ("Embedding", "Hiro", "Knowledge")


# ── The one-time HomeHiro import ────────────────────────────────────────────────────────────────


def _homehiro_db(path: Path) -> Path:
    import sqlite3

    db = path / "homehiro.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE llmtotal (id INTEGER PRIMARY KEY, hour DATETIME, kind TEXT, task TEXT, camera TEXT, profile TEXT, "
            "provider TEXT, model TEXT, billing TEXT, result TEXT, requests INT, tokens_in INT, tokens_out INT, ms INT, "
            "cost REAL, estimate REAL, unpriced INT)"
        )
        conn.execute("CREATE TABLE llmserver (id TEXT, kind TEXT)")
        conn.execute("INSERT INTO llmserver VALUES ('pc', 'ollama')")
        rows = [
            ("2026-11-01 08:00:00.000000", "Ask a camera", "Door", "Front door", "Camera checks", "gemini", "gemini-3.8-flash", "api", "ok", 3, 300, 30, 900, 0.003, 0.0),
            ("2026-11-01 08:00:00.000000", "Write text", "Came home", None, "Writer", "claude_cli", "claude-sonnet-5-5", "plan", "ok", 1, 50, 10, 4000, 0.0, 0.02),
            ("2026-11-02 09:00:00.000000", "StudyHiro", "Math review", None, "Local", "local:pc", "gemma4", "local", "failed", 1, 0, 0, 100, 0.0, 0.0),
            ("2026-11-09 15:00:00.000000", "Ask a camera", "Door", "Front door", "Camera checks", "google", "gemini-3.8-flash", "api", "ok", 2, 200, 20, 600, 0.002, 0.0),
        ]
        conn.executemany(
            "INSERT INTO llmtotal (hour, kind, task, camera, profile, provider, model, billing, result, requests, tokens_in, "
            "tokens_out, ms, cost, estimate, unpriced) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
            rows,
        )
    return db


def test_homehiro_history_is_added_once_before_the_cores_own_home_rows(tmp_path: Path) -> None:
    from hirocli.services.ai_usage.import_homehiro import import_usage

    db = _homehiro_db(tmp_path)
    ws = tmp_path / "ws"
    # The core has counted Home itself since Nov 9, 2 PM UTC: HomeHiro's 3 PM row is already in it.
    record_strict(ws, _call(), NOW)
    prefs = WorkspacePreferences(
        ai=AiPreferences.model_validate({"profiles": {"hh-1": {"label": "Camera checks", "model": "google:gemini-3.8-flash"}}})
    )

    dry = import_usage(ws, prefs, db, dry_run=True)
    assert (dry.rows, dry.imported, dry.written) == (4, 3, False)
    done = import_usage(ws, prefs, db, dry_run=False)
    assert (done.imported, done.requests, done.written, done.cutoff) == (3, 5, True, "2026-11-09T14:00:00Z")
    assert done.cost == pytest.approx(0.003)
    # Running it again adds nothing: the core's first Home hour is now HomeHiro's first.
    assert import_usage(ws, prefs, db, dry_run=False).imported == 0

    rows = {r["use_id"]: r for r in read_rows(ws, datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 11, 9, tzinfo=UTC))}
    assert set(rows) == {"ask", "write", "study"}
    assert (rows["ask"]["profile_id"], rows["ask"]["provider"], rows["ask"]["label"]) == ("hh-1", "google", "Front door")
    assert (rows["write"]["provider"], rows["write"]["billing"], rows["write"]["label"]) == ("claude_code", "plan", "Came home")
    assert rows["write"]["estimate"] == pytest.approx(0.02)
    assert (rows["study"]["provider"], rows["study"]["result"], rows["study"]["profile_name"]) == ("ollama", "failed", "Local")


def test_imported_asks_of_today_count_toward_the_profiles_limits(tmp_path: Path) -> None:
    """B5: 7a's counts are dropped with its table; the import brings today's Home asks back under their profiles."""
    import sqlite3

    from hirocli.services.ai_usage.import_homehiro import import_usage

    db = _homehiro_db(tmp_path)
    today = NOW.replace(minute=0).strftime("%Y-%m-%d %H:%M:%S.000000")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO llmtotal (hour, kind, task, camera, profile, provider, model, billing, result, requests, tokens_in, "
            "tokens_out, ms, cost, estimate, unpriced) VALUES (?, 'Ask a camera', 'Door', 'Front door', 'Camera checks', "
            "'google', 'gemini-3.8-flash', 'api', 'ok', 4, 400, 40, 1200, 0.25, 0, 1)",
            (today,),
        )
    ws = tmp_path / "ws"
    prefs = WorkspacePreferences(
        ai=AiPreferences.model_validate({"profiles": {"hh-1": {"label": "Camera checks", "model": "google:gemini-3.8-flash"}}})
    )
    import_usage(ws, prefs, db, dry_run=False)
    seen = profile_usage(ws, "hh-1", now=NOW)
    # This hour: the 4 imported asks; today also holds the fixture's 3 PM row (its local day permitting).
    assert seen.asks_this_hour == 4 and seen.cost_today >= 0.25
    (row,) = [r for r in read_rows(ws, NOW - timedelta(hours=1), NOW + timedelta(hours=1)) if r["hour"] == "2026-11-09T14:00:00Z"]
    assert row["unpriced"] == 1  # B2: HomeHiro's unpriced count comes along


def test_graph_llm_calls_are_counted_without_the_ledger(tmp_path: Path) -> None:
    """B1: with observability off (or outside an ingest episode) the graph's calls are counted directly."""
    from hirocli.services.ai_usage.from_ledger import count_graph_llm_usage
    from hirocli.services.knowledge.graph.graphiti_adapters import GraphitiLLMUsage

    usage = GraphitiLLMUsage(
        model_id="google:gemini-3.8-flash", model_size="medium", input_tokens=1000, output_tokens=100,
        operation="extract_nodes", elapsed_ms=800.0,
    )
    count_graph_llm_usage(tmp_path, usage)  # no running loop: written here
    (row,) = read_rows(tmp_path, datetime.now(UTC) - timedelta(hours=2), datetime.now(UTC) + timedelta(hours=1))
    assert (row["source"], row["use_id"], row["kind"], row["provider"], row["model"]) == (
        "hiro", "graph", "question", "google", "gemini-3.8-flash",
    )
    assert (row["tokens_in"], row["tokens_out"], row["ms"]) == (1000, 100, 800)
    assert row["cost"] > 0  # priced from the catalog


def test_a_chat_turns_calls_carry_the_senders_person() -> None:
    """B6: the agent manager sets the turn's person (a WhatsApp number in the family list)."""
    from hirocli.services.ai_usage.from_ledger import usage_person

    token = usage_person.set("mia")
    try:
        call = usage_call_from_ledger_row(_ledger_row())
    finally:
        usage_person.reset(token)
    assert call is not None and call.person_id == "mia"
    assert usage_call_from_ledger_row(_ledger_row()).person_id == ""  # type: ignore[union-attr]


def test_a_chat_turns_own_calls_carry_its_ai_profile_only() -> None:
    """Phase 7b step 5: the chat turn's AI profile is filed on the chat's own rows; other jobs'
    rows inside the turn (memory, knowledge, speech…) are left without a profile."""
    from hirocli.services.ai_usage.from_ledger import usage_profile

    token = usage_profile.set(("hiro-chat", "Hiro's chat"))
    try:
        chat = usage_call_from_ledger_row(_ledger_row())
        memory = usage_call_from_ledger_row(_ledger_row(node="memory_recall"))
        speech = usage_call_from_ledger_row(_ledger_row(node="tts", model="gemini-3.8-flash-tts", provider="google"))
    finally:
        usage_profile.reset(token)
    assert chat is not None and (chat.use, chat.profile_id, chat.profile_name) == ("chat", "hiro-chat", "Hiro's chat")
    assert memory is not None and memory.profile_id == ""
    assert speech is not None and (speech.kind, speech.profile_id) == ("speech", "")
    assert usage_call_from_ledger_row(_ledger_row()).profile_id == ""  # type: ignore[union-attr]


def test_ledger_models_lose_the_provider_prefix_and_an_unpriced_api_call_is_marked() -> None:
    call = usage_call_from_ledger_row(_ledger_row(model="google:gemini-3.8-flash", cost_usd=""))
    assert call is not None and (call.provider, call.model, call.unpriced) == ("google", "gemini-3.8-flash", 1)
