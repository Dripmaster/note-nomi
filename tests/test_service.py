import unittest
from pathlib import Path

from app.analysis_worker import extract_main_content, normalize_url, process_url
from app.service import analyze_and_store
from app.storage import SQLiteStore


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db_path = "data/test_note_nomi.db"
        path = Path(self.db_path)
        if path.exists():
            path.unlink()
        self.store = SQLiteStore(db_path=self.db_path)

    def test_normalize_url_removes_query(self) -> None:
        self.assertEqual(
            normalize_url("https://example.com/a?utm_source=x&id=1"),
            "https://example.com/a",
        )

    def test_extract_main_content_article(self) -> None:
        html = "<html><body><article>Hello world</article></body></html>"
        self.assertEqual(extract_main_content(html), "Hello world")

    def test_analyze_and_store_creates_note(self) -> None:
        result = analyze_and_store("https://example.com/post?utm_source=abc", self.store)

        self.assertIn(result["status"], {"done", "partial_done"})
        self.assertIn("noteId", result)

        note = self.store.get_note(result["noteId"])
        self.assertIsNotNone(note)
        assert note is not None
        self.assertEqual(note["sourceUrl"], "https://example.com/post")
        self.assertIn("Sample content", note["contentFull"])

    def test_failure_codes(self) -> None:
        fetch_fail = process_url("https://fetch-fail.example.com")
        self.assertEqual(fetch_fail["status"], "fetch_failed")

        partial = process_url("https://example.com/analyze-fail")
        self.assertEqual(partial["status"], "partial_done")

    def test_job_lifecycle(self) -> None:
        job_id = self.store.create_job(["https://example.com/a", "https://fetch-fail.example.com"])
        job_before = self.store.get_job(job_id)
        assert job_before is not None
        self.assertEqual(job_before["counts"]["queued"], 2)

        self.store.update_job_item(job_id, "https://example.com/a", "done", 1, None, None)
        self.store.update_job_item(job_id, "https://fetch-fail.example.com", "failed", None, "fetch_failed", "fetch failed")
        self.store.recalc_job_counts(job_id)

        job_after = self.store.get_job(job_id)
        assert job_after is not None
        self.assertEqual(job_after["counts"]["done"], 1)
        self.assertEqual(job_after["counts"]["failed"], 1)

        retried = self.store.mark_retry_failed_items(job_id)
        self.assertEqual(retried, 1)

    def test_fts_search(self) -> None:
        analyze_and_store("https://example.com/llm-agent", self.store)
        items = self.store.list_notes(q="Sample")
        self.assertGreaterEqual(len(items), 1)


if __name__ == "__main__":
    unittest.main()
