from __future__ import annotations

import json
import logging
import math
import os
import re
import shlex
import subprocess
from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from app.config import get_config

logger = logging.getLogger(__name__)

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


def _is_instagram_url(url: str) -> bool:
    parsed = urlsplit(url)
    netloc = (parsed.netloc or "").lower()
    return "instagram.com" in netloc and parsed.path and parsed.path.strip("/")


def fetch_html(url: str) -> str:
    config = get_config()
    headers = {"User-Agent": "note-nomi/0.7"}
    if _is_instagram_url(url):
        headers["User-Agent"] = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    req = Request(url, headers=headers)
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


def _extract_og_meta(html: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for name in ("og:title", "og:description"):
        match = re.search(
            rf'<meta\s+property=["\']{re.escape(name)}["\']\s+content=["\']([^"\']*)["\']',
            html,
            re.IGNORECASE,
        )
        if match:
            out[name] = match.group(1).strip()
    return out


def _instagram_login_and_save_session(page, config, timeout_ms: int) -> None:
    """인스타 로그인 페이지에서 아이디/비밀번호 입력 후 로그인하고, 성공 시 세션을 저장한다."""
    login_url = "https://www.instagram.com/accounts/login/"
    page.goto(login_url, wait_until="domcontentloaded", timeout=timeout_ms)
    page.wait_for_load_state("networkidle", timeout=timeout_ms)

    username = (config.instagram_username or "").strip()
    password = config.instagram_password or ""
    if not username or not password:
        raise RuntimeError("Instagram credentials not set")

    uname_el = page.locator('input[name="username"]').first
    uname_el.wait_for(state="visible", timeout=10000)
    uname_el.fill(username)
    pwd_el = page.locator('input[name="password"]').first
    pwd_el.wait_for(state="visible", timeout=5000)
    pwd_el.fill(password)
    page.locator('button[type="submit"]').first.click()
    page.wait_for_url(lambda u: "accounts/login" not in u.url, timeout=15000)
    page.wait_for_load_state("domcontentloaded", timeout=10000)
    if "challenge" in page.url or "checkpoint" in page.url:
        logger.warning("Instagram: login may require checkpoint/challenge (2FA or verify). Session not saved.")
        return
    logger.info("Instagram: login ok, saving session")
    path = config.instagram_session_path
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    page.context.storage_state(path=path)


def fetch_instagram_via_browser(url: str) -> str:
    """Playwright로 인스타그램 포스트 페이지를 열고 캡션 텍스트를 추출한다.
    NOTE_NOMI_INSTAGRAM_BROWSER=playwright 일 때만 호출. 아이디/비밀번호가 있으면 로그인 후 세션 저장해 재사용(프로필 미사용). 없으면 프로필 경로 또는 비로그인 Chromium 사용.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError("playwright not installed; pip install playwright && playwright install chromium") from e

    config = get_config()
    timeout_ms = int(config.browser_timeout_sec * 1000)
    use_credentials = bool((config.instagram_username or "").strip() and config.instagram_password)
    user_data_dir = (config.browser_user_data_dir or "").strip() or None

    if user_data_dir and not use_credentials:
        resolved = user_data_dir
        if not os.path.isdir(resolved):
            parent = os.path.dirname(resolved)
            if parent and parent != resolved and os.path.isdir(parent) and os.access(parent, os.R_OK | os.W_OK):
                resolved = parent
                logger.info("Instagram Playwright: using Chrome user data parent dir (use Default profile): %s", resolved)
            else:
                raise RuntimeError(
                    f"NOTE_NOMI_BROWSER_USER_DATA_DIR does not exist or is not a directory: {user_data_dir}"
                )
        elif not os.access(resolved, os.R_OK | os.W_OK):
            raise RuntimeError(
                f"NOTE_NOMI_BROWSER_USER_DATA_DIR not readable/writable by current user: {resolved}"
            )
        user_data_dir = resolved
    else:
        user_data_dir = None

    with sync_playwright() as p:
        if user_data_dir:
            context = p.chromium.launch_persistent_context(
                user_data_dir,
                channel="chrome",
                headless=True,
                timeout=timeout_ms,
            )
            browser = None
        else:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context()

        try:
            if use_credentials:
                session_path = config.instagram_session_path
                if browser:
                    context.close()
                if os.path.isfile(session_path):
                    context = browser.new_context(storage_state=session_path)
                    page = context.new_page()
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    if "accounts/login" in page.url or "challenge" in page.url or "checkpoint" in page.url:
                        context.close()
                        context = browser.new_context()
                        page = context.new_page()
                        _instagram_login_and_save_session(page, config, timeout_ms)
                        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                else:
                    context = browser.new_context()
                    page = context.new_page()
                    _instagram_login_and_save_session(page, config, timeout_ms)
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            else:
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

            page.wait_for_selector("article", timeout=timeout_ms)
            text = page.locator("article").first.inner_text(timeout=5000)
            text = (text or "").strip()
            if not text:
                raise RuntimeError("fetch_failed")
            return text
        finally:
            if browser:
                browser.close()
            else:
                context.close()


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


def _extract_json_payload(text: str) -> dict:
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _analyze_with_codex_cli(content: str, options: dict | None = None) -> AnalyzeResult:
    cfg = get_config()
    cmd = [cfg.codex_cli_command] + shlex.split(cfg.codex_cli_args)
    prompt = (
        "Return strict JSON only with keys: aiTitle, summaryShort, summaryLong, tags(array), "
        "hashtags(array), category, confidence(0~1), isLowContent(boolean). "
        f"Model hint: {cfg.llm_model}.\n\nContent:\n{content[:8000]}"
    )

    proc = subprocess.run(
        cmd,
        input=prompt,
        text=True,
        capture_output=True,
        timeout=cfg.llm_timeout_sec,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"codex_cli_failed: {proc.stderr.strip()}")

    obj = _extract_json_payload(proc.stdout)
    tags = [str(t) for t in obj.get("tags", [])][:5]
    hashtags = [str(h) for h in obj.get("hashtags", [])][:5]
    confidence = obj.get("confidence", 0.5)
    try:
        confidence_val = float(confidence)
    except (TypeError, ValueError):
        confidence_val = 0.5

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
        confidence=confidence_val,
        is_low_content=bool(obj.get("isLowContent", len(content) < 120)),
    )


def analyze_with_llm(content: str, options: dict | None = None) -> AnalyzeResult:
    provider = get_config().llm_provider.lower()
    if provider == "codex_cli":
        return _analyze_with_codex_cli(content, options=options)
    return _heuristic_analysis(content, options=options)


def process_url(url: str, options: dict | None = None) -> dict:
    canonical = normalize_url(url)
    is_instagram = _is_instagram_url(canonical)
    instagram_unavailable_msg = (
        "인스타그램은 비로그인/비브라우저 요청을 차단합니다. "
        "Meta 앱의 oEmbed API(액세스 토큰) 연동 또는 캡션 수동 입력을 이용해 주세요."
    )
    config = get_config()
    content: str | None = None

    if is_instagram:
        logger.info("Instagram URL requested: %s", canonical)

    if is_instagram and config.instagram_browser == "playwright":
        try:
            logger.info("Instagram: trying Playwright browser fetch")
            content = fetch_instagram_via_browser(canonical)
            logger.info("Instagram: Playwright fetch ok, content length=%d", len(content or ""))
        except Exception as e:
            logger.warning("Instagram: Playwright fetch failed (%s), falling back to HTTP", e)
            content = None

    if not content:
        try:
            html = fetch_html(canonical)
        except Exception as e:
            if is_instagram:
                logger.warning("Instagram: fetch_failed for %s (%s)", canonical, e)
            return {
                "status": "fetch_failed",
                "sourceUrl": canonical,
                "errorMessage": instagram_unavailable_msg if is_instagram else "fetch failed",
            }
        content = extract_main_content(html)
        if not content and is_instagram:
            logger.info("Instagram: using HTTP + og: meta fallback")
            meta = _extract_og_meta(html)
            desc = meta.get("og:description", "").strip()
            title = meta.get("og:title", "").strip()
            if desc or title:
                content = (title + "\n\n" + desc).strip()
    if not content:
        if is_instagram:
            logger.warning("Instagram: extract_failed for %s", canonical)
        return {
            "status": "extract_failed",
            "sourceUrl": canonical,
            "errorMessage": instagram_unavailable_msg if is_instagram else "extract failed",
        }

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
