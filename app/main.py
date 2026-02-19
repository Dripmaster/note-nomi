from datetime import datetime
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Note Nomi API", version="0.1.0")


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
    categoryId: int | None = None
    tags: list[TagPayload] | None = None


JOBS: dict[int, dict] = {}
NOTES: dict[int, dict] = {}
JOB_COUNTER = 100
NOTE_COUNTER = 1000


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/ingestions")
def create_ingestion(payload: IngestionCreateRequest) -> dict:
    global JOB_COUNTER
    JOB_COUNTER += 1
    JOBS[JOB_COUNTER] = {
        "jobId": JOB_COUNTER,
        "requestedCount": len(payload.urls),
        "counts": {"queued": len(payload.urls), "processing": 0, "done": 0, "failed": 0},
        "items": [{"sourceUrl": url, "status": "queued", "noteId": None} for url in payload.urls],
        "options": payload.options.model_dump(),
        "createdAt": datetime.utcnow().isoformat(),
    }
    return {"jobId": JOB_COUNTER, "requestedCount": len(payload.urls), "status": "queued"}


@app.get("/api/v1/ingestions/{job_id}")
def get_ingestion(job_id: int) -> dict:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job_not_found")
    return {"jobId": job_id, "counts": job["counts"], "items": job["items"]}


@app.post("/api/v1/ingestions/{job_id}/retry")
def retry_ingestion(job_id: int) -> dict:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job_not_found")
    retried = 0
    for item in job["items"]:
        if item["status"] == "failed":
            item["status"] = "queued"
            retried += 1
    job["counts"]["queued"] += retried
    job["counts"]["failed"] = max(0, job["counts"]["failed"] - retried)
    return {"jobId": job_id, "retried": retried}


@app.get("/api/v1/notes")
def list_notes(q: str | None = None, categoryId: int | None = None, status: str | None = None) -> dict:
    notes = list(NOTES.values())
    if q:
        notes = [n for n in notes if q.lower() in (n.get("aiTitle") or "").lower() or q.lower() in (n.get("contentFull") or "").lower()]
    if categoryId is not None:
        notes = [n for n in notes if (n.get("category") or {}).get("id") == categoryId]
    if status:
        notes = [n for n in notes if n.get("status") == status]
    return {"items": notes, "total": len(notes)}


@app.get("/api/v1/notes/{note_id}")
def get_note(note_id: int) -> dict:
    note = NOTES.get(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="note_not_found")
    return note


@app.patch("/api/v1/notes/{note_id}")
def patch_note(note_id: int, payload: NotePatchRequest) -> dict:
    note = NOTES.get(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="note_not_found")
    patch_data = payload.model_dump(exclude_none=True)
    for key, value in patch_data.items():
        note[key] = value
    note["updatedAt"] = datetime.utcnow().isoformat()
    return note


@app.delete("/api/v1/notes/{note_id}")
def delete_note(note_id: int) -> dict:
    if note_id not in NOTES:
        raise HTTPException(status_code=404, detail="note_not_found")
    del NOTES[note_id]
    return {"deleted": True, "noteId": note_id}


@app.get("/api/v1/search")
def search(q: str, scope: Literal["all", "title_summary", "tags", "full_content"] = "all") -> dict:
    matched = []
    for note in NOTES.values():
        text = " ".join(
            [
                note.get("aiTitle", ""),
                note.get("summaryShort", ""),
                note.get("summaryLong", ""),
                note.get("contentFull", ""),
            ]
        ).lower()
        if q.lower() in text:
            matched.append(note)
    return {"scope": scope, "q": q, "items": matched, "total": len(matched)}


class ExportRequest(BaseModel):
    target: dict
    format: Literal["markdown_zip", "text_zip"] = "markdown_zip"
    include: dict


@app.post("/api/v1/exports/notebooklm")
def export_notebooklm(payload: ExportRequest) -> dict:
    export_id = f"exp_{int(datetime.utcnow().timestamp())}"
    return {
        "exportId": export_id,
        "downloadUrl": f"/api/v1/exports/{export_id}/download",
        "expiresAt": datetime.utcnow().isoformat(),
        "target": payload.target,
    }
