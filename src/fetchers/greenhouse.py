from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests

from src.fetchers.base import BaseFetcher
from src.fetchers.workday import _strip_html
from src.models import Job

logger = logging.getLogger(__name__)

_BOARDS_API = "https://boards-api.greenhouse.io/v1/boards"


@dataclass
class GreenhouseConfig:
    """Configuration for a single Greenhouse job board."""

    company: str
    board_slug: str  # e.g. "waymo" — appears in boards.greenhouse.io/<slug>
    fetch_descriptions: bool = True


class GreenhouseFetcher(BaseFetcher):
    """Fetches job postings from the Greenhouse public board API."""

    def __init__(self, config: GreenhouseConfig) -> None:
        self.config = config
        self._jobs_url = f"{_BOARDS_API}/{config.board_slug}/jobs"

    def fetch(self) -> list[Job]:
        raw_postings = self._fetch_all_postings()
        jobs = [self._to_job(p) for p in raw_postings]
        if self.config.fetch_descriptions:
            jobs = self.enrich_descriptions(jobs, raw_postings)
        return jobs

    def fetch_listings(self) -> tuple[list[Job], list[dict[str, Any]]]:
        """Fetch all job listings without descriptions."""
        raw_postings = self._fetch_all_postings()
        jobs = [self._to_job(p) for p in raw_postings]
        return jobs, raw_postings

    def enrich_descriptions(
        self, jobs: list[Job], raw_postings: list[dict[str, Any]]
    ) -> list[Job]:
        """Fetch full descriptions for each job from the single-job endpoint."""
        return [self._enrich_with_description(j, p) for j, p in zip(jobs, raw_postings)]

    def _fetch_all_postings(self) -> list[dict[str, Any]]:
        """Fetch all jobs from the Greenhouse board API in a single request."""
        resp = requests.get(self._jobs_url, timeout=30)
        resp.raise_for_status()
        postings = resp.json().get("jobs", [])
        logger.info("Fetched %d jobs from %s", len(postings), self.config.company)
        return postings

    def _to_job(self, posting: dict[str, Any]) -> Job:
        """Convert a Greenhouse job dict to a normalised Job."""
        departments = posting.get("departments") or []
        department = departments[0].get("name", "") if departments else ""
        location = posting.get("location") or {}

        return Job(
            title=posting.get("title", ""),
            url=posting.get("absolute_url", ""),
            company=self.config.company,
            ats_job_id=str(posting.get("id", "")),
            location=location.get("name", ""),
            department=department,
            description="",
        )

    def _enrich_with_description(self, job: Job, posting: dict[str, Any]) -> Job:
        """Fetch the full job description from the single-job endpoint."""
        job_id = posting.get("id")
        if not job_id:
            return job

        detail_url = f"{self._jobs_url}/{job_id}"
        try:
            resp = requests.get(detail_url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.warning("Failed to fetch detail for %s", job.ats_job_id)
            return job

        description = _strip_html(data.get("content", ""))
        return Job(
            title=job.title,
            url=job.url,
            company=job.company,
            ats_job_id=job.ats_job_id,
            location=job.location,
            department=job.department,
            description=description,
        )
