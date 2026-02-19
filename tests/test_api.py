import unittest
from io import BytesIO
from zipfile import ZipFile


class APITests(unittest.TestCase):
    @unittest.skipUnless(__import__("importlib").util.find_spec("fastapi") is not None, "fastapi unavailable")
    def test_ingestion_search_export_flow(self) -> None:
        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)

        create = client.post(
            "/api/v1/ingestions",
            json={
                "urls": ["https://example.com/a", "https://example.com/analyze-fail"],
                "options": {"summaryLength": "standard", "autoCategory": True, "storeFullContent": True},
            },
        )
        self.assertEqual(create.status_code, 200)
        job_id = create.json()["jobId"]

        job = client.get(f"/api/v1/ingestions/{job_id}")
        self.assertEqual(job.status_code, 200)
        self.assertGreaterEqual(job.json()["counts"]["done"], 1)

        search = client.get("/api/v1/search", params={"q": "Sample", "scope": "full_content"})
        self.assertEqual(search.status_code, 200)
        self.assertGreaterEqual(search.json()["total"], 1)

        exported = client.post(
            "/api/v1/exports/notebooklm",
            json={
                "target": {"type": "all"},
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
