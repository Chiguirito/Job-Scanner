from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from src.models import Job

DEFAULT_DB_PATH = Path("data/jobs.db")


class JobStore:
    """SQLite-backed store for deduplicating and persisting job postings."""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._init_db()

    def _init_db(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                unique_key  TEXT PRIMARY KEY,
                title       TEXT NOT NULL,
                url         TEXT NOT NULL,
                company     TEXT NOT NULL,
                ats_job_id  TEXT NOT NULL,
                location    TEXT,
                department  TEXT,
                description TEXT,
                posted_date TEXT,
                first_seen  TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def is_new(self, job: Job) -> bool:
        """Return True if this job has not been seen before."""
        cursor = self._conn.execute(
            "SELECT 1 FROM jobs WHERE unique_key = ?", (job.unique_key,)
        )
        return cursor.fetchone() is None

    def save(self, jobs: Sequence[Job]) -> None:
        """Insert jobs into the store, ignoring duplicates."""
        now = datetime.now(timezone.utc).isoformat()
        self._conn.executemany(
            """
            INSERT OR IGNORE INTO jobs
                (unique_key, title, url, company, ats_job_id,
                 location, department, description, posted_date, first_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    job.unique_key,
                    job.title,
                    job.url,
                    job.company,
                    job.ats_job_id,
                    job.location,
                    job.department,
                    job.description,
                    job.posted_date.isoformat() if job.posted_date else None,
                    now,
                )
                for job in jobs
            ],
        )
        self._conn.commit()

    def filter_new(self, jobs: Sequence[Job]) -> list[Job]:
        """Return only jobs not yet in the store, and save them."""
        new_jobs = [job for job in jobs if self.is_new(job)]
        if new_jobs:
            self.save(new_jobs)
        return new_jobs

    def count(self) -> int:
        """Return the total number of stored jobs."""
        cursor = self._conn.execute("SELECT COUNT(*) FROM jobs")
        return cursor.fetchone()[0]

    def close(self) -> None:
        self._conn.close()
