from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app.app_state import job_runner, store
from app.kakaotalk_parser import parse_urls_csv_bytes

router = APIRouter()


class TagPayload(BaseModel):
    name: str
    type: Literal["tag", "hashtag"] = "tag"


class NoteBatchPatchRequest(BaseModel):
    noteIds: list[int] = Field(min_length=1)
    category: str | None = None
    tags: list[TagPayload] | None = None


def _snippet(note: dict[str, Any], q: str, scope: str) -> str:
    target = ""
    if scope in {"all", "title_summary"}:
        target = " ".join(
            [
                note.get("aiTitle", ""),
                note.get("summaryShort", ""),
                note.get("summaryLong", ""),
            ]
        )
    if not target and scope in {"all", "tags"}:
        target = " ".join(
            [t["name"] for t in note.get("tags", [])]
            + [h["name"] for h in note.get("hashtags", [])]
        )
    if not target and scope in {"all", "full_content"}:
        target = note.get("contentFull", "")

    lowered = target.lower()
    idx = lowered.find(q.lower())
    if idx == -1:
        return target[:180]
    start = max(0, idx - 60)
    end = min(len(target), idx + 120)
    return target[start:end]


@router.patch("/api/v1/notes/batch")
def patch_notes_batch(payload: NoteBatchPatchRequest) -> dict[str, object]:
    patch = payload.model_dump(exclude_unset=True)
    note_ids = patch.pop("noteIds")
    if "category" not in patch and "tags" not in patch:
        raise HTTPException(status_code=400, detail="missing_patch_fields")
    return store.batch_update_note_metadata(note_ids, patch)


@router.post("/api/v1/import/urls-csv")
async def import_urls_csv(
    file: UploadFile = File(..., description="URL 목록 CSV 파일"),
    skip_duplicates: bool = Query(
        True, description="동일 sourceUrl 노트가 있으면 스킵"
    ),
    summary_length: Literal["short", "standard"] = Query(
        "standard", alias="summaryLength"
    ),
    auto_category: bool = Query(True, alias="autoCategory"),
    store_full_content: bool = Query(True, alias="storeFullContent"),
) -> dict[str, object]:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="CSV 파일만 업로드할 수 있습니다.")
    try:
        content = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"파일 읽기 실패: {e}") from e

    try:
        urls = parse_urls_csv_bytes(content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"CSV 파싱 실패: {e}") from e

    if not urls:
        return {
            "jobId": None,
            "requestedCount": 0,
            "queuedCount": 0,
            "skipped": 0,
            "status": "empty",
        }

    queued_urls = []
    skipped = 0
    for url in urls:
        if skip_duplicates and store.get_note_by_source_url(url):
            skipped += 1
            continue
        queued_urls.append(url)

    if not queued_urls:
        return {
            "jobId": None,
            "requestedCount": len(urls),
            "queuedCount": 0,
            "skipped": skipped,
            "status": "empty",
        }

    options = {
        "summaryLength": summary_length,
        "autoCategory": auto_category,
        "storeFullContent": store_full_content,
    }
    job_id = store.create_job(queued_urls, options=options)
    job_runner.enqueue(job_id, store)
    return {
        "jobId": job_id,
        "requestedCount": len(urls),
        "queuedCount": len(queued_urls),
        "skipped": skipped,
        "status": "queued",
    }


@router.get("/api/v1/search")
def search(
    q: str,
    scope: Literal["all", "title_summary", "tags", "full_content"] = "all",
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
) -> dict[str, object]:
    notes, total = store.list_notes(q=q, q_scope=scope, page=page, size=size)
    items = [{**note, "snippet": _snippet(note, q, scope)} for note in notes]
    return {
        "scope": scope,
        "q": q,
        "items": items,
        "total": total,
        "page": page,
        "size": size,
    }
