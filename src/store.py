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
                first_seen  TEXT NOT NULL,
                last_seen   TEXT NOT NULL,
                is_active   INTEGER NOT NULL DEFAULT 1
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
        """Insert new jobs or update last_seen and reactivate existing ones."""
        now = datetime.now(timezone.utc).isoformat()
        for job in jobs:
            self._conn.execute(
                """
                INSERT INTO jobs
                    (unique_key, title, url, company, ats_job_id,
                     location, department, description, posted_date,
                     first_seen, last_seen, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(unique_key) DO UPDATE SET
                    last_seen = excluded.last_seen,
                    is_active = 1
                """,
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
                    now,
                ),
            )
        self._conn.commit()

    def mark_closed(self, company: str, active_job_keys: set[str]) -> list[str]:
        """Mark jobs as closed if they were not in the latest scan.

        Returns the unique_keys of newly closed jobs.
        """
        now = datetime.now(timezone.utc).isoformat()
        cursor = self._conn.execute(
            "SELECT unique_key FROM jobs WHERE company = ? AND is_active = 1",
            (company,),
        )
        all_active_keys = {row[0] for row in cursor.fetchall()}
        newly_closed = all_active_keys - active_job_keys

        if newly_closed:
            placeholders = ",".join("?" for _ in newly_closed)
            self._conn.execute(
                f"UPDATE jobs SET is_active = 0, last_seen = ? WHERE unique_key IN ({placeholders})",
                [now, *newly_closed],
            )
            self._conn.commit()

        return list(newly_closed)

    def filter_new(self, jobs: Sequence[Job]) -> list[Job]:
        """Return only jobs not yet in the store, and save all of them."""
        new_jobs = [job for job in jobs if self.is_new(job)]
        self.save(jobs)
        return new_jobs

    def count(self, active_only: bool = False) -> int:
        """Return the number of stored jobs."""
        query = "SELECT COUNT(*) FROM jobs"
        if active_only:
            query += " WHERE is_active = 1"
        cursor = self._conn.execute(query)
        return cursor.fetchone()[0]

    def close(self) -> None:
        self._conn.close()
