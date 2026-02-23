from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any, Literal
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import FastAPI, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.app_state import config, job_runner, store
from app.extra_routes import router as extra_router
from app.kakaotalk_parser import parse_csv_bytes, row_to_note
from app.note_kinds import KIND_ORDER

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)
app = FastAPI(title="Note Nomi API", version="0.5.0")
EXPORTS: dict[str, bytes] = {}
app.include_router(extra_router)


def _env_flag_enabled(name: str, default: bool = True) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off"}


@app.on_event("startup")
def startup_backfill_note_kinds() -> None:
    if not _env_flag_enabled("NOTE_NOMI_BACKFILL_KINDS_ON_STARTUP", default=True):
        return
    result = store.backfill_note_kinds()
    logger.info("note kinds backfill updated=%s", result["updated"])


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
    target: dict[str, Any]
    format: Literal["markdown_zip", "text_zip"] = "markdown_zip"
    include: dict[str, Any]


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


def _parse_iso_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


@app.get("/")
def home() -> FileResponse:
    return FileResponse("app/static/index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/ingestions")
def create_ingestion(payload: IngestionCreateRequest) -> dict[str, object]:
    options = payload.options.model_dump()
    job_id = store.create_job(payload.urls, options=options)
    job_runner.enqueue(job_id, store)
    return {"jobId": job_id, "requestedCount": len(payload.urls), "status": "queued"}


@app.get("/api/v1/ingestions/{job_id}")
def get_ingestion(job_id: int) -> dict[str, object]:
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job_not_found")
    return job


@app.post("/api/v1/ingestions/{job_id}/retry")
def retry_ingestion(job_id: int) -> dict[str, object]:
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
    kind: str | None = None,
    status: str | None = None,
    tag: str | None = None,
    fromAt: str | None = None,
    toAt: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    sort: Literal[
        "created_desc", "created_asc", "updated_desc", "updated_asc"
    ] = "created_desc",
) -> dict[str, object]:
    if kind and kind not in KIND_ORDER:
        raise HTTPException(status_code=400, detail="invalid_kind")
    items, total = store.list_notes(
        q=q,
        category=category,
        category_id=categoryId,
        kind=kind,
        status=status,
        tag=tag,
        from_at=fromAt,
        to_at=toAt,
        page=page,
        size=size,
        sort=sort,
    )
    return {"items": items, "total": total, "page": page, "size": size}


@app.get("/api/v1/note-kinds")
def count_note_kinds(
    q: str | None = None,
    category: str | None = None,
    categoryId: int | None = None,
    status: str | None = None,
    tag: str | None = None,
    fromAt: str | None = None,
    toAt: str | None = None,
) -> dict[str, object]:
    items, total_notes = store.count_note_kinds(
        q=q,
        category=category,
        category_id=categoryId,
        status=status,
        tag=tag,
        from_at=fromAt,
        to_at=toAt,
    )
    return {"items": items, "totalNotes": total_notes}


@app.get("/api/v1/tags")
def list_tags() -> dict[str, object]:
    """노트에서 사용 중인 태그/해시태그 목록 (이름, 노트 개수)."""
    return {"items": store.list_tags()}


@app.delete("/api/v1/notes")
def reset_notes(
    all: bool = Query(False, description="true면 전체 메모 삭제(초기화)"),
) -> dict[str, object]:
    """전체 메모 삭제. all=true 쿼리 필수."""
    if not all:
        raise HTTPException(
            status_code=400, detail="전체 삭제 시 all=true 쿼리를 보내주세요."
        )
    deleted = store.delete_all_notes()
    return {"deleted": deleted, "message": "전체 메모가 삭제되었습니다."}


@app.get("/api/v1/notes/{note_id}")
def get_note(note_id: int) -> dict[str, object]:
    note = store.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="note_not_found")
    return note


@app.patch("/api/v1/notes/{note_id}")
def patch_note(note_id: int, payload: NotePatchRequest) -> dict[str, object]:
    note = store.update_note(note_id, payload.model_dump(exclude_none=True))
    if not note:
        raise HTTPException(status_code=404, detail="note_not_found")
    return note


@app.delete("/api/v1/notes/{note_id}")
def delete_note(note_id: int) -> dict[str, object]:
    deleted = store.delete_note(note_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="note_not_found")
    return {"deleted": True, "noteId": note_id}


