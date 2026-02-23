from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.note_kinds import KIND_ORDER, NoteKindsResult, compute_note_kinds


class SQLiteStore:
    def __init__(self, db_path: str = "data/note_nomi.db") -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_column(
        self, conn: sqlite3.Connection, table: str, col: str, col_def: str
    ) -> None:
        cols = {
            r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
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
            self._ensure_column(
                conn, "ingestion_jobs", "options_json", "TEXT NOT NULL DEFAULT '{}' "
            )
            self._ensure_column(conn, "notes", "primary_kind", "TEXT")
            self._ensure_column(
                conn, "notes", "kinds_json", "TEXT NOT NULL DEFAULT '[]'"
            )

    def _compute_note_kinds(
        self,
        source_url: str,
        content_full: str,
        summary_short: str,
        summary_long: str,
    ) -> NoteKindsResult:
        return compute_note_kinds(
            {
                "sourceUrl": source_url,
                "contentFull": content_full,
                "summaryShort": summary_short,
                "summaryLong": summary_long,
            }
        )

    def _row_to_note(self, row: sqlite3.Row) -> dict[str, Any]:
        category_name = row["category"]
        category_id = None
        if category_name:
            with self._connect() as conn:
                cat_row = conn.execute(
                    "SELECT id FROM categories WHERE name=?", (category_name,)
                ).fetchone()
                category_id = int(cat_row["id"] or 0) if cat_row else None
        kinds_info = self._compute_note_kinds(
            row["source_url"] or "",
            row["content_full"] or "",
            row["summary_short"] or "",
            row["summary_long"] or "",
        )
        row_keys = set(row.keys())
        primary_kind = (
            row["primary_kind"]
            if "primary_kind" in row_keys and row["primary_kind"]
            else kinds_info["primary_kind"]
        )
        kinds: list[str]
        if "kinds_json" in row_keys and row["kinds_json"]:
            try:
                raw_kinds = json.loads(row["kinds_json"])
                if isinstance(raw_kinds, list) and all(
                    isinstance(kind, str) for kind in raw_kinds
                ):
                    kinds = raw_kinds
                else:
                    kinds = kinds_info["kinds"]
            except json.JSONDecodeError:
                kinds = kinds_info["kinds"]
        else:
            kinds = kinds_info["kinds"]

        return {
            "id": int(row["id"] or 0),
            "sourceUrl": row["source_url"],
            "aiTitle": row["ai_title"] or "",
            "summaryShort": row["summary_short"] or "",
            "summaryLong": row["summary_long"] or "",
            "contentFull": row["content_full"],
            "category": {"id": category_id, "name": category_name}
            if category_name
            else None,
            "tags": [{"name": t, "type": "tag"} for t in json.loads(row["tags_json"])],
            "hashtags": [
                {"name": h, "type": "hashtag"} for h in json.loads(row["hashtags_json"])
            ],
            "status": row["status"],
            "errorMessage": row["error_message"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "primaryKind": primary_kind,
            "kinds": kinds,
        }

    def _build_notes_filter(
        self,
        q: str | None,
        q_scope: str,
        category: str | None,
        category_id: int | None,
        kind: str | None,
        status: str | None,
        tag: str | None,
        from_at: str | None,
        to_at: str | None,
        *,
        kind_filter_mode: str = "json_each",
    ) -> tuple[str, list[object]]:
        clauses: list[str] = []
        params: list[object] = []

        if q:
            terms = [part for part in (x.strip() for x in q.split()) if part]
            if terms:
                escaped_terms: list[str] = []
                for term in terms:
                    safe_term = term.replace('"', '""')
                    escaped_terms.append(f'"{safe_term}"*')
                token_query = " AND ".join(escaped_terms)
                if q_scope == "tags":
                    clauses.append("(tags_json LIKE ? OR hashtags_json LIKE ?)")
                    params.extend([f"%{q}%", f"%{q}%"])
                elif q_scope == "title_summary":
                    fts_query = f"(ai_title : {token_query} OR summary_short : {token_query} OR summary_long : {token_query})"
                    clauses.append(
                        "id IN (SELECT rowid FROM notes_fts WHERE notes_fts MATCH ?)"
                    )
                    params.append(fts_query)
                elif q_scope == "full_content":
                    fts_query = f"content_full : {token_query}"
                    clauses.append(
                        "id IN (SELECT rowid FROM notes_fts WHERE notes_fts MATCH ?)"
                    )
                    params.append(fts_query)
                else:
                    clauses.append(
                        "id IN (SELECT rowid FROM notes_fts WHERE notes_fts MATCH ? UNION SELECT id FROM notes WHERE tags_json LIKE ? OR hashtags_json LIKE ?)"
                    )
                    params.extend([token_query, f"%{q}%", f"%{q}%"])

        if category:
            clauses.append("category=?")
            params.append(category)

        if category_id is not None:
            clauses.append("category IN (SELECT name FROM categories WHERE id=?)")
            params.append(category_id)

        if kind:
            if kind_filter_mode == "json_each":
                clauses.append(
                    "EXISTS (SELECT 1 FROM json_each(notes.kinds_json) WHERE json_each.value = ?)"
                )
                params.append(kind)
            else:
                clauses.append("kinds_json LIKE ?")
                params.append(f'%"{kind}"%')

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
        q_scope: str = "all",
        category: str | None = None,
        category_id: int | None = None,
        kind: str | None = None,
        status: str | None = None,
        tag: str | None = None,
        from_at: str | None = None,
        to_at: str | None = None,
        page: int = 1,
        size: int = 20,
        sort: str = "created_desc",
    ) -> tuple[list[dict[str, Any]], int]:
        where_sql, params = self._build_notes_filter(
            q, q_scope, category, category_id, kind, status, tag, from_at, to_at
        )
        order_by = {
            "created_desc": "created_at DESC",
            "created_asc": "created_at ASC",
            "updated_desc": "updated_at DESC",
            "updated_asc": "updated_at ASC",
        }.get(sort, "created_at DESC")
        offset = (page - 1) * size

        with self._connect() as conn:
            try:
                total_row = conn.execute(
                    f"SELECT COUNT(*) AS c FROM notes{where_sql}", tuple(params)
                ).fetchone()
                rows = conn.execute(
                    f"SELECT * FROM notes{where_sql} ORDER BY {order_by} LIMIT ? OFFSET ?",
                    tuple(params + [size, offset]),
                ).fetchall()
            except sqlite3.OperationalError as exc:
                if not kind or "json_each" not in str(exc).lower():
                    raise
                where_sql, params = self._build_notes_filter(
                    q,
                    q_scope,
                    category,
                    category_id,
                    kind,
                    status,
                    tag,
                    from_at,
                    to_at,
                    kind_filter_mode="like",
                )
                total_row = conn.execute(
                    f"SELECT COUNT(*) AS c FROM notes{where_sql}", tuple(params)
                ).fetchone()
                rows = conn.execute(
                    f"SELECT * FROM notes{where_sql} ORDER BY {order_by} LIMIT ? OFFSET ?",
                    tuple(params + [size, offset]),
                ).fetchall()
        total_raw = total_row["c"] if total_row else 0
        total = int(total_raw or 0)
        return [self._row_to_note(r) for r in rows], total

    def count_note_kinds(
        self,
        q: str | None = None,
        category: str | None = None,
        category_id: int | None = None,
        status: str | None = None,
        tag: str | None = None,
        from_at: str | None = None,
        to_at: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        where_sql, params = self._build_notes_filter(
            q,
            "all",
            category,
            category_id,
            None,
            status,
            tag,
            from_at,
            to_at,
        )
        counts_by_kind = {kind: 0 for kind in KIND_ORDER}

        with self._connect() as conn:
            total_row = conn.execute(
                f"SELECT COUNT(*) AS c FROM notes{where_sql}", tuple(params)
            ).fetchone()
            try:
                rows = conn.execute(
                    f"""
                    SELECT json_each.value AS kind, COUNT(DISTINCT notes.id) AS c
                    FROM notes
                    JOIN json_each(notes.kinds_json)
                    {where_sql}
                    GROUP BY json_each.value
                    """,
                    tuple(params),
                ).fetchall()
                for row in rows:
                    kind = row["kind"]
                    if kind in counts_by_kind:
                        counts_by_kind[kind] = int(row["c"] or 0)
            except sqlite3.OperationalError as exc:
                if "json_each" not in str(exc).lower():
                    raise
                for kind in KIND_ORDER:
                    kind_where_sql = (
                        f"{where_sql} AND kinds_json LIKE ?"
                        if where_sql
                        else " WHERE kinds_json LIKE ?"
                    )
                    row = conn.execute(
                        f"SELECT COUNT(*) AS c FROM notes{kind_where_sql}",
                        tuple(params + [f'%"{kind}"%']),
                    ).fetchone()
                    counts_by_kind[kind] = int((row["c"] if row else 0) or 0)

        total_raw = total_row["c"] if total_row else 0
        total_notes = int(total_raw or 0)
        items = [{"kind": kind, "count": counts_by_kind[kind]} for kind in KIND_ORDER]
        return items, total_notes

    def create_note(self, note: dict[str, Any]) -> int:
        now = datetime.now(UTC).isoformat()
        created_at = (
            note.get("createdAt") if isinstance(note.get("createdAt"), str) else now
        )
        updated_at = (
            note.get("updatedAt") if isinstance(note.get("updatedAt"), str) else now
        )
        kinds_info = self._compute_note_kinds(
            note.get("sourceUrl", ""),
            note.get("contentFull", ""),
            note.get("summaryShort", ""),
            note.get("summaryLong", ""),
        )

        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO notes (
                  source_url, ai_title, summary_short, summary_long, content_full,
                  category, tags_json, hashtags_json, status, error_message, created_at, updated_at,
                  primary_kind, kinds_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    created_at,
                    updated_at,
                    kinds_info["primary_kind"],
                    json.dumps(kinds_info["kinds"], ensure_ascii=False),
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
        lastrowid = cur.lastrowid
        return int(lastrowid or 0)

    def get_note_by_source_url(self, source_url: str) -> dict[str, Any] | None:
        """source_url로 노트 한 건 조회 (중복 체크용)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM notes WHERE source_url=?", (source_url,)
            ).fetchone()
        return self._row_to_note(row) if row else None

    def get_note(self, note_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone()
        return self._row_to_note(row) if row else None

    def update_note(self, note_id: int, patch: dict[str, Any]) -> dict[str, Any] | None:
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
            hashtags_list = [
                t["name"] for t in tags_payload if t.get("type") == "hashtag"
            ]

        now = datetime.now(UTC).isoformat()
        kinds_info = self._compute_note_kinds(
            current["sourceUrl"],
            content_full,
            summary_short,
            summary_long,
        )
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE notes
                SET ai_title=?, summary_short=?, summary_long=?, content_full=?, category=?,
                    tags_json=?, hashtags_json=?, primary_kind=?, kinds_json=?, updated_at=?
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
                    kinds_info["primary_kind"],
                    json.dumps(kinds_info["kinds"], ensure_ascii=False),
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

    def batch_update_note_metadata(
        self, note_ids: list[int], patch: dict[str, Any]
    ) -> dict[str, Any]:
        deduped_ids = list(dict.fromkeys(note_ids))
        if not deduped_ids:
            return {"updated": 0, "noteIds": [], "notFoundIds": []}

        has_category = "category" in patch
        has_tags = "tags" in patch
        if not has_category and not has_tags:
            return {"updated": 0, "noteIds": [], "notFoundIds": deduped_ids}

        placeholders = ",".join("?" for _ in deduped_ids)
        now = datetime.now(UTC).isoformat()

        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT id FROM notes WHERE id IN ({placeholders})", tuple(deduped_ids)
            ).fetchall()
            found_ids = [int(row["id"] or 0) for row in rows]
            found_set = set(found_ids)
            not_found_ids = [
                note_id for note_id in deduped_ids if note_id not in found_set
            ]

            if not found_ids:
                return {"updated": 0, "noteIds": [], "notFoundIds": not_found_ids}

            set_clauses: list[str] = []
            params: list[object] = []

            if has_category:
                set_clauses.append("category=?")
                params.append(patch.get("category"))

            if has_tags:
                tags_payload = patch.get("tags") or []
                tags_list = [t["name"] for t in tags_payload if t.get("type") == "tag"]
                hashtags_list = [
                    t["name"] for t in tags_payload if t.get("type") == "hashtag"
                ]
                set_clauses.extend(["tags_json=?", "hashtags_json=?"])
                params.extend(
                    [
                        json.dumps(tags_list, ensure_ascii=False),
                        json.dumps(hashtags_list, ensure_ascii=False),
                    ]
                )

            set_clauses.append("updated_at=?")
            params.append(now)

            found_placeholders = ",".join("?" for _ in found_ids)
            conn.execute(
                f"UPDATE notes SET {', '.join(set_clauses)} WHERE id IN ({found_placeholders})",
                tuple(params + found_ids),
            )

            category = patch.get("category")
            if has_category and category:
                conn.execute(
                    """
                    INSERT INTO categories(name, created_at, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET updated_at=excluded.updated_at
                    """,
                    (category, now, now),
                )

        return {
            "updated": len(found_ids),
            "noteIds": found_ids,
            "notFoundIds": not_found_ids,
        }

    def backfill_note_kinds(
        self, batch_size: int = 5000, max_rows: int = 20000
    ) -> dict[str, int]:
        scanned = 0
        updated = 0
        if max_rows <= 0:
            return {"scanned": scanned, "updated": updated}

        step = max(1, batch_size)
        remaining = max_rows

        while remaining > 0:
            limit = min(step, remaining)
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT id, source_url, content_full, summary_short, summary_long
                    FROM notes
                    WHERE kinds_json IS NULL
                       OR TRIM(kinds_json) = ''
                       OR TRIM(kinds_json) = '[]'
                    ORDER BY id
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()

                if not rows:
                    break

                now = datetime.now(UTC).isoformat()
                update_payload: list[tuple[str, str, str, int]] = []
                for row in rows:
                    kinds_info = self._compute_note_kinds(
                        row["source_url"] or "",
                        row["content_full"] or "",
                        row["summary_short"] or "",
                        row["summary_long"] or "",
                    )
                    update_payload.append(
                        (
                            kinds_info["primary_kind"],
                            json.dumps(kinds_info["kinds"], ensure_ascii=False),
                            now,
                            int(row["id"] or 0),
                        )
                    )

                conn.executemany(
                    """
                    UPDATE notes
                    SET primary_kind=?, kinds_json=?, updated_at=?
                    WHERE id=?
                    """,
                    update_payload,
                )

                batch_count = len(update_payload)
                scanned += batch_count
                updated += batch_count
                remaining -= batch_count

                if batch_count < limit:
                    break

        return {"scanned": scanned, "updated": updated}

    def delete_note(self, note_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM notes WHERE id=?", (note_id,))
        return cur.rowcount > 0

    def delete_all_notes(self) -> int:
        """전체 노트 삭제(초기화). 삭제된 행 수 반환."""
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM notes")
        return cur.rowcount

    def list_tags(self) -> list[dict[str, Any]]:
        """노트에서 사용 중인 태그/해시태그 이름 목록 (이름, 노트 개수)."""
        seen: dict[str, int] = {}
        with self._connect() as conn:
            rows = conn.execute("SELECT tags_json, hashtags_json FROM notes").fetchall()
        for row in rows:
            for name in json.loads(row["tags_json"] or "[]"):
                if name:
                    seen[name] = seen.get(name, 0) + 1
            for name in json.loads(row["hashtags_json"] or "[]"):
                if name:
                    seen[name] = seen.get(name, 0) + 1
        return [
            {"name": name, "count": count}
            for name, count in sorted(seen.items(), key=lambda x: (-x[1], x[0]))
        ]

    def create_job(self, urls: list[str], options: dict[str, Any] | None = None) -> int:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO ingestion_jobs(
                  requested_count, queued_count, processing_count, done_count, failed_count, options_json, created_at, updated_at
                )
                VALUES (?, ?, 0, 0, 0, ?, ?, ?)
                """,
                (
                    len(urls),
                    len(urls),
                    json.dumps(options or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            lastrowid = cur.lastrowid
            job_id = int(lastrowid or 0)
            conn.executemany(
                """
                INSERT INTO ingestion_job_items(job_id, source_url, note_id, status, error_code, error_message, created_at, updated_at)
                VALUES (?, ?, NULL, 'queued', NULL, NULL, ?, ?)
                """,
                [(job_id, url, now, now) for url in urls],
            )
        return job_id

    def list_job_items(self, job_id: int) -> list[dict[str, Any]]:
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

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM ingestion_jobs WHERE id=?", (job_id,)
            ).fetchone()
        if row is None:
            return None
        return {
            "jobId": int(row["id"] or 0),
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

    def create_category(self, name: str, color: str | None = None) -> dict[str, Any]:
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
            row = conn.execute(
                "SELECT * FROM categories WHERE name=?", (name,)
            ).fetchone()
        return {
            "id": int(row["id"] or 0),
            "name": row["name"],
            "color": row["color"],
        }

    def get_category(self, category_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM categories WHERE id=?", (category_id,)
            ).fetchone()
        if not row:
            return None
        return {
            "id": int(row["id"] or 0),
            "name": row["name"],
            "color": row["color"],
        }

    def rename_category(
        self, from_name: str, to_name: str, color: str | None = None
    ) -> bool:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            src = conn.execute(
                "SELECT name FROM categories WHERE name=?", (from_name,)
            ).fetchone()
            if src is None and from_name != to_name:
                note_has = conn.execute(
                    "SELECT 1 FROM notes WHERE category=? LIMIT 1", (from_name,)
                ).fetchone()
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
            conn.execute(
                "UPDATE notes SET category=?, updated_at=? WHERE category=?",
                (to_name, now, from_name),
            )
            conn.execute("DELETE FROM categories WHERE name=?", (from_name,))
        return True

    def rename_category_by_id(
        self, category_id: int, to_name: str, color: str | None = None
    ) -> bool:
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
                cur = conn.execute(
                    "UPDATE notes SET category=?, updated_at=? WHERE category=?",
                    (target_name, now, source),
                )
                merged += cur.rowcount
                conn.execute("DELETE FROM categories WHERE name=?", (source,))
        return merged

    def list_categories(self) -> list[dict[str, Any]]:
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
        return [
            {
                "id": int(r["id"] or 0),
                "name": r["name"],
                "color": r["color"],
                "count": r["note_count"],
            }
            for r in rows
        ]
