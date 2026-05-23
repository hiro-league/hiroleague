"""SQLite catalog store for knowledge document and job metadata."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from hiro_commons.log import Logger

from hirocli.services.knowledge.converters import document_from_row, utc_now_iso
from hirocli.services.knowledge.models import KnowledgeDocumentRow, KnowledgeListDocumentsResult
from hirocli.services.knowledge.runtime_owner import is_owner_token_alive

log = Logger.get("SVC.KNOWLEDGE.CATALOG")


class CatalogStore:
    """Source of truth for knowledge metadata in ``knowledge.db``."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    def ensure_schema(self) -> None:
        with self.connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_documents (
                  id TEXT PRIMARY KEY,
                  source_uri TEXT NOT NULL UNIQUE,
                  source_type TEXT NOT NULL,
                  mime TEXT NOT NULL,
                  ext TEXT NOT NULL,
                  owner_kind TEXT NOT NULL,
                  owner_id TEXT NOT NULL,
                  category_id INTEGER NULL,
                  subcategory_id INTEGER NULL,
                  title TEXT NOT NULL,
                  -- content_hash/chunk_count are NULL during parsing/embedding;
                  -- only populated when status flips to 'ready'.
                  content_hash TEXT NULL,
                  size_bytes INTEGER NOT NULL,
                  chunk_count INTEGER NULL,
                  status TEXT NOT NULL,
                  error TEXT NULL,
                  ingested_at TEXT NULL,
                  updated_at TEXT NOT NULL,
                  CHECK (subcategory_id IS NULL OR category_id IS NOT NULL)
                );
                CREATE TABLE IF NOT EXISTS knowledge_categories (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL,
                  parent_id INTEGER NULL REFERENCES knowledge_categories(id) ON DELETE CASCADE,
                  UNIQUE(parent_id, name)
                );
                CREATE TABLE IF NOT EXISTS knowledge_tags (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS knowledge_document_tags (
                  document_id TEXT NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
                  tag_id INTEGER NOT NULL REFERENCES knowledge_tags(id) ON DELETE CASCADE,
                  PRIMARY KEY (document_id, tag_id)
                );
                CREATE TABLE IF NOT EXISTS knowledge_ingestion_jobs (
                  id TEXT PRIMARY KEY,
                  created_at TEXT NOT NULL,
                  finished_at TEXT NULL,
                  status TEXT NOT NULL,
                  totals_json TEXT NOT NULL,
                  errors_json TEXT NOT NULL,
                  params_json TEXT NOT NULL,
                  owner_token TEXT NULL
                );
                """
            )
            columns = {
                str(row[1])
                for row in con.execute("PRAGMA table_info(knowledge_ingestion_jobs)").fetchall()
            }
            if "owner_token" not in columns:
                con.execute("ALTER TABLE knowledge_ingestion_jobs ADD COLUMN owner_token TEXT NULL")

    def recover_abandoned_work(
        self,
        *,
        live_tokens: set[str] | None = None,
    ) -> None:
        """Mark abandoned running jobs failed; skip jobs owned by live processes."""
        active_tokens = set(live_tokens or ())
        now = utc_now_iso()
        abandoned_paths: set[str] = set()
        recovered_jobs = 0
        with self.connect() as con:
            running = con.execute(
                """
                SELECT id, totals_json, errors_json, params_json, owner_token
                FROM knowledge_ingestion_jobs
                WHERE status = 'running'
                """
            ).fetchall()
            for row in running:
                owner_token = row["owner_token"]
                if owner_token and str(owner_token) in active_tokens:
                    continue
                if is_owner_token_alive(owner_token):
                    continue
                errors = json.loads(row["errors_json"] or "{}")
                errors["job"] = "server restarted"
                con.execute(
                    """
                    UPDATE knowledge_ingestion_jobs
                    SET status = 'failed', finished_at = ?, errors_json = ?
                    WHERE id = ?
                    """,
                    (now, json.dumps(errors), row["id"]),
                )
                recovered_jobs += 1
                params = json.loads(row["params_json"] or "{}")
                for raw_path in params.get("paths") or []:
                    if not str(raw_path).strip():
                        continue
                    abandoned_paths.add(str(Path(str(raw_path)).expanduser().resolve()))
            if abandoned_paths:
                placeholders = ",".join("?" for _ in abandoned_paths)
                con.execute(
                    f"""
                    UPDATE knowledge_documents
                    SET status = 'failed', error = COALESCE(error, 'server restarted'), updated_at = ?
                    WHERE status != 'ready' AND source_uri IN ({placeholders})
                    """,
                    (now, *sorted(abandoned_paths)),
                )
        if recovered_jobs:
            log.warning(
                "knowledge crash recovery marked jobs failed",
                jobs=recovered_jobs,
                documents=len(abandoned_paths),
            )

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        return con

    def known_source_uris(self) -> set[str]:
        with self.connect() as con:
            rows = con.execute("SELECT source_uri FROM knowledge_documents WHERE status = 'ready'").fetchall()
            return {str(row["source_uri"]) for row in rows}

    def insert_job(
        self,
        job_id: str,
        status: str,
        totals: dict[str, int],
        errors: dict[str, str],
        params: dict[str, Any],
        *,
        owner_token: str | None = None,
    ) -> None:
        now = utc_now_iso()
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO knowledge_ingestion_jobs
                (id, created_at, finished_at, status, totals_json, errors_json, params_json, owner_token)
                VALUES (?, ?, NULL, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    now,
                    status,
                    json.dumps(totals),
                    json.dumps(errors),
                    json.dumps(params),
                    owner_token,
                ),
            )

    def update_job(self, job_id: str, status: str, totals: dict[str, int], errors: dict[str, str]) -> None:
        with self.connect() as con:
            con.execute(
                "UPDATE knowledge_ingestion_jobs SET status = ?, totals_json = ?, errors_json = ? WHERE id = ?",
                (status, json.dumps(totals), json.dumps(errors), job_id),
            )

    def finish_job(self, job_id: str, status: str, totals: dict[str, int], errors: dict[str, str]) -> None:
        with self.connect() as con:
            con.execute(
                """
                UPDATE knowledge_ingestion_jobs
                SET status = ?, totals_json = ?, errors_json = ?, finished_at = ?
                WHERE id = ?
                """,
                (status, json.dumps(totals), json.dumps(errors), utc_now_iso(), job_id),
            )

    def job_row(self, job_id: str) -> sqlite3.Row | None:
        with self.connect() as con:
            return con.execute("SELECT * FROM knowledge_ingestion_jobs WHERE id = ?", (job_id,)).fetchone()

    def list_jobs(self, limit: int) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute(
                """
                SELECT * FROM knowledge_ingestion_jobs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 100)),),
            ).fetchall()

    def document_row_by_source(self, source_uri: str) -> sqlite3.Row | None:
        with self.connect() as con:
            return con.execute("SELECT * FROM knowledge_documents WHERE source_uri = ?", (source_uri,)).fetchone()

    def document_row_by_id(self, document_id: str) -> sqlite3.Row | None:
        with self.connect() as con:
            return con.execute("SELECT * FROM knowledge_documents WHERE id = ?", (document_id,)).fetchone()

    def mark_document_progress(
        self,
        document_id: str,
        path: Path,
        status: str,
        size_bytes: int,
        params: dict[str, Any],
    ) -> None:
        # Reserves a row (or refreshes an existing one) so 'parsing'/'embedding' show up
        # in Browse and so crash recovery can flip live work to 'failed'. content_hash
        # and chunk_count remain NULL until the row flips to 'ready' in upsert_document_row.
        now = utc_now_iso()
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO knowledge_documents (
                  id, source_uri, source_type, mime, ext, owner_kind, owner_id,
                  category_id, subcategory_id, title, content_hash, size_bytes,
                  chunk_count, status, error, ingested_at, updated_at
                )
                VALUES (?, ?, 'file', 'application/octet-stream', ?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?, NULL, NULL, ?)
                ON CONFLICT(source_uri) DO UPDATE SET
                  id = excluded.id,
                  ext = excluded.ext,
                  owner_kind = excluded.owner_kind,
                  owner_id = excluded.owner_id,
                  category_id = excluded.category_id,
                  subcategory_id = excluded.subcategory_id,
                  size_bytes = excluded.size_bytes,
                  status = excluded.status,
                  error = NULL,
                  updated_at = excluded.updated_at
                """,
                (
                    document_id,
                    str(path),
                    path.suffix.lower(),
                    params.get("owner_kind") or "system",
                    params.get("owner_id") or "0",
                    params.get("category_id"),
                    params.get("subcategory_id"),
                    path.stem,
                    size_bytes,
                    status,
                    now,
                ),
            )

    def update_document_status(self, document_id: str, status: str, error: str | None) -> None:
        now = utc_now_iso()
        with self.connect() as con:
            con.execute(
                "UPDATE knowledge_documents SET status = ?, error = ?, updated_at = ? WHERE id = ?",
                (status, error, now, document_id),
            )

    def touch_document_ingested(self, document_id: str, now: str) -> None:
        """Record a successful reingest when file content is unchanged (no re-embed)."""
        with self.connect() as con:
            con.execute(
                """
                UPDATE knowledge_documents
                SET ingested_at = ?, updated_at = ?
                WHERE id = ? AND status = 'ready'
                """,
                (now, now, document_id),
            )

    def upsert_document_row(
        self,
        document_id: str,
        path: Path,
        title: str,
        mime: str,
        content_hash: str,
        size_bytes: int,
        chunk_count: int,
        params: dict[str, Any],
        now: str,
        tags: Sequence[str],
    ) -> None:
        # Successful indexing: stamp ingested_at and bump updated_at together.
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO knowledge_documents (
                  id, source_uri, source_type, mime, ext, owner_kind, owner_id,
                  category_id, subcategory_id, title, content_hash, size_bytes,
                  chunk_count, status, error, ingested_at, updated_at
                )
                VALUES (?, ?, 'file', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', NULL, ?, ?)
                ON CONFLICT(source_uri) DO UPDATE SET
                  id = excluded.id,
                  mime = excluded.mime,
                  ext = excluded.ext,
                  owner_kind = excluded.owner_kind,
                  owner_id = excluded.owner_id,
                  category_id = excluded.category_id,
                  subcategory_id = excluded.subcategory_id,
                  title = excluded.title,
                  content_hash = excluded.content_hash,
                  size_bytes = excluded.size_bytes,
                  chunk_count = excluded.chunk_count,
                  status = 'ready',
                  error = NULL,
                  ingested_at = excluded.ingested_at,
                  updated_at = excluded.updated_at
                """,
                (
                    document_id,
                    str(path),
                    mime,
                    path.suffix.lower(),
                    params.get("owner_kind") or "system",
                    params.get("owner_id") or "0",
                    params.get("category_id"),
                    params.get("subcategory_id"),
                    title,
                    content_hash,
                    size_bytes,
                    chunk_count,
                    now,
                    now,
                ),
            )
            con.execute("DELETE FROM knowledge_document_tags WHERE document_id = ?", (document_id,))
            for tag in tags:
                tag_id = con.execute("SELECT id FROM knowledge_tags WHERE name = ?", (tag,)).fetchone()["id"]
                con.execute(
                    "INSERT OR IGNORE INTO knowledge_document_tags (document_id, tag_id) VALUES (?, ?)",
                    (document_id, tag_id),
                )

    def ensure_tags(self, tags: Sequence[str]) -> list[str]:
        clean = sorted({str(tag).strip() for tag in tags if str(tag).strip()})
        if not clean:
            return []
        with self.connect() as con:
            for tag in clean:
                con.execute("INSERT OR IGNORE INTO knowledge_tags (name) VALUES (?)", (tag,))
        return clean

    def list_documents(
        self,
        status: str | None,
        owner_kind: str | None,
        owner_id: str | None,
        category_id: int | None,
        subcategory_id: int | None,
        tag: str | None,
        source_type: str | None,
        title: str | None,
        limit: int,
        offset: int,
    ) -> KnowledgeListDocumentsResult:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if owner_kind:
            clauses.append("owner_kind = ?")
            params.append(owner_kind)
        if owner_id:
            clauses.append("owner_id = ?")
            params.append(owner_id)
        if category_id is not None:
            clauses.append("category_id = ?")
            params.append(category_id)
        if subcategory_id is not None:
            clauses.append("subcategory_id = ?")
            params.append(subcategory_id)
        if source_type:
            clauses.append("source_type = ?")
            params.append(source_type)
        if title:
            clauses.append("title LIKE ?")
            params.append(f"%{title}%")
        if tag:
            clauses.append(
                """
                EXISTS (
                  SELECT 1 FROM knowledge_document_tags kdt
                  JOIN knowledge_tags kt ON kt.id = kdt.tag_id
                  WHERE kdt.document_id = knowledge_documents.id AND kt.name = ?
                )
                """
            )
            params.append(tag)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as con:
            total = con.execute(f"SELECT COUNT(*) AS n FROM knowledge_documents {where}", params).fetchone()["n"]
            rows = con.execute(
                f"""
                SELECT * FROM knowledge_documents
                {where}
                ORDER BY COALESCE(ingested_at, updated_at) DESC
                LIMIT ? OFFSET ?
                """,
                [*params, max(1, min(int(limit), 200)), max(0, int(offset))],
            ).fetchall()
        doc_ids = [str(row["id"]) for row in rows]
        tags_by_id = self.tags_by_document_ids(doc_ids)
        return KnowledgeListDocumentsResult(
            documents=[
                document_from_row(row, tags=tags_by_id.get(str(row["id"]), [])) for row in rows
            ],
            total=int(total),
        )

    def delete_document_row(self, document_id: str) -> bool:
        row = self.document_row_by_id(document_id)
        if row is None:
            return False
        with self.connect() as con:
            con.execute("DELETE FROM knowledge_documents WHERE id = ?", (document_id,))
        return True

    def tags_for_document(self, document_id: str) -> list[str]:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT kt.name
                FROM knowledge_document_tags kdt
                JOIN knowledge_tags kt ON kt.id = kdt.tag_id
                WHERE kdt.document_id = ?
                ORDER BY kt.name
                """,
                (document_id,),
            ).fetchall()
        return [str(row["name"]) for row in rows]

    def tags_by_document_ids(self, document_ids: Sequence[str]) -> dict[str, list[str]]:
        if not document_ids:
            return {}
        placeholders = ",".join("?" for _ in document_ids)
        with self.connect() as con:
            rows = con.execute(
                f"""
                SELECT kdt.document_id, kt.name
                FROM knowledge_document_tags kdt
                JOIN knowledge_tags kt ON kt.id = kdt.tag_id
                WHERE kdt.document_id IN ({placeholders})
                ORDER BY kt.name
                """,
                list(document_ids),
            ).fetchall()
        grouped: dict[str, list[str]] = {str(doc_id): [] for doc_id in document_ids}
        for row in rows:
            grouped[str(row["document_id"])].append(str(row["name"]))
        return grouped

    def validate_category_assignment(self, category_id: int | None, subcategory_id: int | None) -> None:
        if category_id is None and subcategory_id is None:
            return
        if subcategory_id is not None and category_id is None:
            raise ValueError("subcategory_id requires category_id.")
        with self.connect() as con:
            category = None
            if category_id is not None:
                category = con.execute(
                    "SELECT id, parent_id FROM knowledge_categories WHERE id = ?",
                    (int(category_id),),
                ).fetchone()
                if category is None:
                    raise ValueError(f"Unknown category id: {category_id}")
                if category["parent_id"] is not None:
                    raise ValueError("category_id must reference a top-level category.")
            if subcategory_id is not None:
                subcategory = con.execute(
                    "SELECT id, parent_id FROM knowledge_categories WHERE id = ?",
                    (int(subcategory_id),),
                ).fetchone()
                if subcategory is None:
                    raise ValueError(f"Unknown subcategory id: {subcategory_id}")
                if subcategory["parent_id"] is None:
                    raise ValueError("subcategory_id must reference a subcategory.")
                if int(subcategory["parent_id"]) != int(category_id):
                    raise ValueError("subcategory_id must belong to category_id.")

    def update_document_metadata(
        self,
        document_id: str,
        owner_kind: str,
        owner_id: str,
        category_id: int | None,
        subcategory_id: int | None,
        tags: Sequence[str],
    ) -> sqlite3.Row | None:
        existing = self.document_row_by_id(document_id)
        if existing is None:
            return None
        self.validate_category_assignment(category_id, subcategory_id)
        clean_tags = self.ensure_tags(tags)
        now = utc_now_iso()
        with self.connect() as con:
            # Metadata-only edits: updated_at only; ingested_at stays at last successful index.
            con.execute(
                """
                UPDATE knowledge_documents
                SET owner_kind = ?, owner_id = ?, category_id = ?, subcategory_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (owner_kind or "system", owner_id or "0", category_id, subcategory_id, now, document_id),
            )
            con.execute("DELETE FROM knowledge_document_tags WHERE document_id = ?", (document_id,))
            for tag in clean_tags:
                tag_id = con.execute("SELECT id FROM knowledge_tags WHERE name = ?", (tag,)).fetchone()["id"]
                con.execute(
                    "INSERT OR IGNORE INTO knowledge_document_tags (document_id, tag_id) VALUES (?, ?)",
                    (document_id, tag_id),
                )
            row = con.execute("SELECT * FROM knowledge_documents WHERE id = ?", (document_id,)).fetchone()
        return row

    def list_table(self, table: str) -> list[dict[str, Any]]:
        if table not in {"knowledge_tags", "knowledge_categories"}:
            raise ValueError("Unsupported table.")
        with self.connect() as con:
            rows = con.execute(f"SELECT * FROM {table} ORDER BY name").fetchall()
            return [dict(row) for row in rows]

    def create_category(self, name: str, parent_id: int | None) -> dict[str, Any]:
        clean_name = str(name).strip()
        if not clean_name:
            raise ValueError("Category name is required.")
        with self.connect() as con:
            if parent_id is None:
                existing = con.execute(
                    "SELECT * FROM knowledge_categories WHERE parent_id IS NULL AND name = ?",
                    (clean_name,),
                ).fetchone()
                if existing is not None:
                    return dict(existing)
            else:
                parent = con.execute(
                    "SELECT * FROM knowledge_categories WHERE id = ?",
                    (int(parent_id),),
                ).fetchone()
                if parent is None:
                    raise ValueError(f"Unknown parent category id: {parent_id}")
                if parent["parent_id"] is not None:
                    raise ValueError("Subcategories cannot have children.")
                existing = con.execute(
                    "SELECT * FROM knowledge_categories WHERE parent_id = ? AND name = ?",
                    (int(parent_id), clean_name),
                ).fetchone()
                if existing is not None:
                    return dict(existing)
            cur = con.execute(
                "INSERT INTO knowledge_categories (name, parent_id) VALUES (?, ?)",
                (clean_name, parent_id),
            )
            row = con.execute(
                "SELECT * FROM knowledge_categories WHERE id = ?",
                (cur.lastrowid,),
            ).fetchone()
            if row is None:
                raise RuntimeError("Created category row could not be loaded.")
            return dict(row)

    def create_tag(self, name: str) -> dict[str, Any]:
        clean_name = str(name).strip()
        if not clean_name:
            raise ValueError("Tag name is required.")
        with self.connect() as con:
            con.execute("INSERT OR IGNORE INTO knowledge_tags (name) VALUES (?)", (clean_name,))
            row = con.execute("SELECT * FROM knowledge_tags WHERE name = ?", (clean_name,)).fetchone()
            if row is None:
                raise RuntimeError("Created tag row could not be loaded.")
            return dict(row)

    @staticmethod
    def sql_known_chunk_count(db_path: Path) -> int:
        if not db_path.exists():
            return 0
        try:
            with sqlite3.connect(db_path) as con:
                row = con.execute(
                    "SELECT COALESCE(SUM(chunk_count), 0) FROM knowledge_documents"
                ).fetchone()
                return int(row[0] or 0) if row else 0
        except sqlite3.Error:
            return 0
