"""Clear leaked per-turn fan-out scratch (transcripts / visions / errors) from the
agent-graph checkpoint.

Background
----------
Before the ``append_or_reset`` reducer fix, ``transcripts`` / ``visions`` / ``errors`` used
``operator.add`` and were never reset. With the durable per-``thread_id`` SQLite checkpointer,
STT transcripts from earlier voice-note turns accumulated and leaked into every later turn's
``user_text`` (via ``gather_node``) — showing up as "strange text" the user never typed.

The code fix self-heals this on the *next* message in each thread (``ingest_node`` now emits
``None`` → ``append_or_reset`` clears the channel). This script is an OPTIONAL convenience to
clear the stuck scratch immediately, without waiting for another message — and a diagnostic to
confirm what is stuck.

It is LOSSLESS: it clears only ``transcripts`` / ``visions`` / ``errors`` by driving the graph's
own ``update_state`` with ``None`` (the reducer maps ``None`` → ``[]``). Conversation history
(``messages``) and every other channel are preserved.

Usage
-----
Stop the server first (the checkpointer opens ``db/workspace.db``; concurrent writers are unsafe)::

    hiro stop

Diagnose (read-only) — list threads and any stuck scratch::

    python scripts/clear_graph_scratch.py --workspace "<workspace_path>"

Clear the stuck scratch for one thread (lossless)::

    python scripts/clear_graph_scratch.py --workspace "<workspace_path>" --clear --thread 1

Clear for all threads::

    python scripts/clear_graph_scratch.py --workspace "<workspace_path>" --clear --all
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from hirocli.runtime.agent_graph.state import GraphState

# Channels this script resets — the per-turn fan-out scratch that used to leak.
_SCRATCH_CHANNELS = ("transcripts", "visions", "errors")


def _workspace_db(workspace_path: Path) -> Path:
    # Mirrors domain.db.db_path — all DBs live under <workspace>/db/ (consolidated layout).
    db = workspace_path / "db" / "workspace.db"
    if not db.exists():
        raise SystemExit(f"workspace.db not found at {db}")
    return db


def _thread_ids(db: Path) -> list[str]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute("select distinct thread_id from checkpoints").fetchall()
    finally:
        con.close()
    return [str(r[0]) for r in rows]


def _build_probe_graph(saver: SqliteSaver):
    """A no-op graph over the real GraphState so update_state uses the real reducers/channels."""
    b = StateGraph(GraphState)
    b.add_node("noop", lambda state: {})
    b.add_edge(START, "noop")
    b.add_edge("noop", END)
    return b.compile(checkpointer=saver)


def _scratch_summary(values: dict) -> str:
    parts = []
    for ch in _SCRATCH_CHANNELS:
        items = values.get(ch) or []
        if items:
            if ch == "transcripts":
                sample = "; ".join(str(i.get("transcript", ""))[:40] for i in items[:3])
            elif ch == "visions":
                sample = "; ".join(str(i.get("description", ""))[:40] for i in items[:3])
            else:
                sample = "; ".join(str(i.get("error", ""))[:40] for i in items[:3])
            parts.append(f"{ch}={len(items)} [{sample}]")
    return " · ".join(parts) if parts else "clean (no stuck scratch)"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workspace", required=True, type=Path, help="Workspace path (contains db/).")
    ap.add_argument("--clear", action="store_true", help="Clear stuck scratch (default: diagnose only).")
    ap.add_argument("--thread", help="Thread id to clear (with --clear).")
    ap.add_argument("--all", action="store_true", help="Clear all threads (with --clear).")
    args = ap.parse_args()

    db = _workspace_db(args.workspace)
    threads = _thread_ids(db)
    if not threads:
        print("No checkpointed threads found — nothing to do.")
        return

    if args.clear:
        if args.all:
            targets = threads
        elif args.thread:
            targets = [args.thread]
        else:
            raise SystemExit("--clear requires --thread <id> or --all")
    else:
        targets = threads

    # SqliteSaver needs a real connection; open read/write only when clearing.
    con = sqlite3.connect(str(db))
    try:
        saver = SqliteSaver(con)
        graph = _build_probe_graph(saver)
        for tid in targets:
            cfg = {"configurable": {"thread_id": tid}}
            snap = graph.get_state(cfg)
            before = _scratch_summary(snap.values)
            if not args.clear:
                print(f"thread {tid}: {before}")
                continue
            # update_state with None drives append_or_reset(current, None) -> [] for each
            # scratch channel. messages and all other channels are untouched (lossless).
            graph.update_state(cfg, {ch: None for ch in _SCRATCH_CHANNELS})
            after = _scratch_summary(graph.get_state(cfg).values)
            print(f"thread {tid}: cleared\n    before: {before}\n    after:  {after}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
