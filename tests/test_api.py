import time
import unittest
from io import BytesIO
from importlib import import_module
from unittest import mock
from unittest.mock import patch
from zipfile import ZipFile


class APITests(unittest.TestCase):
    @unittest.skipUnless(
        __import__("importlib").util.find_spec("fastapi") is not None,
        "fastapi unavailable",
    )
    def test_home_contains_social_embed_viewer_markup(self) -> None:
        TestClient = import_module("fastapi.testclient").TestClient
        from app.main import app

        client = TestClient(app)
        home = client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn("연결된 소셜 페이지", home.text)
        self.assertIn("instagram-media", home.text)
        self.assertIn("threads-embed", home.text)

    @unittest.skipUnless(
        __import__("importlib").util.find_spec("fastapi") is not None,
        "fastapi unavailable",
    )
    def test_notes_kind_filter_for_youtube_and_invalid_kind(self) -> None:
        TestClient = import_module("fastapi.testclient").TestClient
        from app.main import app

        client = TestClient(app)

        csv_payload = (
            "Date,User,Message\n"
            "2026-02-23 12:34:56,me,watch this https://youtu.be/dQw4w9WgXcQ\n"
        ).encode("utf-8")
        imported = client.post(
            "/api/v1/import/kakaotalk?skip_duplicates=false",
            files={"file": ("kakaotalk.csv", csv_payload, "text/csv")},
        )
        self.assertEqual(imported.status_code, 200)
        imported_note_ids = imported.json()["noteIds"]
        self.assertGreaterEqual(len(imported_note_ids), 1)

        filtered = client.get("/api/v1/notes", params={"kind": "youtube", "size": 100})
        self.assertEqual(filtered.status_code, 200)
        body = filtered.json()
        self.assertGreaterEqual(body["total"], 1)
        returned_ids = [item["id"] for item in body["items"]]
        self.assertIn(imported_note_ids[0], returned_ids)
        self.assertTrue(
            all("youtube" in item.get("kinds", []) for item in body["items"])
        )

        invalid = client.get("/api/v1/notes", params={"kind": "not_a_kind"})
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.json()["detail"], "invalid_kind")

    @unittest.skipUnless(
        __import__("importlib").util.find_spec("fastapi") is not None,
        "fastapi unavailable",
    )
    @patch("app.analysis_worker.fetch_html")
    def test_note_kinds_counts_endpoint(self, mocked_fetch: mock.Mock) -> None:
        mocked_fetch.return_value = "<html><body><article>Example article for kind counts.</article></body></html>"

        TestClient = import_module("fastapi.testclient").TestClient
        from app.main import app
        from app.note_kinds import KIND_ORDER

        client = TestClient(app)

        csv_payload = (
            "Date,User,Message\n"
            "2026-02-23 12:34:56,me,watch this https://youtu.be/dQw4w9WgXcQ\n"
        ).encode("utf-8")
        imported = client.post(
            "/api/v1/import/kakaotalk?skip_duplicates=false",
            files={"file": ("kakaotalk.csv", csv_payload, "text/csv")},
        )
        self.assertEqual(imported.status_code, 200)
        self.assertGreaterEqual(len(imported.json()["noteIds"]), 1)

        create = client.post(
            "/api/v1/ingestions",
            json={
                "urls": ["https://example.com"],
                "options": {
                    "summaryLength": "short",
                    "autoCategory": True,
                    "storeFullContent": True,
                },
            },
        )
        self.assertEqual(create.status_code, 200)
        job_id = create.json()["jobId"]

        for _ in range(30):
            job = client.get(f"/api/v1/ingestions/{job_id}")
            if (
                job.json()["counts"]["queued"] == 0
                and job.json()["counts"]["processing"] == 0
            ):
                break
            time.sleep(0.05)

        final_job = client.get(f"/api/v1/ingestions/{job_id}")
        self.assertGreaterEqual(final_job.json()["counts"]["done"], 1)

        counts_resp = client.get("/api/v1/note-kinds")
        self.assertEqual(counts_resp.status_code, 200)
        body = counts_resp.json()
        self.assertIn("items", body)
        self.assertIn("totalNotes", body)
        self.assertGreaterEqual(body["totalNotes"], 2)

        counts = {item["kind"]: item["count"] for item in body["items"]}
        for kind in KIND_ORDER:
            self.assertIn(kind, counts)
        self.assertGreaterEqual(counts["youtube"], 1)
        self.assertGreaterEqual(counts["other_link"], 1)

    @unittest.skipUnless(
        __import__("importlib").util.find_spec("fastapi") is not None,
        "fastapi unavailable",
    )
    def test_note_kinds_counts_endpoint_with_q_filter(self) -> None:
        TestClient = import_module("fastapi.testclient").TestClient
        from app.main import app

        client = TestClient(app)

        csv_payload = (
            "Date,User,Message\n"
            "2026-02-23 12:34:56,me,watch this https://youtu.be/dQw4w9WgXcQ\n"
        ).encode("utf-8")
        imported = client.post(
            "/api/v1/import/kakaotalk?skip_duplicates=false",
            files={"file": ("kakaotalk.csv", csv_payload, "text/csv")},
        )
        self.assertEqual(imported.status_code, 200)
        self.assertGreaterEqual(len(imported.json()["noteIds"]), 1)

        counts_resp = client.get("/api/v1/note-kinds", params={"q": "watch"})
        self.assertEqual(counts_resp.status_code, 200)

        body = counts_resp.json()
        self.assertIn("items", body)
        self.assertIsInstance(body["items"], list)
        self.assertGreater(len(body["items"]), 0)
        for item in body["items"]:
            self.assertIn("kind", item)
            self.assertIn("count", item)

    @unittest.skipUnless(
        __import__("importlib").util.find_spec("fastapi") is not None,
        "fastapi unavailable",
    )
    @patch("app.analysis_worker.fetch_html")
    def test_ingestion_search_export_flow(self, mocked_fetch: mock.Mock) -> None:
        mocked_fetch.return_value = "<html><body><article>Sample content for API integration test. Includes note export flow and category management.</article></body></html>"

        TestClient = import_module("fastapi.testclient").TestClient
        from app.main import app

        client = TestClient(app)

        create = client.post(
            "/api/v1/ingestions",
            json={
                "urls": ["https://example.com/a", "https://example.com/b"],
                "options": {
                    "summaryLength": "short",
                    "autoCategory": True,
                    "storeFullContent": True,
                },
            },
        )
        self.assertEqual(create.status_code, 200)
        job_id = create.json()["jobId"]

        for _ in range(30):
            job = client.get(f"/api/v1/ingestions/{job_id}")
            if (
                job.json()["counts"]["queued"] == 0
                and job.json()["counts"]["processing"] == 0
            ):
                break
            time.sleep(0.05)

        final_job = client.get(f"/api/v1/ingestions/{job_id}")
        self.assertGreaterEqual(final_job.json()["counts"]["done"], 1)

        csv_import = client.post(
            "/api/v1/import/urls-csv?skip_duplicates=false",
            files={
                "file": (
                    "urls.csv",
                    b"url\nhttps://example.com/c\nhttps://example.com/d\n",
                    "text/csv",
                )
            },
        )
        self.assertEqual(csv_import.status_code, 200)
        self.assertEqual(csv_import.json()["status"], "queued")
        csv_job_id = csv_import.json()["jobId"]

        for _ in range(30):
            csv_job = client.get(f"/api/v1/ingestions/{csv_job_id}")
            if (
                csv_job.json()["counts"]["queued"] == 0
                and csv_job.json()["counts"]["processing"] == 0
            ):
                break
            time.sleep(0.05)

        notes_all = client.get("/api/v1/notes")
        self.assertEqual(notes_all.status_code, 200)
        note_ids = [item["id"] for item in notes_all.json()["items"][:2]]
        batch_patch = client.patch(
            "/api/v1/notes/batch",
            json={
                "noteIds": note_ids,
                "category": "BatchUpdated",
                "tags": [
                    {"name": "bulk-tag", "type": "tag"},
                    {"name": "bulk-hash", "type": "hashtag"},
                ],
            },
        )
        self.assertEqual(batch_patch.status_code, 200)
        self.assertEqual(batch_patch.json()["updated"], len(note_ids))

        paged_notes = client.get(
            "/api/v1/notes", params={"page": 1, "size": 1, "sort": "created_desc"}
        )
        self.assertEqual(paged_notes.status_code, 200)
        self.assertEqual(paged_notes.json()["size"], 1)

        search = client.get(
            "/api/v1/search",
            params={"q": "Sample", "scope": "full_content", "page": 1, "size": 1},
        )
        self.assertEqual(search.status_code, 200)
        self.assertEqual(search.json()["size"], 1)
        self.assertIn("snippet", search.json()["items"][0])

        tags_search = client.get(
            "/api/v1/search",
            params={"q": "bulk-tag", "scope": "tags", "page": 1, "size": 10},
        )
        self.assertEqual(tags_search.status_code, 200)
        self.assertGreaterEqual(tags_search.json()["total"], 1)

        created_category = client.post(
            "/api/v1/categories", json={"name": "Tech", "color": "#111111"}
        )
        self.assertEqual(created_category.status_code, 200)
        category_id = created_category.json()["id"]

        renamed_by_id = client.patch(
            f"/api/v1/categories/{category_id}",
            json={"toName": "Engineering", "color": "#222222"},
        )
        self.assertEqual(renamed_by_id.status_code, 200)

        merged = client.post(
            "/api/v1/categories/merge",
            json={"targetName": "Engineering", "sourceNames": ["개발", "AI"]},
        )
        self.assertEqual(merged.status_code, 200)

        notes = client.get("/api/v1/notes")
        first_created_at = notes.json()["items"][0]["createdAt"]

        exported = client.post(
            "/api/v1/exports/notebooklm",
            json={
                "target": {
                    "type": "date_range",
                    "from": "2000-01-01T00:00:00+00:00",
                    "to": first_created_at,
                },
                "format": "markdown_zip",
                "include": {"sourceUrl": True, "contentFull": True},
            },
        )
        self.assertEqual(exported.status_code, 200)
        download = client.get(exported.json()["downloadUrl"])
        self.assertEqual(download.status_code, 200)

        with ZipFile(BytesIO(download.content), "r") as zf:
            self.assertGreaterEqual(len(zf.namelist()), 1)


if __name__ == "__main__":
    unittest.main()
