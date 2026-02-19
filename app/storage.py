from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class StoredNote:
    id: int
    source_url: str
    ai_title: str
    summary_short: str
    summary_long: str
    content_full: str
    category: str
    tags: list[str]
    hashtags: list[str]
    status: str
    created_at: str


class SQLiteStore:
    def __init__(self, db_path: str = "data/note_nomi.db") -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS notes (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  source_url TEXT NOT NULL,
                  ai_title TEXT,
                  summary_short TEXT,
                  summary_long TEXT,
                  content_full TEXT NOT NULL,
                  category TEXT,
                  tags_json TEXT NOT NULL DEFAULT '[]',
                  hashtags_json TEXT NOT NULL DEFAULT '[]',
                  status TEXT NOT NULL,
                  error_message TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ingestion_jobs (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  requested_count INTEGER NOT NULL,
                  queued_count INTEGER NOT NULL,
                  processing_count INTEGER NOT NULL,
                  done_count INTEGER NOT NULL,
                  failed_count INTEGER NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ingestion_job_items (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  job_id INTEGER NOT NULL,
                  source_url TEXT NOT NULL,
                  note_id INTEGER,
                  status TEXT NOT NULL,
                  error_code TEXT,
                  error_message TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  FOREIGN KEY(job_id) REFERENCES ingestion_jobs(id)
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
                  ai_title,
                  summary_short,
                  summary_long,
                  content_full,
                  content='notes',
                  content_rowid='id'
                );

                CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
                  INSERT INTO notes_fts(rowid, ai_title, summary_short, summary_long, content_full)
                  VALUES (new.id, new.ai_title, new.summary_short, new.summary_long, new.content_full);
                END;

                CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
                  INSERT INTO notes_fts(notes_fts, rowid, ai_title, summary_short, summary_long, content_full)
                  VALUES ('delete', old.id, old.ai_title, old.summary_short, old.summary_long, old.content_full);
                  INSERT INTO notes_fts(rowid, ai_title, summary_short, summary_long, content_full)
                  VALUES (new.id, new.ai_title, new.summary_short, new.summary_long, new.content_full);
                END;

                CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
                  INSERT INTO notes_fts(notes_fts, rowid, ai_title, summary_short, summary_long, content_full)
                  VALUES ('delete', old.id, old.ai_title, old.summary_short, old.summary_long, old.content_full);
                END;
                """
            )

    def _row_to_note(self, row: sqlite3.Row) -> dict:
        return {
            "id": int(row["id"]),
            "sourceUrl": row["source_url"],
            "aiTitle": row["ai_title"] or "",
            "summaryShort": row["summary_short"] or "",
            "summaryLong": row["summary_long"] or "",
            "contentFull": row["content_full"],
            "category": {"name": row["category"]} if row["category"] else None,
            "tags": [{"name": t, "type": "tag"} for t in json.loads(row["tags_json"])],
            "hashtags": [{"name": h, "type": "hashtag"} for h in json.loads(row["hashtags_json"])],
            "status": row["status"],
            "errorMessage": row["error_message"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def create_note(self, note: dict) -> int:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO notes (
                  source_url, ai_title, summary_short, summary_long, content_full,
                  category, tags_json, hashtags_json, status, error_message, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    note["sourceUrl"],
                    note.get("aiTitle"),
                    note.get("summaryShort"),
                    note.get("summaryLong"),
                    note["contentFull"],
                    note.get("category"),
                    json.dumps(note.get("tags", []), ensure_ascii=False),
                    json.dumps(note.get("hashtags", []), ensure_ascii=False),
                    note.get("status", "done"),
                    note.get("errorMessage"),
                    now,
                    now,
                ),
            )
            return int(cur.lastrowid)

    def get_note(self, note_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        return self._row_to_note(row) if row else None

    def list_notes(self, q: str | None = None, category: str | None = None, status: str | None = None) -> list[dict]:
        query = "SELECT n.* FROM notes n"
        params: list[str] = []
        clauses: list[str] = []

        if q:
            query = "SELECT n.* FROM notes n JOIN notes_fts f ON n.id = f.rowid"
            clauses.append("notes_fts MATCH ?")
            params.append(q)
        if category:
            clauses.append("n.category = ?")
            params.append(category)
        if status:
            clauses.append("n.status = ?")
            params.append(status)

        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY n.id DESC"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_note(r) for r in rows]

    def update_note(self, note_id: int, patch: dict) -> dict | None:
        current = self.get_note(note_id)
        if current is None:
            return None

        ai_title = patch.get("aiTitle", current["aiTitle"])
        summary_short = patch.get("summaryShort", current["summaryShort"])
        summary_long = patch.get("summaryLong", current["summaryLong"])
        content_full = patch.get("contentFull", current["contentFull"])
        category = patch.get("category")
        if category is None:
            category = (current.get("category") or {}).get("name")
        tags_payload = patch.get("tags")
        if tags_payload is None:
            tags_list = [t["name"] for t in current.get("tags", [])]
            hashtags_list = [h["name"] for h in current.get("hashtags", [])]
        else:
            tags_list = [t["name"] for t in tags_payload if t.get("type") == "tag"]
            hashtags_list = [t["name"] for t in tags_payload if t.get("type") == "hashtag"]

        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE notes
                SET ai_title=?, summary_short=?, summary_long=?, content_full=?, category=?,
                    tags_json=?, hashtags_json=?, updated_at=?
                WHERE id=?
                """,
                (
                    ai_title,
                    summary_short,
                    summary_long,
                    content_full,
                    category,
                    json.dumps(tags_list, ensure_ascii=False),
                    json.dumps(hashtags_list, ensure_ascii=False),
                    now,
                    note_id,
                ),
            )
        return self.get_note(note_id)

    def delete_note(self, note_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM notes WHERE id=?", (note_id,))
        return cur.rowcount > 0

    def create_job(self, urls: list[str]) -> int:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO ingestion_jobs(requested_count, queued_count, processing_count, done_count, failed_count, created_at, updated_at)
                VALUES (?, ?, 0, 0, 0, ?, ?)
                """,
                (len(urls), len(urls), now, now),
            )
            job_id = int(cur.lastrowid)
            conn.executemany(
                """
                INSERT INTO ingestion_job_items(job_id, source_url, note_id, status, error_code, error_message, created_at, updated_at)
                VALUES (?, ?, NULL, 'queued', NULL, NULL, ?, ?)
                """,
                [(job_id, url, now, now) for url in urls],
            )
        return job_id

    def list_job_items(self, job_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT source_url, status, note_id, error_code, error_message FROM ingestion_job_items WHERE job_id=? ORDER BY id",
                (job_id,),
            ).fetchall()
        return [
            {
                "sourceUrl": r["source_url"],
                "status": r["status"],
                "noteId": r["note_id"],
                "errorCode": r["error_code"],
                "errorMessage": r["error_message"],
            }
            for r in rows
        ]

    def get_job(self, job_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM ingestion_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return None
        return {
            "jobId": int(row["id"]),
            "counts": {
                "queued": row["queued_count"],
                "processing": row["processing_count"],
                "done": row["done_count"],
                "failed": row["failed_count"],
            },
            "items": self.list_job_items(job_id),
        }

    def update_job_item(self, job_id: int, source_url: str, status: str, note_id: int | None, error_code: str | None, error_message: str | None) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE ingestion_job_items
                SET status=?, note_id=?, error_code=?, error_message=?, updated_at=?
                WHERE job_id=? AND source_url=?
                """,
                (status, note_id, error_code, error_message, now, job_id, source_url),
            )

    def recalc_job_counts(self, job_id: int) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                  SUM(CASE WHEN status='queued' THEN 1 ELSE 0 END) AS queued_count,
                  SUM(CASE WHEN status='processing' THEN 1 ELSE 0 END) AS processing_count,
                  SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) AS done_count,
                  SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed_count
                FROM ingestion_job_items WHERE job_id=?
                """,
                (job_id,),
            ).fetchone()
            conn.execute(
                """
                UPDATE ingestion_jobs
                SET queued_count=?, processing_count=?, done_count=?, failed_count=?, updated_at=?
                WHERE id=?
                """,
                (
                    row["queued_count"] or 0,
                    row["processing_count"] or 0,
                    row["done_count"] or 0,
                    row["failed_count"] or 0,
                    now,
                    job_id,
                ),
            )

    def mark_retry_failed_items(self, job_id: int) -> int:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE ingestion_job_items
                SET status='queued', error_code=NULL, error_message=NULL, updated_at=?
                WHERE job_id=? AND status='failed'
                """,
                (now, job_id),
            )
        self.recalc_job_counts(job_id)
        return cur.rowcount
