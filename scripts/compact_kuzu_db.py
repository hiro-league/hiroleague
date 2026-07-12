#!/usr/bin/env python
"""Compact a bloated Graphiti Kuzu database via EXPORT/IMPORT rebuild.

Why this exists
---------------
Kuzu 0.11.3 has no VACUUM / compaction for variable-length columns. Every time
Graphiti re-summarizes an Entity or rewrites a fact during dedupe/merge, the old
value stays on disk as a dead row, and the four BM25 (FTS) indexes are rebuilt
over that bloated storage. A DB holding only tens of MB of live content can grow
to hundreds of MB. The only reclaim path Kuzu gives us is a full dump + reload.

What it does
------------
1. EXPORT DATABASE (parquet) from the *read-only* source -> temp dir (~1s, lossless).
2. Strip the auto-generated tokenizer MACRO statements from schema.cypher and
   empty index.cypher, so IMPORT only rebuilds tables + COPYs data.
   (IMPORT's own FTS replay collides on the shared ``default_english_stopwords``
   table -- see the Kuzu bug note below. We skip it and rebuild FTS the runtime way.)
3. IMPORT DATABASE into a fresh DB file.
4. Recreate the 4 FTS indexes via the normal runtime path (CALL CREATE_FTS_INDEX),
   which tolerates the shared stopwords table exactly as Graphiti does live.
5. CHECKPOINT, then verify: node counts + edge multisets must match the source
   exactly, and all 4 FTS indexes must be present.
6. Optionally swap the rebuilt file in (atomic-ish rename), keeping a timestamped
   backup of the original.

The source DB is NEVER mutated. With --swap the script renames files; without it,
you get ``<db>.rebuilt`` next to the original and swap by hand.

IMPORTANT: the server MUST be stopped first. Kuzu takes an exclusive file lock,
so ``hiro stop`` (and ``hirogate stop`` if relevant) before running this.

Usage
-----
  # dry rebuild next to the original, verify only, no swap:
  python scripts/compact_kuzu_db.py "<workspace>/db/graphiti_kuzu.db"

  # rebuild and swap in place (keeps graphiti_kuzu.db.bloated-YYYYmmdd-HHMMSS):
  python scripts/compact_kuzu_db.py "<path>/graphiti_kuzu.db" --swap

Run with the venv that has the matching kuzu pin:
  hiroserver/.venv/Scripts/python.exe scripts/compact_kuzu_db.py ...
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

try:
    import kuzu
except ModuleNotFoundError:
    sys.exit(
        "kuzu not importable. Run with the project venv, e.g.\n"
        "  hiroserver/.venv/Scripts/python.exe scripts/compact_kuzu_db.py <db>"
    )

# The 4 FTS indexes Graphiti maintains, as (table, index_name, columns) tuples.
# Discovered from CALL SHOW_INDEXES(); rebuilt via the runtime path so the shared
# ``default_english_stopwords`` table is reused rather than re-created (the bug below).
FTS_INDEXES = [
    ("Community", "community_name", ["name"]),
    ("Entity", "node_name_and_summary", ["name", "summary"]),
    ("Episodic", "episode_content", ["content", "source", "source_description"]),
    ("RelatesToNode_", "edge_name_and_fact", ["name", "fact"]),
]

NODE_TABLES = ["Episodic", "Entity", "RelatesToNode_", "Community", "Saga"]
# Edge multisets we verify exactly (table, from_label, to_label).
EDGE_TABLES = [
    ("MENTIONS", "Episodic", "Entity"),
    ("RELATES_TO", "Entity", "RelatesToNode_"),
    ("RELATES_TO", "RelatesToNode_", "Entity"),
    ("HAS_EPISODE", "Saga", "Episodic"),
    ("NEXT_EPISODE", "Episodic", "Episodic"),
    ("HAS_MEMBER", "Community", "Entity"),
    ("HAS_MEMBER", "Community", "Community"),
]


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.2f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.2f} GB"


def node_counts(conn: "kuzu.Connection") -> dict[str, int]:
    out = {}
    for t in NODE_TABLES:
        try:
            r = conn.execute(f"MATCH (n:`{t}`) RETURN count(n)")
            out[t] = r.get_next()[0]
        except Exception:
            out[t] = None  # table may legitimately not exist
    return out


def edge_count(conn: "kuzu.Connection", table: str, frm: str, to: str) -> int:
    # Structural MATCH count (the bare `count(r)` relationship counter is known to
    # over-report by one in some Kuzu builds, so we count the pattern instead).
    q = f"MATCH (:`{frm}`)-[r:`{table}`]->(:`{to}`) RETURN count(r)"
    r = conn.execute(q)
    return r.get_next()[0]


def edge_signature(conn: "kuzu.Connection") -> dict[tuple, int]:
    return {
        (table, frm, to): edge_count(conn, table, frm, to)
        for table, frm, to in EDGE_TABLES
    }


def show_index_names(conn: "kuzu.Connection") -> set[str]:
    names = set()
    try:
        r = conn.execute("CALL SHOW_INDEXES() RETURN *")
        while r.has_next():
            row = r.get_next()
            # row = [table, indexName, indexType, properties, ...]
            names.add((row[0], row[1]))
    except Exception as e:
        print(f"  (SHOW_INDEXES failed: {e})")
    return names


def export_source(src: Path, export_dir: Path) -> None:
    db = kuzu.Database(str(src), read_only=True)
    conn = kuzu.Connection(db)
    t = time.time()
    conn.execute(f"EXPORT DATABASE '{export_dir.as_posix()}' (format='parquet')")
    print(f"  exported in {time.time() - t:.1f}s -> {human(dir_size(export_dir))}")
    del conn, db


def dir_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def strip_fts_from_export(export_dir: Path) -> None:
    """Remove auto-generated tokenizer MACROs from schema.cypher and empty
    index.cypher, so IMPORT rebuilds only tables + data (no FTS replay)."""
    schema = export_dir / "schema.cypher"
    text = schema.read_text(encoding="utf-8")
    # CREATE MACRO `<n>_..._TOKENIZE` (query) AS string_split(... , ' ');  -- spans
    # several lines. The body holds a literal ';' inside a char-class string, so we
    # can't split on ';'; instead match lazily up to the terminating ')' + ';' pair
    # (`\);`), which only occurs at the true end of the statement.
    cleaned = re.sub(
        r"CREATE MACRO `[^`]*_TOKENIZE`.*?\);\s*",
        "",
        text,
        flags=re.DOTALL,
    )
    schema.write_text(cleaned, encoding="utf-8")
    removed = text.count("CREATE MACRO") - cleaned.count("CREATE MACRO")
    print(f"  stripped {removed} tokenizer macro(s) from schema.cypher")

    index = export_dir / "index.cypher"
    if index.exists():
        index.write_text("", encoding="utf-8")
        print("  emptied index.cypher (FTS rebuilt at runtime instead)")


def rebuild(export_dir: Path, dest: Path) -> None:
    if dest.exists():
        dest.unlink()
    db = kuzu.Database(str(dest))
    conn = kuzu.Connection(db)
    t = time.time()
    conn.execute(f"IMPORT DATABASE '{export_dir.as_posix()}'")
    print(f"  imported tables + data in {time.time() - t:.1f}s")

    t = time.time()
    for table, name, cols in FTS_INDEXES:
        col_list = ", ".join(f"'{c}'" for c in cols)
        conn.execute(
            f"CALL CREATE_FTS_INDEX('{table}', '{name}', [{col_list}], "
            f"stemmer := 'english', stopWords := 'default')"
        )
    conn.execute("CHECKPOINT")
    print(f"  rebuilt {len(FTS_INDEXES)} FTS indexes + checkpoint in {time.time() - t:.1f}s")
    del conn, db


def verify(src: Path, dest: Path) -> bool:
    sdb = kuzu.Database(str(src), read_only=True)
    sconn = kuzu.Connection(sdb)
    ddb = kuzu.Database(str(dest), read_only=True)
    dconn = kuzu.Connection(ddb)

    ok = True
    sc, dc = node_counts(sconn), node_counts(dconn)
    print("  node counts (source -> rebuilt):")
    for t in NODE_TABLES:
        match = sc.get(t) == dc.get(t)
        ok &= match
        flag = "OK" if match else "MISMATCH"
        print(f"    {t:<16} {sc.get(t)} -> {dc.get(t)}  [{flag}]")

    se, de = edge_signature(sconn), edge_signature(dconn)
    print("  edge multisets (source -> rebuilt):")
    for k in EDGE_TABLES:
        match = se.get(k) == de.get(k)
        ok &= match
        flag = "OK" if match else "MISMATCH"
        print(f"    {k[0]} {k[1]}->{k[2]:<16} {se.get(k)} -> {de.get(k)}  [{flag}]")

    idx = show_index_names(dconn)
    want = {(t, n) for t, n, _ in FTS_INDEXES}
    missing = want - idx
    if missing:
        ok = False
        print(f"  FTS indexes MISSING: {missing}")
    else:
        print(f"  FTS indexes OK: {len(want)}/4 present")

    del sconn, sdb, dconn, ddb
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("db", type=Path, help="path to graphiti_kuzu.db (server must be stopped)")
    ap.add_argument("--swap", action="store_true",
                    help="swap the rebuilt file in place, backing up the original as .bloated-<ts>")
    ap.add_argument("--keep-export", action="store_true", help="keep the temp parquet export dir")
    args = ap.parse_args()

    src: Path = args.db.resolve()
    if not src.exists():
        sys.exit(f"not found: {src}")
    for sidecar in (src.with_suffix(src.suffix + ".wal"), Path(str(src) + ".wal")):
        if sidecar.exists():
            sys.exit(f"WAL sidecar present ({sidecar.name}) -- is the server still running? Stop it first.")

    print(f"kuzu {kuzu.__version__}")
    print(f"source: {src}  ({human(src.stat().st_size)})")

    # Fail fast if the source is locked (server running).
    try:
        _ = kuzu.Connection(kuzu.Database(str(src), read_only=True))
        del _
    except Exception as e:
        sys.exit(f"cannot open source read-only (locked? server running?): {e}")

    rebuilt = src.with_name(src.name + ".rebuilt")
    # EXPORT DATABASE requires its target dir to NOT pre-exist, so point it at a
    # fresh subdir inside the temp scratch dir.
    scratch = Path(tempfile.mkdtemp(prefix="kuzu_export_"))
    export_dir = scratch / "dump"
    try:
        print("\n[1/4] EXPORT")
        export_source(src, export_dir)
        print("\n[2/4] strip FTS replay from export")
        strip_fts_from_export(export_dir)
        print("\n[3/4] IMPORT + rebuild FTS")
        rebuild(export_dir, rebuilt)
        print("\n[4/4] VERIFY")
        if not verify(src, rebuilt):
            print("\nVERIFICATION FAILED -- leaving rebuilt file in place, NOT swapping.")
            print(f"  rebuilt: {rebuilt}")
            return 2
    finally:
        if args.keep_export:
            print(f"\nexport kept at: {export_dir}")
        else:
            shutil.rmtree(scratch, ignore_errors=True)

    before, after = src.stat().st_size, rebuilt.stat().st_size
    ratio = before / after if after else float("inf")
    print(f"\nSIZE  {human(before)} -> {human(after)}  ({ratio:.2f}x smaller, "
          f"-{100 * (before - after) / before:.0f}%)")

    if args.swap:
        ts = time.strftime("%Y%m%d-%H%M%S")
        backup = src.with_name(src.name + f".bloated-{ts}")
        src.rename(backup)
        rebuilt.rename(src)
        print(f"\nSWAPPED. original kept at: {backup.name}")
        print(f"  live DB is now the compacted file: {src.name}")
    else:
        print(f"\nrebuilt file: {rebuilt}")
        print("  not swapped (pass --swap to swap in place). To swap by hand:")
        print(f"    stop server; rename '{src.name}' aside; rename '{rebuilt.name}' -> '{src.name}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
