from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Literal
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.config import get_config
from app.job_runner import JobRunner
from app.storage import SQLiteStore

config = get_config()
app = FastAPI(title="Note Nomi API", version="0.5.0")
store = SQLiteStore(db_path=config.db_path)
job_runner = JobRunner(max_workers=2)
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


class CategoryCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    color: str | None = None


class CategoryUpdateRequest(BaseModel):
    fromName: str = Field(min_length=1)
    toName: str = Field(min_length=1)
    color: str | None = None


class CategoryRenameByIdRequest(BaseModel):
    toName: str = Field(min_length=1)
    color: str | None = None


class CategoryMergeRequest(BaseModel):
    targetName: str = Field(min_length=1)
    sourceNames: list[str] = Field(min_length=1)


def _snippet(note: dict, q: str, scope: str) -> str:
    target = ""
    if scope in {"all", "title_summary"}:
        target = " ".join([note.get("aiTitle", ""), note.get("summaryShort", ""), note.get("summaryLong", "")])
    if not target and scope in {"all", "tags"}:
        target = " ".join([t["name"] for t in note.get("tags", [])] + [h["name"] for h in note.get("hashtags", [])])
    if not target and scope in {"all", "full_content"}:
        target = note.get("contentFull", "")

    lowered = target.lower()
    idx = lowered.find(q.lower())
    if idx == -1:
        return target[:180]
    start = max(0, idx - 60)
    end = min(len(target), idx + 120)
    return target[start:end]




@app.get("/")
def home() -> FileResponse:
    return FileResponse("app/static/index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/ingestions")
def create_ingestion(payload: IngestionCreateRequest) -> dict:
    options = payload.options.model_dump()
    job_id = store.create_job(payload.urls, options=options)
    job_runner.enqueue(job_id, store)
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
    if retried > 0:
        job_runner.enqueue(job_id, store)
    return {"jobId": job_id, "retried": retried}


@app.get("/api/v1/notes")
def list_notes(
    q: str | None = None,
    category: str | None = None,
    categoryId: int | None = None,
    status: str | None = None,
    tag: str | None = None,
    fromAt: str | None = None,
    toAt: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    sort: Literal["created_desc", "created_asc", "updated_desc", "updated_asc"] = "created_desc",
) -> dict:
    items, total = store.list_notes(
        q=q,
        category=category,
        category_id=categoryId,
        status=status,
        tag=tag,
        from_at=fromAt,
        to_at=toAt,
        page=page,
        size=size,
        sort=sort,
    )
    return {"items": items, "total": total, "page": page, "size": size}


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
def search(
    q: str,
    scope: Literal["all", "title_summary", "tags", "full_content"] = "all",
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
) -> dict:
    notes, _ = store.list_notes(page=1, size=5000)
    query = q.lower()
    matched: list[dict] = []

    for note in notes:
        title_summary_text = " ".join([note.get("aiTitle", ""), note.get("summaryShort", ""), note.get("summaryLong", "")]).lower()
        tags_text = " ".join([t["name"] for t in note.get("tags", [])] + [h["name"] for h in note.get("hashtags", [])]).lower()
        content_text = note.get("contentFull", "").lower()

        is_match = (
            (scope == "title_summary" and query in title_summary_text)
            or (scope == "tags" and query in tags_text)
            or (scope == "full_content" and query in content_text)
            or (scope == "all" and (query in title_summary_text or query in tags_text or query in content_text))
        )
        if is_match:
            matched.append({**note, "snippet": _snippet(note, q, scope)})

    start = (page - 1) * size
    end = start + size
    return {"scope": scope, "q": q, "items": matched[start:end], "total": len(matched), "page": page, "size": size}


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
    notes, _ = store.list_notes(page=1, size=5000)
    target_type = payload.target.get("type")

    if target_type == "category":
        category_name = payload.target.get("category")
        notes = [n for n in notes if (n.get("category") or {}).get("name") == category_name]
    elif target_type == "note_ids":
        note_ids = set(payload.target.get("noteIds", []))
        notes = [n for n in notes if n["id"] in note_ids]
    elif target_type == "date_range":
        from_iso = payload.target.get("from")
        to_iso = payload.target.get("to")
        if not from_iso or not to_iso:
            raise HTTPException(status_code=400, detail="invalid_date_range")
        start = datetime.fromisoformat(from_iso)
        end = datetime.fromisoformat(to_iso)
        notes = [n for n in notes if start <= datetime.fromisoformat(n["createdAt"]) <= end]

    markdown = payload.format == "markdown_zip"
    ext = "md" if markdown else "txt"

    buff = BytesIO()
    with ZipFile(buff, mode="w", compression=ZIP_DEFLATED) as zf:
        for note in notes:
            content = _render_note(note, payload.include, markdown=markdown)
            zf.writestr(f"note-{note['id']}.{ext}", content)

    export_id = f"exp_{int(datetime.now(UTC).timestamp())}"
    EXPORTS[export_id] = buff.getvalue()
    expires_at = (datetime.now(UTC) + timedelta(hours=config.export_ttl_hours)).isoformat()

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
    return {"items": store.list_categories()}


@app.post("/api/v1/categories")
def create_category(payload: CategoryCreateRequest) -> dict:
    return store.create_category(payload.name, color=payload.color)


@app.patch("/api/v1/categories")
def rename_category(payload: CategoryUpdateRequest) -> dict:
    updated = store.rename_category(payload.fromName, payload.toName, color=payload.color)
    if not updated:
        raise HTTPException(status_code=404, detail="category_not_found")
    return {"updated": True, "name": payload.toName}


@app.patch("/api/v1/categories/{category_id}")
def rename_category_by_id(category_id: int, payload: CategoryRenameByIdRequest) -> dict:
    updated = store.rename_category_by_id(category_id, payload.toName, color=payload.color)
    if not updated:
        raise HTTPException(status_code=404, detail="category_not_found")
    return {"updated": True, "id": category_id, "name": payload.toName}


@app.post("/api/v1/categories/merge")
def merge_categories(payload: CategoryMergeRequest) -> dict:
    merged_count = store.merge_categories(payload.sourceNames, payload.targetName)
    return {"targetName": payload.targetName, "mergedNoteCount": merged_count}


@app.get("/api/v1/tags")
def list_tags(limit: int = Query(20, ge=1, le=200)) -> dict:
    notes, _ = store.list_notes(page=1, size=5000)
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
