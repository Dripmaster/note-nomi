from __future__ import annotations

from app.config import get_config
from app.job_runner import JobRunner
from app.storage import SQLiteStore

config = get_config()
store = SQLiteStore(db_path=config.db_path)
job_runner = JobRunner(max_workers=2)
