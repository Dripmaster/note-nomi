import unittest
from pathlib import Path

from app.analysis_worker import extract_main_content, normalize_url
from app.service import analyze_and_store
from app.storage import SQLiteStore


class ServiceTests(unittest.TestCase):
    def test_normalize_url_removes_query(self) -> None:
        self.assertEqual(
            normalize_url("https://example.com/a?utm_source=x&id=1"),
            "https://example.com/a",
        )

    def test_extract_main_content_article(self) -> None:
        html = "<html><body><article>Hello world</article></body></html>"
        self.assertEqual(extract_main_content(html), "Hello world")

    def test_analyze_and_store_creates_note(self) -> None:
        db_path = "data/test_note_nomi.db"
        path = Path(db_path)
        if path.exists():
            path.unlink()

        store = SQLiteStore(db_path=db_path)
        result = analyze_and_store("https://example.com/post?utm_source=abc", store)

        self.assertIn(result["status"], {"done", "partial_done"})
        self.assertIn("noteId", result)

        note = store.get_note(result["noteId"])
        self.assertIsNotNone(note)
        self.assertEqual(note.source_url, "https://example.com/post")
        assert note is not None
        self.assertIn("Sample content", note.content_full)


if __name__ == "__main__":
    unittest.main()
