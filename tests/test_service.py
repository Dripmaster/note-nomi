import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.analysis_worker import analyze_with_llm, extract_main_content, normalize_url, process_url
from app.service import analyze_and_store
from app.storage import SQLiteStore


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db_path = "data/test_note_nomi.db"
        path = Path(self.db_path)
        if path.exists():
            path.unlink()
        self.store = SQLiteStore(db_path=self.db_path)

    def test_normalize_url_removes_tracking_query(self) -> None:
        self.assertEqual(normalize_url("https://example.com/a?utm_source=x&id=1"), "https://example.com/a?id=1")

    def test_extract_main_content_article(self) -> None:
        html = "<html><body><article>Hello <b>world</b></article></body></html>"
        self.assertEqual(extract_main_content(html), "Hello world")

    @patch("app.analysis_worker.subprocess.run")
    @patch("app.analysis_worker.get_config")
    def test_codex_cli_provider(self, mocked_cfg: unittest.mock.Mock, mocked_run: unittest.mock.Mock) -> None:
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

        result = analyze_with_llm("Codex CLI integration content", options={"summaryLength": "standard"})
        self.assertEqual(result.ai_title, "코덱스 제목")
        self.assertEqual(result.category, "AI")

    def test_analysis_option_short_summary(self) -> None:
        content = "Sentence one about API. Sentence two about service architecture. Sentence three about notes and tags."
        result = analyze_with_llm(content, options={"summaryLength": "short", "autoCategory": True})
        self.assertLessEqual(len(result.summary_long), len(content))

    @patch("app.analysis_worker.fetch_html")
    def test_analyze_and_store_creates_note(self, mocked_fetch: unittest.mock.Mock) -> None:
        mocked_fetch.return_value = "<html><body><article>Sample content from test article. It contains useful information about API design.</article></body></html>"
        result = analyze_and_store("https://example.com/post?utm_source=abc", self.store, options={"storeFullContent": True})
        self.assertIn("noteId", result)
        note = self.store.get_note(result["noteId"])
        assert note is not None
        self.assertEqual(note["sourceUrl"], "https://example.com/post")

    @patch("app.analysis_worker.fetch_html")
    def test_store_full_content_option(self, mocked_fetch: unittest.mock.Mock) -> None:
        mocked_fetch.return_value = "<html><body><article>Only summary no content body storage option.</article></body></html>"
        result = process_url("https://example.com/a", options={"storeFullContent": False})
        self.assertEqual(result["contentFull"], "")

    def test_job_lifecycle(self) -> None:
        job_id = self.store.create_job(["https://example.com/a", "https://fetch-fail.example.com"], options={"summaryLength": "short"})
        job_before = self.store.get_job(job_id)
        assert job_before is not None
        self.assertEqual(job_before["options"]["summaryLength"], "short")

    @patch("app.analysis_worker.fetch_html")
    def test_fts_search_and_filters(self, mocked_fetch: unittest.mock.Mock) -> None:
        mocked_fetch.return_value = "<html><body><article>Sample content with llm agent and fastapi service.</article></body></html>"
        analyze_and_store("https://example.com/llm-agent", self.store)
        items, total = self.store.list_notes(q="Sample", tag="llm", page=1, size=10)
        self.assertGreaterEqual(total, 1)
        self.assertGreaterEqual(len(items), 1)


if __name__ == "__main__":
    unittest.main()