@app.post("/api/v1/import/kakaotalk")
async def import_kakaotalk(
    file: UploadFile = File(..., description="카카오톡 나에게 보내기 채팅 CSV 파일"),
    skip_duplicates: bool = Query(
        True, description="동일 sourceUrl 노트가 있으면 스킵"
    ),
    category: str = Query("카카오톡 나에게보내기", description="등록할 메모 카테고리"),
) -> dict[str, object]:
    """카카오톡 '나에게 보내기' CSV를 파싱해 메모(노트)로 일괄 등록."""
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="CSV 파일만 업로드할 수 있습니다.")
    try:
        content = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"파일 읽기 실패: {e}") from e
    try:
        rows = parse_csv_bytes(content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"CSV 파싱 실패: {e}") from e
    if not rows:
        return {"imported": 0, "skipped": 0, "total": 0, "noteIds": []}
    imported = 0
    skipped = 0
    note_ids: list[int] = []
    for i, row in enumerate(rows):
        note = row_to_note(row, index=i, category=category)
        if skip_duplicates and store.get_note_by_source_url(note["sourceUrl"]):
            skipped += 1
            continue
        note_id = store.create_note(note)
        imported += 1
        note_ids.append(note_id)
    return {
        "imported": imported,
        "skipped": skipped,
        "total": len(rows),
        "noteIds": note_ids,
    }


def _render_note(note: dict[str, Any], include: dict[str, Any], markdown: bool) -> str:
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
    add(
        "Summary Short",
        note.get("summaryShort") if include.get("summaryShort", True) else None,
    )
    add(
        "Summary Long",
        note.get("summaryLong") if include.get("summaryLong", True) else None,
    )
    if include.get("tags", True):
        tag_text = ", ".join(
            [t["name"] for t in note.get("tags", [])]
            + [h["name"] for h in note.get("hashtags", [])]
        )
        add("Tags", tag_text)
    add(
        "Content Full",
        note.get("contentFull") if include.get("contentFull", True) else None,
    )

    return "\n".join(lines).strip() + "\n"


@app.post("/api/v1/exports/notebooklm")
def export_notebooklm(payload: ExportRequest) -> dict[str, object]:
    notes, _ = store.list_notes(page=1, size=5000)
    target_type = payload.target.get("type")

    if target_type == "category":
        category_name = payload.target.get("category")
        notes = [
            n for n in notes if (n.get("category") or {}).get("name") == category_name
        ]
    elif target_type == "note_ids":
        note_ids = set(payload.target.get("noteIds", []))
        notes = [n for n in notes if n["id"] in note_ids]
    elif target_type == "date_range":
        from_iso = payload.target.get("from")
        to_iso = payload.target.get("to")
        if not from_iso or not to_iso:
            raise HTTPException(status_code=400, detail="invalid_date_range")
        try:
            start = _parse_iso_utc(from_iso)
            end = _parse_iso_utc(to_iso)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid_date_range") from exc
        notes = [n for n in notes if start <= _parse_iso_utc(n["createdAt"]) <= end]

    markdown = payload.format == "markdown_zip"
    ext = "md" if markdown else "txt"

    buff = BytesIO()
    with ZipFile(buff, mode="w", compression=ZIP_DEFLATED) as zf:
        for note in notes:
            content = _render_note(note, payload.include, markdown=markdown)
            zf.writestr(f"note-{note['id']}.{ext}", content)

    export_id = f"exp_{int(datetime.now(UTC).timestamp())}"
    EXPORTS[export_id] = buff.getvalue()
    expires_at = (
        datetime.now(UTC) + timedelta(hours=config.export_ttl_hours)
    ).isoformat()

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
def list_categories() -> dict[str, object]:
    return {"items": store.list_categories()}


@app.post("/api/v1/categories")
def create_category(payload: CategoryCreateRequest) -> dict[str, object]:
    return store.create_category(payload.name, color=payload.color)


@app.patch("/api/v1/categories")
def rename_category(payload: CategoryUpdateRequest) -> dict[str, object]:
    updated = store.rename_category(
        payload.fromName, payload.toName, color=payload.color
    )
    if not updated:
        raise HTTPException(status_code=404, detail="category_not_found")
    return {"updated": True, "name": payload.toName}


@app.patch("/api/v1/categories/{category_id}")
def rename_category_by_id(
    category_id: int, payload: CategoryRenameByIdRequest
) -> dict[str, object]:
    updated = store.rename_category_by_id(
        category_id, payload.toName, color=payload.color
    )
    if not updated:
        raise HTTPException(status_code=404, detail="category_not_found")
    return {"updated": True, "id": category_id, "name": payload.toName}


@app.post("/api/v1/categories/merge")
def merge_categories(payload: CategoryMergeRequest) -> dict[str, object]:
    merged_count = store.merge_categories(payload.sourceNames, payload.targetName)
    return {"targetName": payload.targetName, "mergedNoteCount": merged_count}
