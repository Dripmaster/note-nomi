import time
import unittest
from io import BytesIO
from unittest.mock import patch
from zipfile import ZipFile


class APITests(unittest.TestCase):
    @unittest.skipUnless(__import__("importlib").util.find_spec("fastapi") is not None, "fastapi unavailable")
    @patch("app.analysis_worker.fetch_html")
    def test_ingestion_search_export_flow(self, mocked_fetch: unittest.mock.Mock) -> None:
        mocked_fetch.return_value = "<html><body><article>Sample content for API integration test. Includes note export flow and category management.</article></body></html>"

        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)

        create = client.post(
            "/api/v1/ingestions",
            json={
                "urls": ["https://example.com/a", "https://example.com/b"],
                "options": {"summaryLength": "short", "autoCategory": True, "storeFullContent": True},
            },
        )
        self.assertEqual(create.status_code, 200)
        job_id = create.json()["jobId"]

        for _ in range(30):
            job = client.get(f"/api/v1/ingestions/{job_id}")
            if job.json()["counts"]["queued"] == 0 and job.json()["counts"]["processing"] == 0:
                break
            time.sleep(0.05)

        final_job = client.get(f"/api/v1/ingestions/{job_id}")
        self.assertGreaterEqual(final_job.json()["counts"]["done"], 1)

        paged_notes = client.get("/api/v1/notes", params={"page": 1, "size": 1, "sort": "created_desc"})
        self.assertEqual(paged_notes.status_code, 200)
        self.assertEqual(paged_notes.json()["size"], 1)

        search = client.get("/api/v1/search", params={"q": "Sample", "scope": "full_content", "page": 1, "size": 1})
        self.assertEqual(search.status_code, 200)
        self.assertEqual(search.json()["size"], 1)
        self.assertIn("snippet", search.json()["items"][0])

        created_category = client.post("/api/v1/categories", json={"name": "Tech", "color": "#111111"})
        self.assertEqual(created_category.status_code, 200)
        category_id = created_category.json()["id"]

        renamed_by_id = client.patch(f"/api/v1/categories/{category_id}", json={"toName": "Engineering", "color": "#222222"})
        self.assertEqual(renamed_by_id.status_code, 200)

        merged = client.post("/api/v1/categories/merge", json={"targetName": "Engineering", "sourceNames": ["개발", "AI"]})
        self.assertEqual(merged.status_code, 200)

        notes = client.get("/api/v1/notes")
        first_created_at = notes.json()["items"][0]["createdAt"]

        exported = client.post(
            "/api/v1/exports/notebooklm",
            json={
                "target": {"type": "date_range", "from": "2000-01-01T00:00:00+00:00", "to": first_created_at},
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
