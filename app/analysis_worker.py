"""Simple worker skeleton for content analysis pipeline.

This module is intentionally lightweight and implementation-ready.
Replace stubs (`fetch_html`, `extract_main_content`, `analyze_with_llm`) with production adapters.
"""

from dataclasses import dataclass


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


def normalize_url(url: str) -> str:
    return url.split("?")[0]


def fetch_html(url: str) -> str:
    # TODO: requests/httpx with timeout, redirect policy, payload size cap
    return f"<html><body><article>Sample content from {url}</article></body></html>"


def extract_main_content(html: str) -> str:
    # TODO: readability-lxml / trafilatura fallback
    start = html.find("<article>")
    end = html.find("</article>")
    if start == -1 or end == -1:
        return ""
    return html[start + len("<article>") : end].strip()


def analyze_with_llm(content: str) -> AnalyzeResult:
    # TODO: integrate LLM provider with strict JSON schema validation
    return AnalyzeResult(
        ai_title="자동 생성 제목",
        summary_short=content[:80],
        summary_long=content[:300],
        tags=["요약", "노트"],
        hashtags=["#자동분석"],
        category="미분류",
        confidence=0.6,
        is_low_content=len(content) < 500,
    )


def process_url(url: str) -> dict:
    canonical = normalize_url(url)
    html = fetch_html(canonical)
    content = extract_main_content(html)
    if not content:
        return {"status": "extract_failed", "url": canonical}

    result = analyze_with_llm(content)
    if result.is_low_content:
        status = "partial_done"
    else:
        status = "done"

    return {
        "status": status,
        "sourceUrl": canonical,
        "contentFull": content,
        "aiTitle": result.ai_title,
        "summaryShort": result.summary_short,
        "summaryLong": result.summary_long,
        "tags": result.tags,
        "hashtags": result.hashtags,
        "category": result.category,
        "confidence": result.confidence,
    }
