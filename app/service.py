from __future__ import annotations

from app.analysis_worker import process_url
from app.storage import SQLiteStore


def analyze_and_store(url: str, store: SQLiteStore, options: dict | None = None) -> dict:
    result = process_url(url, options=options)
    if result.get("status") in {"done", "partial_done"}:
        note_id = store.create_note(result)
        result["noteId"] = note_id
    return result


def process_job(job_id: int, store: SQLiteStore) -> dict:
    job = store.get_job(job_id)
    if job is None:
        return {"error": "job_not_found"}

    options = job.get("options", {})

    for item in job["items"]:
        if item["status"] != "queued":
            continue

        source_url = item["sourceUrl"]
        store.update_job_item(job_id, source_url, "processing", None, None, None)
        store.recalc_job_counts(job_id)

        result = analyze_and_store(source_url, store, options=options)
        status = result.get("status", "failed")
        if status in {"done", "partial_done"}:
            store.update_job_item(job_id, source_url, "done", result.get("noteId"), None, None)
        else:
            error_code = status
            error_message = result.get("errorMessage", "processing failed")
            store.update_job_item(job_id, source_url, "failed", None, error_code, error_message)

        store.recalc_job_counts(job_id)

    return store.get_job(job_id) or {"error": "job_not_found"}
