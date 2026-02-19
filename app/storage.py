from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


class SQLiteStore:
    def __init__(self, db_path: str = "data/note_nomi.db") -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_column(self, conn: sqlite3.Connection, table: str, col: str, col_def: str) -> None:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")

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

                CREATE TABLE IF NOT EXISTS categories (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL UNIQUE,
                  color TEXT,
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
                  options_json TEXT NOT NULL DEFAULT '{}',
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
            self._ensure_column(conn, "ingestion_jobs", "options_json", "TEXT NOT NULL DEFAULT '{}' ")

    def _row_to_note(self, row: sqlite3.Row) -> dict:
        category_name = row["category"]
        category_id = None
        if category_name:
            with self._connect() as conn:
                cat_row = conn.execute("SELECT id FROM categories WHERE name=?", (category_name,)).fetchone()
                category_id = int(cat_row["id"]) if cat_row else None
        return {
            "id": int(row["id"]),
            "sourceUrl": row["source_url"],
            "aiTitle": row["ai_title"] or "",
            "summaryShort": row["summary_short"] or "",
            "summaryLong": row["summary_long"] or "",
            "contentFull": row["content_full"],
            "category": {"id": category_id, "name": category_name} if category_name else None,
            "tags": [{"name": t, "type": "tag"} for t in json.loads(row["tags_json"])],
            "hashtags": [{"name": h, "type": "hashtag"} for h in json.loads(row["hashtags_json"])],
            "status": row["status"],
            "errorMessage": row["error_message"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def _build_notes_filter(
        self,
        q: str | None,
        category: str | None,
        category_id: int | None,
        status: str | None,
        tag: str | None,
        from_at: str | None,
        to_at: str | None,
    ) -> tuple[str, list[object]]:
        clauses: list[str] = []
        params: list[object] = []

        if q:
            clauses.append(
                "id IN (SELECT rowid FROM notes_fts WHERE notes_fts MATCH ? UNION SELECT id FROM notes WHERE tags_json LIKE ? OR hashtags_json LIKE ?)"
            )
            params.extend([q, f"%{q}%", f"%{q}%"])

        if category:
            clauses.append("category=?")
            params.append(category)

        if category_id is not None:
            clauses.append("category IN (SELECT name FROM categories WHERE id=?)")
            params.append(category_id)

        if status:
            clauses.append("status=?")
            params.append(status)

        if tag:
            clauses.append("(tags_json LIKE ? OR hashtags_json LIKE ?)")
            params.extend([f"%{tag}%", f"%{tag}%"])

        if from_at:
            clauses.append("created_at >= ?")
            params.append(from_at)

        if to_at:
            clauses.append("created_at <= ?")
            params.append(to_at)

        where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
        return where_sql, params

    def list_notes(
        self,
        q: str | None = None,
        category: str | None = None,
        category_id: int | None = None,
        status: str | None = None,
        tag: str | None = None,
        from_at: str | None = None,
        to_at: str | None = None,
        page: int = 1,
        size: int = 20,
        sort: str = "created_desc",
    ) -> tuple[list[dict], int]:
        where_sql, params = self._build_notes_filter(q, category, category_id, status, tag, from_at, to_at)
        order_by = {
            "created_desc": "created_at DESC",
            "created_asc": "created_at ASC",
            "updated_desc": "updated_at DESC",
            "updated_asc": "updated_at ASC",
        }.get(sort, "created_at DESC")
        offset = (page - 1) * size

        with self._connect() as conn:
            total_row = conn.execute(f"SELECT COUNT(*) AS c FROM notes{where_sql}", tuple(params)).fetchone()
            rows = conn.execute(
                f"SELECT * FROM notes{where_sql} ORDER BY {order_by} LIMIT ? OFFSET ?",
                tuple(params + [size, offset]),
            ).fetchall()
        total = int(total_row["c"]) if total_row else 0
        return [self._row_to_note(r) for r in rows], total

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
                    note.get("contentFull", ""),
                    note.get("category"),
                    json.dumps(note.get("tags", []), ensure_ascii=False),
                    json.dumps(note.get("hashtags", []), ensure_ascii=False),
                    note.get("status", "done"),
                    note.get("errorMessage"),
                    now,
                    now,
                ),
            )
            if note.get("category"):
                conn.execute(
                    """
                    INSERT INTO categories(name, created_at, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET updated_at=excluded.updated_at
                    """,
                    (note["category"], now, now),
                )
        return int(cur.lastrowid)

    def get_note(self, note_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone()
        return self._row_to_note(row) if row else None

    def update_note(self, note_id: int, patch: dict) -> dict | None:
        current = self.get_note(note_id)
        if not current:
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
            if category:
                conn.execute(
                    """
                    INSERT INTO categories(name, created_at, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET updated_at=excluded.updated_at
                    """,
                    (category, now, now),
                )
        return self.get_note(note_id)

    def delete_note(self, note_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM notes WHERE id=?", (note_id,))
        return cur.rowcount > 0

    def create_job(self, urls: list[str], options: dict | None = None) -> int:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO ingestion_jobs(
                  requested_count, queued_count, processing_count, done_count, failed_count, options_json, created_at, updated_at
                )
                VALUES (?, ?, 0, 0, 0, ?, ?, ?)
                """,
                (len(urls), len(urls), json.dumps(options or {}, ensure_ascii=False), now, now),
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
            "options": json.loads(row["options_json"] or "{}"),
            "counts": {
                "queued": row["queued_count"],
                "processing": row["processing_count"],
                "done": row["done_count"],
                "failed": row["failed_count"],
            },
            "items": self.list_job_items(job_id),
        }

    def update_job_item(
        self,
        job_id: int,
        source_url: str,
        status: str,
        note_id: int | None,
        error_code: str | None,
        error_message: str | None,
    ) -> None:
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

    def create_category(self, name: str, color: str | None = None) -> dict:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO categories(name, color, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                  color=COALESCE(excluded.color, categories.color),
                  updated_at=excluded.updated_at
                """,
                (name, color, now, now),
            )
            row = conn.execute("SELECT * FROM categories WHERE name=?", (name,)).fetchone()
        return {"id": int(row["id"]), "name": row["name"], "color": row["color"]}

    def get_category(self, category_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM categories WHERE id=?", (category_id,)).fetchone()
        if not row:
            return None
        return {"id": int(row["id"]), "name": row["name"], "color": row["color"]}

    def rename_category(self, from_name: str, to_name: str, color: str | None = None) -> bool:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            src = conn.execute("SELECT name FROM categories WHERE name=?", (from_name,)).fetchone()
            if src is None and from_name != to_name:
                note_has = conn.execute("SELECT 1 FROM notes WHERE category=? LIMIT 1", (from_name,)).fetchone()
                if note_has is None:
                    return False

            conn.execute(
                """
                INSERT INTO categories(name, color, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                  color=COALESCE(excluded.color, categories.color),
                  updated_at=excluded.updated_at
                """,
                (to_name, color, now, now),
            )
            conn.execute("UPDATE notes SET category=?, updated_at=? WHERE category=?", (to_name, now, from_name))
            conn.execute("DELETE FROM categories WHERE name=?", (from_name,))
        return True

    def rename_category_by_id(self, category_id: int, to_name: str, color: str | None = None) -> bool:
        src = self.get_category(category_id)
        if not src:
            return False
        return self.rename_category(src["name"], to_name, color=color)

    def merge_categories(self, source_names: list[str], target_name: str) -> int:
        now = datetime.now(UTC).isoformat()
        merged = 0
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO categories(name, created_at, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET updated_at=excluded.updated_at
                """,
                (target_name, now, now),
            )
            for source in source_names:
                if source == target_name:
                    continue
                cur = conn.execute("UPDATE notes SET category=?, updated_at=? WHERE category=?", (target_name, now, source))
                merged += cur.rowcount
                conn.execute("DELETE FROM categories WHERE name=?", (source,))
        return merged

    def list_categories(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.id, c.name, c.color, COALESCE(n.cnt, 0) AS note_count
                FROM categories c
                LEFT JOIN (
                  SELECT category, COUNT(*) AS cnt
                  FROM notes
                  WHERE category IS NOT NULL
                  GROUP BY category
                ) n ON c.name = n.category
                ORDER BY note_count DESC, c.name ASC
                """
            ).fetchall()
        return [{"id": int(r["id"]), "name": r["name"], "color": r["color"], "count": r["note_count"]} for r in rows]
