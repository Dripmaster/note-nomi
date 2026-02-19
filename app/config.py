from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    db_path: str
    http_timeout_sec: float
    http_max_bytes: int
    default_category: str
    export_ttl_hours: int
    llm_provider: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_timeout_sec: float


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue

        key, value = raw.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _get_float(name: str, default: float) -> float:
    val = os.getenv(name)
    if val is None:
        return default
    try:
        return float(val)
    except ValueError as exc:
        raise ValueError(f"{name} must be a float") from exc


def _get_int(name: str, default: int) -> int:
    val = os.getenv(name)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    _load_dotenv(Path(".env"))

    return AppConfig(
        db_path=os.getenv("NOTE_NOMI_DB_PATH", "data/note_nomi.db"),
        http_timeout_sec=_get_float("NOTE_NOMI_HTTP_TIMEOUT_SEC", 8.0),
        http_max_bytes=_get_int("NOTE_NOMI_HTTP_MAX_BYTES", 2_000_000),
        default_category=os.getenv("NOTE_NOMI_DEFAULT_CATEGORY", "미분류"),
        export_ttl_hours=_get_int("NOTE_NOMI_EXPORT_TTL_HOURS", 1),
        llm_provider=os.getenv("NOTE_NOMI_LLM_PROVIDER", "heuristic"),
        llm_base_url=os.getenv("NOTE_NOMI_LLM_BASE_URL", ""),
        llm_api_key=os.getenv("NOTE_NOMI_LLM_API_KEY", ""),
        llm_model=os.getenv("NOTE_NOMI_LLM_MODEL", "gpt-5.2-codex"),
        llm_timeout_sec=_get_float("NOTE_NOMI_LLM_TIMEOUT_SEC", 20.0),
    )
