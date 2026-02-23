from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TypedDict
from urllib.parse import urlparse

KIND_ORDER = (
    "plain_text",
    "youtube",
    "instagram_post",
    "instagram_reel",
    "threads",
    "other_link",
)

_KIND_RANK = {kind: idx for idx, kind in enumerate(KIND_ORDER)}
_HTTP_SCHEMES = {"http", "https"}
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
_URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", flags=re.IGNORECASE)
_TRAILING_PUNCTUATION = ").,!?]}"
_MAX_SCAN_CHARS = 50_000
_MAX_URLS = 50


class NoteKindsResult(TypedDict):
    primary_kind: str
    kinds: list[str]


def _is_instagram_host(host: str) -> bool:
    return host.endswith("instagram.com") or host == "instagr.am"


def _ordered_unique(kinds: set[str]) -> list[str]:
    return sorted(kinds, key=lambda kind: _KIND_RANK.get(kind, len(KIND_ORDER)))


def extract_urls(text: str) -> list[str]:
    scanned = text[:_MAX_SCAN_CHARS]
    urls: list[str] = []
    for match in _URL_PATTERN.finditer(scanned):
        candidate = match.group(0).rstrip(_TRAILING_PUNCTUATION)
        if not candidate:
            continue
        urls.append(candidate)
        if len(urls) >= _MAX_URLS:
            break
    return urls


def classify_url(url: str) -> str:
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in _HTTP_SCHEMES:
        return "plain_text"

    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()

    if host in _YOUTUBE_HOSTS:
        return "youtube"
    if _is_instagram_host(host) and ("/reel/" in path or "/reels/" in path):
        return "instagram_reel"
    if _is_instagram_host(host) and ("/p/" in path or "/tv/" in path):
        return "instagram_post"
    if host.endswith("threads.net") and "/post/" in path:
        return "threads"
    return "other_link"


def _read_note_field(note_dict: Mapping[str, object], key: str) -> str:
    value = note_dict.get(key)
    if value is None:
        return ""
    return str(value)


def compute_note_kinds(note_dict: Mapping[str, object]) -> NoteKindsResult:
    source_url = _read_note_field(note_dict, "sourceUrl")
    source_scheme = (urlparse(source_url).scheme or "").lower()
    primary_kind = "plain_text"
    if source_scheme in _HTTP_SCHEMES:
        primary_kind = classify_url(source_url)

    text_to_scan = "\n".join(
        _read_note_field(note_dict, key)
        for key in ("sourceUrl", "contentFull", "summaryShort", "summaryLong")
    )
    extracted_urls = extract_urls(text_to_scan)

    kinds = {primary_kind}
    for url in extracted_urls:
        kinds.add(classify_url(url))

    return {"primary_kind": primary_kind, "kinds": _ordered_unique(kinds)}
