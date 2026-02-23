import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

from app.analysis_worker import (
    analyze_with_llm,
    extract_main_content,
    normalize_url,
    process_url,
)
from app.kakaotalk_parser import parse_urls_csv_bytes
from app.service import analyze_and_store
from app.storage import SQLiteStore


class _MockHeaders:
    def get_content_charset(self, default: str) -> str:
        return default


class _MockResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.headers = _MockHeaders()

    def read(self) -> bytes:
        import json

        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class ServiceTests(unittest.TestCase):
    db_path: str = ""
    store: Any = None

    def setUp(self) -> None:
        self.db_path = "data/test_note_nomi.db"
        path = Path(self.db_path)
        if path.exists():
            path.unlink()
        self.store = SQLiteStore(db_path=self.db_path)

    def test_normalize_url_removes_tracking_query(self) -> None:
        self.assertEqual(
            normalize_url("https://example.com/a?utm_source=x&id=1"),
            "https://example.com/a?id=1",
        )

    def test_extract_main_content_article(self) -> None:
        html = "<html><body><article>Hello <b>world</b></article></body></html>"
        self.assertEqual(extract_main_content(html), "Hello world")

    @patch("app.analysis_worker.subprocess.run")
    @patch("app.analysis_worker.get_config")
    def test_codex_cli_provider(self, mocked_cfg: Mock, mocked_run: Mock) -> None:
        mocked_cfg.return_value = SimpleNamespace(
            llm_provider="codex_cli",
            codex_cli_command="codex",
            codex_cli_args="run --json",
            llm_timeout_sec=3.0,
            llm_model="gpt-5.2-codex",
            default_category="미분류",
        )
        mocked_run.return_value = SimpleNamespace(
            returncode=0,
            stdout='{"aiTitle":"코덱스 제목","summaryShort":"짧은 요약","summaryLong":"긴 요약","tags":["tag1"],"hashtags":["#tag1"],"category":"AI","confidence":0.87,"isLowContent":false}',
            stderr="",
        )

        result = analyze_with_llm(
            "Codex CLI integration content", options={"summaryLength": "standard"}
        )
        self.assertEqual(result.ai_title, "코덱스 제목")
        self.assertEqual(result.category, "AI")

    def test_analysis_option_short_summary(self) -> None:
        content = "Sentence one about API. Sentence two about service architecture. Sentence three about notes and tags."
        result = analyze_with_llm(
            content, options={"summaryLength": "short", "autoCategory": True}
        )
        self.assertLessEqual(len(result.summary_long), len(content))

    @patch("app.analysis_worker.fetch_html")
    def test_analyze_and_store_creates_note(self, mocked_fetch: Mock) -> None:
        mocked_fetch.return_value = "<html><body><article>Sample content from test article. It contains useful information about API design.</article></body></html>"
        result = analyze_and_store(
            "https://example.com/post?utm_source=abc",
            self.store,
            options={"storeFullContent": True},
        )
        self.assertIn("noteId", result)
        note = self.store.get_note(result["noteId"])
        assert note is not None
        self.assertEqual(note["sourceUrl"], "https://example.com/post")

    @patch("app.analysis_worker.fetch_html")
    def test_store_full_content_option(self, mocked_fetch: Mock) -> None:
        mocked_fetch.return_value = "<html><body><article>Only summary no content body storage option.</article></body></html>"
        result = process_url(
            "https://example.com/a", options={"storeFullContent": False}
        )
        self.assertEqual(result["contentFull"], "")

    def test_job_lifecycle(self) -> None:
        job_id = self.store.create_job(
            ["https://example.com/a", "https://fetch-fail.example.com"],
            options={"summaryLength": "short"},
        )
        job_before = self.store.get_job(job_id)
        assert job_before is not None
        self.assertEqual(job_before["options"]["summaryLength"], "short")

    def test_parse_urls_csv_bytes(self) -> None:
        rows = parse_urls_csv_bytes(
            b"url,name\nhttps://example.com/a,A\nhttps://example.com/b,B\nhttps://example.com/a,Dup\n"
        )
        self.assertEqual(rows, ["https://example.com/a", "https://example.com/b"])

    def test_batch_update_note_metadata(self) -> None:
        first_id = self.store.create_note(
            {
                "sourceUrl": "https://example.com/one",
                "contentFull": "first",
                "status": "done",
                "tags": [],
                "hashtags": [],
            }
        )
        second_id = self.store.create_note(
            {
                "sourceUrl": "https://example.com/two",
                "contentFull": "second",
                "status": "done",
                "tags": [],
                "hashtags": [],
            }
        )

        result = self.store.batch_update_note_metadata(
            [first_id, second_id],
            {
                "category": "Batch",
                "tags": [
                    {"name": "t1", "type": "tag"},
                    {"name": "h1", "type": "hashtag"},
                ],
            },
        )

        self.assertEqual(result["updated"], 2)
        note = self.store.get_note(first_id)
        assert note is not None
        self.assertEqual((note.get("category") or {}).get("name"), "Batch")
        names = {t["name"] for t in note.get("tags", [])}
        self.assertIn("t1", names)

    def test_create_note_persists_primary_kind_and_kinds(self) -> None:
        note_id = self.store.create_note(
            {
                "sourceUrl": "kakaotalk://in-chat/123",
                "contentFull": "check this https://youtu.be/abc",
                "summaryShort": "",
                "summaryLong": "",
                "status": "done",
                "tags": [],
                "hashtags": [],
            }
        )

        note = self.store.get_note(note_id)
        assert note is not None
        self.assertEqual(note["primaryKind"], "plain_text")
        self.assertEqual(note["kinds"], ["plain_text", "youtube"])

        notes, total = self.store.list_notes(page=1, size=10)
        self.assertEqual(total, 1)
        self.assertEqual(notes[0]["primaryKind"], "plain_text")
        self.assertEqual(notes[0]["kinds"], ["plain_text", "youtube"])

    def test_update_note_recomputes_kinds_when_text_changes(self) -> None:
        note_id = self.store.create_note(
            {
                "sourceUrl": "https://example.com/post",
                "contentFull": "initial body",
                "summaryShort": "",
                "summaryLong": "",
                "status": "done",
                "tags": [],
                "hashtags": [],
            }
        )

        updated = self.store.update_note(
            note_id,
            {"contentFull": "new body with https://www.youtube.com/watch?v=abc"},
        )
        assert updated is not None
        self.assertEqual(updated["primaryKind"], "other_link")
        self.assertEqual(updated["kinds"], ["youtube", "other_link"])

        updated_again = self.store.update_note(note_id, {"contentFull": "no links"})
        assert updated_again is not None
        self.assertEqual(updated_again["primaryKind"], "other_link")
        self.assertEqual(updated_again["kinds"], ["other_link"])

    def test_backfill_note_kinds_repairs_legacy_rows(self) -> None:
        legacy_id = self.store.create_note(
            {
                "sourceUrl": "kakaotalk://in-chat/legacy",
                "contentFull": "legacy memo has https://youtu.be/abc",
                "summaryShort": "",
                "summaryLong": "",
                "status": "done",
                "tags": [],
                "hashtags": [],
            }
        )
        healthy_id = self.store.create_note(
            {
                "sourceUrl": "https://example.com/healthy",
                "contentFull": "already populated",
                "summaryShort": "",
                "summaryLong": "",
                "status": "done",
                "tags": [],
                "hashtags": [],
            }
        )

        with self.store._connect() as conn:
            healthy_before = conn.execute(
                "SELECT updated_at, kinds_json FROM notes WHERE id=?", (healthy_id,)
            ).fetchone()
            conn.execute(
                "UPDATE notes SET primary_kind=NULL, kinds_json='' WHERE id=?",
                (legacy_id,),
            )

        result = self.store.backfill_note_kinds(batch_size=1, max_rows=10)
        self.assertEqual(result["scanned"], 1)
        self.assertEqual(result["updated"], 1)

        repaired = self.store.get_note(legacy_id)
        assert repaired is not None
        self.assertEqual(repaired["primaryKind"], "plain_text")
        self.assertEqual(repaired["kinds"], ["plain_text", "youtube"])

        with self.store._connect() as conn:
            healthy_after = conn.execute(
                "SELECT updated_at, kinds_json FROM notes WHERE id=?", (healthy_id,)
            ).fetchone()

        self.assertEqual(healthy_before["updated_at"], healthy_after["updated_at"])
        self.assertEqual(healthy_before["kinds_json"], healthy_after["kinds_json"])

    def test_backfill_note_kinds_treats_empty_json_array_as_missing(self) -> None:
        note_id = self.store.create_note(
            {
                "sourceUrl": "https://example.com/with-threads",
                "contentFull": "visit https://threads.net/@user/post/1",
                "summaryShort": "",
                "summaryLong": "",
                "status": "done",
                "tags": [],
                "hashtags": [],
            }
        )

        with self.store._connect() as conn:
            conn.execute(
                "UPDATE notes SET kinds_json='[]', primary_kind=NULL WHERE id=?",
                (note_id,),
            )

        first = self.store.backfill_note_kinds(batch_size=10, max_rows=10)
        self.assertEqual(first["updated"], 1)
        second = self.store.backfill_note_kinds(batch_size=10, max_rows=10)
        self.assertEqual(second["updated"], 0)

        note = self.store.get_note(note_id)
        assert note is not None
        self.assertEqual(note["primaryKind"], "other_link")
        self.assertEqual(note["kinds"], ["threads", "other_link"])

    @patch("app.analysis_worker.fetch_html")
    def test_fts_search_and_filters(self, mocked_fetch: Mock) -> None:
        mocked_fetch.return_value = "<html><body><article>Sample content with llm agent and fastapi service.</article></body></html>"
        analyze_and_store("https://example.com/llm-agent", self.store)
        items, total = self.store.list_notes(q="Sample", tag="llm", page=1, size=10)
        self.assertGreaterEqual(total, 1)
        self.assertGreaterEqual(len(items), 1)

    @patch("app.analysis_worker.fetch_html")
    def test_instagram_fetch_failed_returns_korean_message(
        self, mocked_fetch: Mock
    ) -> None:
        mocked_fetch.side_effect = RuntimeError("fetch_failed")
        result = process_url("https://www.instagram.com/p/ABC123/")
        self.assertEqual(result["status"], "fetch_failed")
        self.assertIn("인스타그램", result["errorMessage"])
        self.assertIn("oEmbed", result["errorMessage"])

    @patch("app.analysis_worker.fetch_html")
    def test_instagram_html_with_og_meta_uses_caption_as_content(
        self, mocked_fetch: Mock
    ) -> None:
        # Body has no article/main text, so extract_main_content is empty; we fall back to og: meta
        html = (
            "<html><head>"
            '<meta property="og:title" content="Post by user" />'
            '<meta property="og:description" content="Caption text from Instagram post." />'
            "</head><body><script>require('app')</script></body></html>"
        )
        mocked_fetch.return_value = html
        result = process_url("https://www.instagram.com/p/xyz/")
        self.assertIn(result["status"], ("done", "partial_done"))
        self.assertIn("Caption text from Instagram post", result.get("contentFull", ""))

    @patch("app.analysis_worker.fetch_instagram_via_browser")
    @patch("app.analysis_worker.get_config")
    def test_instagram_playwright_path_uses_browser_caption(
        self, mocked_config: Mock, mocked_browser: Mock
    ) -> None:
        mocked_config.return_value = SimpleNamespace(
            instagram_browser="playwright",
            browser_user_data_dir=None,
            browser_timeout_sec=25,
            default_category="미분류",
            llm_provider="heuristic",
        )
        mocked_browser.return_value = (
            "Caption from automated browser. This is the post text."
        )
        result = process_url("https://www.instagram.com/p/abc123/")
        mocked_browser.assert_called_once()
        self.assertIn(result["status"], ("done", "partial_done"))
        self.assertIn("Caption from automated browser", result.get("contentFull", ""))


if __name__ == "__main__":
    unittest.main()
