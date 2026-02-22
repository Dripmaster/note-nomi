"""카카오톡 '나에게 보내기' 채팅 CSV 파싱 및 노트 변환."""

from __future__ import annotations

import csv
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import BinaryIO


# 카카오톡 내보내기 CSV 컬럼: Date, User, Message
KAKAOTALK_CSV_COLUMNS = ("Date", "User", "Message")


def parse_datetime(date_str: str) -> str | None:
    """'2025-07-06 14:39:55' 형태를 ISO 형식으로 변환."""
    date_str = (date_str or "").strip()
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.isoformat()
        except ValueError:
            continue
    return None


def _read_rows(reader: csv.DictReader) -> list[dict]:
    rows: list[dict] = []
    for row in reader:
        normalized = {k.strip(): v for k, v in row.items()}
        date_raw = normalized.get("Date", "")
        user = (normalized.get("User") or "").strip()
        message = (normalized.get("Message") or "").strip()
        if not message:
            continue
        iso_date = parse_datetime(date_raw)
        rows.append({
            "date": iso_date or datetime.now().isoformat(),
            "user": user,
            "message": message,
        })
    return rows


def parse_csv(path: str | Path) -> list[dict]:
    """
    카카오톡 채팅 CSV 파일을 파싱해 행 목록 반환.
    각 항목: {"date": "2025-07-06T14:39:55", "user": "손영민", "message": "..."}
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(str(path))
    with path.open(encoding="utf-8-sig", newline="") as f:
        return _read_rows(csv.DictReader(f))


def parse_csv_bytes(content: bytes | BinaryIO) -> list[dict]:
    """업로드된 CSV 바이트 또는 파일 객체를 파싱해 행 목록 반환."""
    if isinstance(content, bytes):
        text = content.decode("utf-8-sig")
    else:
        text = content.read().decode("utf-8-sig")
    return _read_rows(csv.DictReader(StringIO(text)))


def row_to_note(row: dict, index: int, category: str = "카카오톡 나에게보내기") -> dict:
    """
    파싱된 한 행을 note-nomi 노트 딕셔너리로 변환.
    sourceUrl로 중복 여부 판별 가능 (같은 CSV 재업로드 시 스킵용).
    """
    date = row.get("date", "")
    message = row.get("message", "")
    # 동일 초에 여러 건일 수 있어 index 포함
    source_url = f"kakaotalk://me/{date}_{index}"
    # 제목은 첫 줄 또는 앞 50자
    first_line = message.split("\n")[0].strip() if message else ""
    ai_title = (first_line[:50] + "…") if len(first_line) > 50 else first_line or "(메모)"
    return {
        "sourceUrl": source_url,
        "aiTitle": ai_title,
        "summaryShort": "",
        "summaryLong": "",
        "contentFull": message,
        "category": category,
        "tags": [],
        "hashtags": [],
        "status": "done",
        "createdAt": date,
        "updatedAt": date,
    }
