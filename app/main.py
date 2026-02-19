from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Literal
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import FastAPI, HTTPException, Query, Response
from pydantic import BaseModel, Field

from app.service import process_job
from app.storage import SQLiteStore

app = FastAPI(title="Note Nomi API", version="0.2.0")
store = SQLiteStore()
EXPORTS: dict[str, bytes] = {}


class IngestionOptions(BaseModel):
    summaryLength: Literal["short", "standard"] = "standard"
    autoCategory: bool = True
    storeFullContent: bool = True


class IngestionCreateRequest(BaseModel):
    urls: list[str] = Field(min_length=1)
    options: IngestionOptions = IngestionOptions()


class TagPayload(BaseModel):
    name: str
    type: Literal["tag", "hashtag"] = "tag"


class NotePatchRequest(BaseModel):
    aiTitle: str | None = None
    summaryShort: str | None = None
    summaryLong: str | None = None
    contentFull: str | None = None
    category: str | None = None
    tags: list[TagPayload] | None = None


class ExportRequest(BaseModel):
    target: dict
    format: Literal["markdown_zip", "text_zip"] = "markdown_zip"
    include: dict


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/ingestions")
def create_ingestion(payload: IngestionCreateRequest) -> dict:
    job_id = store.create_job(payload.urls)
    process_job(job_id, store)
    return {"jobId": job_id, "requestedCount": len(payload.urls), "status": "queued"}


@app.get("/api/v1/ingestions/{job_id}")
def get_ingestion(job_id: int) -> dict:
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job_not_found")
    return job


@app.post("/api/v1/ingestions/{job_id}/retry")
def retry_ingestion(job_id: int) -> dict:
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job_not_found")

    retried = store.mark_retry_failed_items(job_id)
    process_job(job_id, store)
    return {"jobId": job_id, "retried": retried}


@app.get("/api/v1/notes")
def list_notes(
    q: str | None = None,
    category: str | None = None,
    status: str | None = None,
) -> dict:
    notes = store.list_notes(q=q, category=category, status=status)
    return {"items": notes, "total": len(notes)}


@app.get("/api/v1/notes/{note_id}")
def get_note(note_id: int) -> dict:
    note = store.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="note_not_found")
    return note


@app.patch("/api/v1/notes/{note_id}")
def patch_note(note_id: int, payload: NotePatchRequest) -> dict:
    note = store.update_note(note_id, payload.model_dump(exclude_none=True))
    if not note:
        raise HTTPException(status_code=404, detail="note_not_found")
    return note


@app.delete("/api/v1/notes/{note_id}")
def delete_note(note_id: int) -> dict:
    deleted = store.delete_note(note_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="note_not_found")
    return {"deleted": True, "noteId": note_id}


@app.get("/api/v1/search")
def search(q: str, scope: Literal["all", "title_summary", "tags", "full_content"] = "all") -> dict:
    notes = store.list_notes()
    query = q.lower()
    matched: list[dict] = []

    for note in notes:
        title_summary_text = " ".join([note.get("aiTitle", ""), note.get("summaryShort", ""), note.get("summaryLong", "")]).lower()
        tags_text = " ".join([t["name"] for t in note.get("tags", [])] + [h["name"] for h in note.get("hashtags", [])]).lower()
        content_text = note.get("contentFull", "").lower()

        if scope == "title_summary" and query in title_summary_text:
            matched.append(note)
        elif scope == "tags" and query in tags_text:
            matched.append(note)
        elif scope == "full_content" and query in content_text:
            matched.append(note)
        elif scope == "all" and (query in title_summary_text or query in tags_text or query in content_text):
            matched.append(note)

    return {"scope": scope, "q": q, "items": matched, "total": len(matched)}


def _render_note(note: dict, include: dict, markdown: bool) -> str:
    lines: list[str] = []
    def add(label: str, val: str | None) -> None:
        if not val:
            return
        if markdown:
            lines.append(f"## {label}\n{val}\n")
        else:
            lines.append(f"[{label}]\n{val}\n")

    add("Source URL", note.get("sourceUrl") if include.get("sourceUrl", True) else None)
    add("AI Title", note.get("aiTitle") if include.get("aiTitle", True) else None)
    add("Summary Short", note.get("summaryShort") if include.get("summaryShort", True) else None)
    add("Summary Long", note.get("summaryLong") if include.get("summaryLong", True) else None)
    if include.get("tags", True):
        tag_text = ", ".join([t["name"] for t in note.get("tags", [])] + [h["name"] for h in note.get("hashtags", [])])
        add("Tags", tag_text)
    add("Content Full", note.get("contentFull") if include.get("contentFull", True) else None)

    return "\n".join(lines).strip() + "\n"


@app.post("/api/v1/exports/notebooklm")
def export_notebooklm(payload: ExportRequest) -> dict:
    notes = store.list_notes()
    target_type = payload.target.get("type")

    if target_type == "category":
        category_name = payload.target.get("category")
        notes = [n for n in notes if (n.get("category") or {}).get("name") == category_name]
    elif target_type == "note_ids":
        note_ids = set(payload.target.get("noteIds", []))
        notes = [n for n in notes if n["id"] in note_ids]

    markdown = payload.format == "markdown_zip"
    ext = "md" if markdown else "txt"

    buff = BytesIO()
    with ZipFile(buff, mode="w", compression=ZIP_DEFLATED) as zf:
        for note in notes:
            content = _render_note(note, payload.include, markdown=markdown)
            zf.writestr(f"note-{note['id']}.{ext}", content)

    export_id = f"exp_{int(datetime.now(UTC).timestamp())}"
    EXPORTS[export_id] = buff.getvalue()
    expires_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()

    return {
        "exportId": export_id,
        "downloadUrl": f"/api/v1/exports/{export_id}/download",
        "expiresAt": expires_at,
    }


@app.get("/api/v1/exports/{export_id}/download")
def download_export(export_id: str) -> Response:
    data = EXPORTS.get(export_id)
    if data is None:
        raise HTTPException(status_code=404, detail="export_not_found")
    return Response(content=data, media_type="application/zip")


@app.get("/api/v1/categories")
def list_categories() -> dict:
    notes = store.list_notes()
    cat_counts: dict[str, int] = {}
    for note in notes:
        cat = ((note.get("category") or {}).get("name") or "미분류")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
    return {"items": [{"name": k, "count": v} for k, v in sorted(cat_counts.items())]}


@app.get("/api/v1/tags")
def list_tags(limit: int = Query(20, ge=1, le=200)) -> dict:
    notes = store.list_notes()
    counts: dict[str, int] = {}
    for note in notes:
        for tag in note.get("tags", []):
            key = tag["name"]
            counts[key] = counts.get(key, 0) + 1
        for tag in note.get("hashtags", []):
            key = tag["name"]
            counts[key] = counts.get(key, 0) + 1

    items = [{"name": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]]
    return {"items": items}
