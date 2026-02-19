from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, UTC
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
            conn.execute(
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
                  created_at TEXT NOT NULL
                )
                """
            )

    def create_note(self, note: dict) -> int:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO notes (
                  source_url, ai_title, summary_short, summary_long, content_full,
                  category, tags_json, hashtags_json, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    now,
                ),
            )
            return int(cur.lastrowid)

    def get_note(self, note_id: int) -> StoredNote | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        if row is None:
            return None
        return StoredNote(
            id=int(row["id"]),
            source_url=row["source_url"],
            ai_title=row["ai_title"] or "",
            summary_short=row["summary_short"] or "",
            summary_long=row["summary_long"] or "",
            content_full=row["content_full"],
            category=row["category"] or "",
            tags=json.loads(row["tags_json"]),
            hashtags=json.loads(row["hashtags_json"]),
            status=row["status"],
            created_at=row["created_at"],
        )
