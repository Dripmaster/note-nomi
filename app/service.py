from __future__ import annotations

from app.analysis_worker import process_url
from app.storage import SQLiteStore


def analyze_and_store(url: str, store: SQLiteStore) -> dict:
    result = process_url(url)
    if result.get("status") in {"done", "partial_done"}:
        note_id = store.create_note(result)
        result["noteId"] = note_id
    return result
