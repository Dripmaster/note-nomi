from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from app.service import process_job
from app.storage import SQLiteStore


class JobRunner:
    def __init__(self, max_workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="note-nomi-job")
        self._running_job_ids: set[int] = set()
        self._lock = Lock()

    def enqueue(self, job_id: int, store: SQLiteStore) -> bool:
        with self._lock:
            if job_id in self._running_job_ids:
                return False
            self._running_job_ids.add(job_id)

        def _task() -> None:
            try:
                process_job(job_id, store)
            finally:
                with self._lock:
                    self._running_job_ids.discard(job_id)

        self._executor.submit(_task)
        return True
