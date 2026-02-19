from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from app.config import get_config

_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "have",
    "about",
    "your",
    "you",
    "are",
    "was",
    "were",
    "있다",
    "하다",
    "그리고",
    "에서",
    "으로",
    "대한",
    "하는",
    "있는",
    "입니다",
}

_TRACKING_QUERY_KEYS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid", "fbclid"}

_CATEGORY_KEYWORDS = {
    "개발": {"python", "api", "fastapi", "database", "sqlite", "코드", "개발", "프로그래밍", "backend", "server"},
    "AI": {"ai", "llm", "model", "prompt", "inference", "machine", "learning", "인공지능"},
    "생산성": {"work", "note", "workflow", "task", "productivity", "정리", "생산성", "업무"},
}


@dataclass
class AnalyzeResult:
    ai_title: str
    summary_short: str
    summary_long: str
    tags: list[str]
    hashtags: list[str]
    category: str
    confidence: float
    is_low_content: bool


class _ReadableTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._buf: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip:
            text = data.strip()
            if text:
                self._buf.append(text)

    @property
    def text(self) -> str:
        return " ".join(self._buf)


def normalize_url(url: str) -> str:
    parsed = urlsplit(url)
    query_pairs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k.lower() not in _TRACKING_QUERY_KEYS]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query_pairs), ""))


def fetch_html(url: str) -> str:
    config = get_config()
    req = Request(url, headers={"User-Agent": "note-nomi/0.6"})
    with urlopen(req, timeout=config.http_timeout_sec) as response:
        content_type = (response.headers.get("Content-Type") or "").lower()
        if "text/html" not in content_type:
            raise RuntimeError("fetch_failed")
        raw = response.read(config.http_max_bytes + 1)
        if len(raw) > config.http_max_bytes:
            raise RuntimeError("fetch_failed")
        return raw.decode(response.headers.get_content_charset("utf-8"), errors="replace")


def extract_main_content(html: str) -> str:
    for tag in ("article", "main", "body"):
        match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", html, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        p = _ReadableTextParser()
        p.feed(match.group(1))
        t = p.text.strip()
        if t:
            return t
    p = _ReadableTextParser()
    p.feed(html)
    return p.text.strip()


def _sentences(text: str) -> list[str]:
    return [chunk.strip() for chunk in re.split(r"(?<=[.!?。！？])\s+|\n+", text) if chunk.strip()]


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\w가-힣]{2,}", text.lower())


def _top_keywords(text: str, limit: int = 5) -> list[str]:
    return [w for w, _ in Counter([t for t in _tokens(text) if t not in _STOPWORDS]).most_common(limit)]


def _infer_category(text: str, enabled: bool) -> str:
    if not enabled:
        return get_config().default_category
    lowered = text.lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(k in lowered for k in keywords):
            return category
    return get_config().default_category


def _extractive_summary(text: str, sentence_count: int) -> str:
    sents = _sentences(text)
    if not sents:
        return ""
    ww = Counter(_top_keywords(text, limit=20))
    scored: list[tuple[int, float, str]] = []
    for idx, sent in enumerate(sents):
        toks = [tok for tok in _tokens(sent) if tok not in _STOPWORDS]
        if toks:
            score = sum(ww.get(tok, 0) for tok in toks) * (1 / (1 + math.log(max(10, len(toks)))))
            scored.append((idx, score, sent))
    if not scored:
        return " ".join(sents[:sentence_count])
    top = sorted(scored, key=lambda x: x[1], reverse=True)[:sentence_count]
    return " ".join(s for _, _, s in sorted(top, key=lambda x: x[0]))


def _heuristic_analysis(content: str, options: dict | None = None) -> AnalyzeResult:
    opts = options or {}
    summary_len = opts.get("summaryLength", "standard")
    summary_short = _extractive_summary(content, 1)[:180]
    summary_long = _extractive_summary(content, 2 if summary_len == "short" else 4)[:700]
    tags = _top_keywords(content, 4)[:3]
    hashtags = [f"#{t}" for t in tags[:2]]
    ai_title = " · ".join(tags[:2]) if tags else ((_sentences(content) or [content])[0][:40] or "제목 없음")
    category = _infer_category(content, enabled=bool(opts.get("autoCategory", True)))
    confidence = min(0.99, 0.35 + (len(set(_tokens(content))) / 120))
    return AnalyzeResult(ai_title, summary_short, summary_long, tags, hashtags, category, round(confidence, 2), len(content) < 120)


def _analyze_with_internal_codex(content: str, options: dict | None = None) -> AnalyzeResult:
    cfg = get_config()
    if not cfg.llm_base_url or not cfg.llm_api_key:
        raise RuntimeError("llm_config_missing")

    payload = {
        "model": cfg.llm_model,
        "messages": [
            {
                "role": "system",
                "content": "Return strict JSON with keys: aiTitle, summaryShort, summaryLong, tags(array), hashtags(array), category, confidence(0~1), isLowContent(boolean).",
            },
            {"role": "user", "content": content[:8000]},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    req = Request(
        f"{cfg.llm_base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {cfg.llm_api_key}"},
        method="POST",
    )
    with urlopen(req, timeout=cfg.llm_timeout_sec) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
    content_raw = raw["choices"][0]["message"]["content"]
    obj = json.loads(content_raw)

    tags = [str(t) for t in obj.get("tags", [])][:5]
    hashtags = [str(h) for h in obj.get("hashtags", [])][:5]
    return AnalyzeResult(
        ai_title=str(obj.get("aiTitle", "제목 없음")),
        summary_short=str(obj.get("summaryShort", ""))[:180],
        summary_long=str(obj.get("summaryLong", ""))[:700],
        tags=tags,
        hashtags=hashtags,
        category=str(obj.get("category", get_config().default_category)),
        confidence=float(obj.get("confidence", 0.5)),
        is_low_content=bool(obj.get("isLowContent", len(content) < 120)),
    )


def analyze_with_llm(content: str, options: dict | None = None) -> AnalyzeResult:
    provider = get_config().llm_provider.lower()
    if provider == "internal_codex":
        return _analyze_with_internal_codex(content, options=options)
    return _heuristic_analysis(content, options=options)


def process_url(url: str, options: dict | None = None) -> dict:
    canonical = normalize_url(url)
    try:
        html = fetch_html(canonical)
    except Exception:
        return {"status": "fetch_failed", "sourceUrl": canonical, "errorMessage": "fetch failed"}

    content = extract_main_content(html)
    if not content:
        return {"status": "extract_failed", "sourceUrl": canonical, "errorMessage": "extract failed"}

    try:
        result = analyze_with_llm(content, options=options)
    except Exception:
        return {
            "status": "partial_done",
            "sourceUrl": canonical,
            "contentFull": content,
            "aiTitle": "",
            "summaryShort": "",
            "summaryLong": "",
            "tags": [],
            "hashtags": [],
            "category": get_config().default_category,
            "confidence": 0.0,
            "errorMessage": "analyze failed",
        }

    opts = options or {}
    return {
        "status": "partial_done" if result.is_low_content else "done",
        "sourceUrl": canonical,
        "contentFull": content if opts.get("storeFullContent", True) else "",
        "aiTitle": result.ai_title,
        "summaryShort": result.summary_short,
        "summaryLong": result.summary_long,
        "tags": result.tags,
        "hashtags": result.hashtags,
        "category": result.category,
        "confidence": result.confidence,
    }
