from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Sequence

from src.models import Job, SearchScore

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
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS search_scores (
                unique_key          TEXT NOT NULL,
                search_name         TEXT NOT NULL,
                fit_score           INTEGER NOT NULL,
                desirability_score  INTEGER NOT NULL,
                hard_fail           INTEGER NOT NULL,
                hard_fail_reason    TEXT NOT NULL DEFAULT '',
                score_detail        TEXT NOT NULL DEFAULT '{}',
                stage_reached       INTEGER NOT NULL,
                profile_hash        TEXT NOT NULL,
                requirements_hash   TEXT NOT NULL,
                scored_at           TEXT NOT NULL,
                PRIMARY KEY (unique_key, search_name)
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

    def get_all_known_keys(self) -> set[str]:
        """Return unique_keys of all jobs currently in the store."""
        cursor = self._conn.execute("SELECT unique_key FROM jobs")
        return {row[0] for row in cursor.fetchall()}

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

    def get_unscored_jobs_for_search(
        self,
        search_name: str,
        profile_hash: str,
        requirements_hash: str,
        regions: list[str],
    ) -> list[Job]:
        """Return active jobs with descriptions not yet scored (or needing re-score) for this search.

        A job needs scoring if it has no row in search_scores for this search, or if either
        hash has changed since it was last scored (profile or requirements updated).
        """
        cursor = self._conn.execute(
            """
            SELECT j.unique_key, j.title, j.url, j.company, j.ats_job_id,
                   j.location, j.department, j.description, j.posted_date,
                   j.first_seen, j.last_seen, j.is_active
            FROM jobs j
            LEFT JOIN search_scores ss
                ON j.unique_key = ss.unique_key AND ss.search_name = ?
            WHERE j.is_active = 1
              AND j.description != ''
              AND (ss.unique_key IS NULL
                   OR ss.profile_hash != ?
                   OR ss.requirements_hash != ?)
            """,
            (search_name, profile_hash, requirements_hash),
        )
        jobs = [self._row_to_job(row) for row in cursor.fetchall()]
        if not regions:
            return jobs
        return [j for j in jobs if any(r.lower() in j.location.lower() for r in regions)]

    def save_score(self, score: SearchScore) -> None:
        """Upsert a scoring result for a job/search pair."""
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO search_scores
                (unique_key, search_name, fit_score, desirability_score,
                 hard_fail, hard_fail_reason, score_detail, stage_reached,
                 profile_hash, requirements_hash, scored_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(unique_key, search_name) DO UPDATE SET
                fit_score          = excluded.fit_score,
                desirability_score = excluded.desirability_score,
                hard_fail          = excluded.hard_fail,
                hard_fail_reason   = excluded.hard_fail_reason,
                score_detail       = excluded.score_detail,
                stage_reached      = excluded.stage_reached,
                profile_hash       = excluded.profile_hash,
                requirements_hash  = excluded.requirements_hash,
                scored_at          = excluded.scored_at
            """,
            (
                score.unique_key, score.search_name,
                score.fit_score, score.desirability_score,
                int(score.hard_fail), score.hard_fail_reason,
                json.dumps(score.score_detail), score.stage_reached,
                score.profile_hash, score.requirements_hash, now,
            ),
        )
        self._conn.commit()

    def get_top_jobs_for_search(
        self,
        search_name: str,
        min_fit: int = 60,
        min_desirability: int = 60,
        limit: int = 10,
    ) -> list[tuple[Job, SearchScore]]:
        """Return the highest-scoring non-failed jobs for a search, ordered by combined score."""
        cursor = self._conn.execute(
            """
            SELECT j.unique_key, j.title, j.url, j.company, j.ats_job_id,
                   j.location, j.department, j.description, j.posted_date,
                   j.first_seen, j.last_seen, j.is_active,
                   ss.fit_score, ss.desirability_score, ss.hard_fail,
                   ss.hard_fail_reason, ss.score_detail, ss.stage_reached,
                   ss.profile_hash, ss.requirements_hash, ss.scored_at
            FROM jobs j
            JOIN search_scores ss ON j.unique_key = ss.unique_key
            WHERE ss.search_name = ?
              AND ss.hard_fail = 0
              AND ss.fit_score >= ?
              AND ss.desirability_score >= ?
            ORDER BY (ss.fit_score + ss.desirability_score) DESC
            LIMIT ?
            """,
            (search_name, min_fit, min_desirability, limit),
        )
        results = []
        for row in cursor.fetchall():
            job = self._row_to_job(row)
            score = SearchScore(
                unique_key=row[0],
                search_name=search_name,
                fit_score=row[12],
                desirability_score=row[13],
                hard_fail=bool(row[14]),
                hard_fail_reason=row[15] or "",
                score_detail=json.loads(row[16]) if row[16] else {},
                stage_reached=row[17],
                profile_hash=row[18],
                requirements_hash=row[19],
                scored_at=row[20],
            )
            results.append((job, score))
        return results

    def _row_to_job(self, row: tuple) -> Job:
        return Job(
            title=row[1],
            url=row[2],
            company=row[3],
            ats_job_id=row[4],
            location=row[5] or "",
            department=row[6] or "",
            description=row[7] or "",
            posted_date=date.fromisoformat(row[8]) if row[8] else None,
        )

    def close(self) -> None:
        self._conn.close()
