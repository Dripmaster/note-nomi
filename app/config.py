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
    llm_model: str
    llm_timeout_sec: float
    codex_cli_command: str
    codex_cli_args: str
    instagram_browser: str
    browser_user_data_dir: str | None
    browser_timeout_sec: float
    instagram_username: str | None
    instagram_password: str | None
    instagram_session_path: str


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


def _normalize_browser_user_data_dir(raw: str | None) -> str | None:
    if not raw or not (v := raw.strip()):
        return None
    return os.path.expanduser(v)


def _instagram_session_path() -> str:
    base = os.getenv("NOTE_NOMI_DB_PATH", "data/note_nomi.db")
    dir_path = os.path.dirname(os.path.abspath(os.path.expanduser(base)))
    return os.path.join(dir_path, "instagram_session.json")


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
        llm_model=os.getenv("NOTE_NOMI_LLM_MODEL", "gpt-5.2-codex"),
        llm_timeout_sec=_get_float("NOTE_NOMI_LLM_TIMEOUT_SEC", 20.0),
        codex_cli_command=os.getenv("NOTE_NOMI_CODEX_CLI_COMMAND", "codex"),
        codex_cli_args=os.getenv("NOTE_NOMI_CODEX_CLI_ARGS", ""),
        instagram_browser=(os.getenv("NOTE_NOMI_INSTAGRAM_BROWSER") or "").strip().lower(),
        browser_user_data_dir=_normalize_browser_user_data_dir(
            os.getenv("NOTE_NOMI_BROWSER_USER_DATA_DIR") or None
        ),
        browser_timeout_sec=_get_float("NOTE_NOMI_BROWSER_TIMEOUT_SEC", 25.0),
        instagram_username=(os.getenv("NOTE_NOMI_INSTAGRAM_USERNAME") or "").strip() or None,
        instagram_password=os.getenv("NOTE_NOMI_INSTAGRAM_PASSWORD") or None,
        instagram_session_path=_instagram_session_path(),
    )
