from __future__ import annotations

import html
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

import requests

from src.fetchers.base import BaseFetcher
from src.models import Job

logger = logging.getLogger(__name__)

BATCH_SIZE = 20        # Workday API maximum per request
PAGINATION_WORKERS = 5  # concurrent page fetches per company


@dataclass
class WorkdayConfig:
    """Configuration for a single Workday career site."""

    company: str
    base_url: str  # e.g. "https://nvidia.wd5.myworkdayjobs.com"
    site_path: str  # e.g. "/wday/cxs/nvidia/NVIDIAExternalCareerSite"
    site_name: str  # e.g. "NVIDIAExternalCareerSite" — used for public job URLs
    search_text: str = ""
    applied_facets: dict[str, list[str]] | None = None
    limit: int | None = None  # max total jobs to fetch; None = all
    fetch_descriptions: bool = True  # fetch full JD from detail endpoint


class WorkdayFetcher(BaseFetcher):
    """Fetches job postings from a Workday CXS career site."""

    def __init__(self, config: WorkdayConfig) -> None:
        self.config = config
        self._jobs_url = f"{config.base_url}{config.site_path}/jobs"
        self._detail_base = f"{config.base_url}{config.site_path}"

    def fetch(self) -> list[Job]:
        """Fetch all job postings from the Workday career site."""
        raw_postings = self._fetch_all_postings()
        jobs = [self._to_job(p) for p in raw_postings]
        if self.config.fetch_descriptions:
            jobs = self.enrich_descriptions(jobs, raw_postings)
        return jobs

    def fetch_listings(self) -> tuple[list[Job], list[dict[str, Any]]]:
        """Fetch job listings without descriptions. Returns (jobs, raw_postings)."""
        raw_postings = self._fetch_all_postings()
        jobs = [self._to_job(p) for p in raw_postings]
        return jobs, raw_postings

    def enrich_descriptions(
        self, jobs: list[Job], raw_postings: list[dict[str, Any]]
    ) -> list[Job]:
        """Fetch full descriptions for a list of jobs from the detail endpoint."""
        return [self._enrich_with_description(j, p) for j, p in zip(jobs, raw_postings)]

    def _fetch_all_postings(self) -> list[dict[str, Any]]:
        """Paginate through the Workday jobs endpoint using concurrent page fetches.

        Fetches the first page to discover the total count, then fires all
        remaining pages in parallel to minimise wall-clock time.
        """
        first = self._fetch_page(0)
        postings: list[dict[str, Any]] = first.get("jobPostings", [])
        total = first.get("total", 0)

        if not postings or len(postings) >= total:
            logger.info("Fetched %d jobs from %s", len(postings), self.config.company)
            return postings

        remaining_offsets = range(len(postings), total, BATCH_SIZE)
        if self.config.limit:
            remaining_offsets = [o for o in remaining_offsets if o < self.config.limit]

        with ThreadPoolExecutor(max_workers=PAGINATION_WORKERS) as executor:
            futures = [executor.submit(self._fetch_page, offset) for offset in remaining_offsets]
            for future in as_completed(futures):
                postings.extend(future.result().get("jobPostings", []))

        if self.config.limit:
            postings = postings[: self.config.limit]

        logger.info("Fetched %d jobs from %s", len(postings), self.config.company)
        return postings

    def _fetch_page(self, offset: int) -> dict[str, Any]:
        """Fetch a single page of job postings."""
        payload: dict[str, Any] = {
            "limit": BATCH_SIZE,
            "offset": offset,
            "searchText": self.config.search_text,
        }
        if self.config.applied_facets:
            payload["appliedFacets"] = self.config.applied_facets

        resp = requests.post(self._jobs_url, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _to_job(self, posting: dict[str, Any]) -> Job:
        """Convert a Workday posting dict to a normalised Job."""
        bullet_fields = posting.get("bulletFields", [])
        job_req_id = bullet_fields[0] if bullet_fields else posting.get("externalPath", "")

        external_path = posting.get("externalPath", "")
        job_url = f"{self.config.base_url}/{self.config.site_name}{external_path}"

        return Job(
            title=posting.get("title", ""),
            url=job_url,
            company=self.config.company,
            ats_job_id=job_req_id,
            location=posting.get("locationsText", ""),
            department="",
            description="",
            posted_date=None,
        )

    def _enrich_with_description(self, job: Job, posting: dict[str, Any]) -> Job:
        """Fetch the full job description from the detail endpoint."""
        external_path = posting.get("externalPath", "")
        if not external_path:
            return job

        detail_url = f"{self._detail_base}{external_path}"
        try:
            resp = requests.get(detail_url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.warning("Failed to fetch detail for %s", job.ats_job_id)
            return job

        info = data.get("jobPostingInfo", {})
        description_html = info.get("jobDescription", "")
        description = _strip_html(description_html)

        return Job(
            title=job.title,
            url=job.url,
            company=job.company,
            ats_job_id=job.ats_job_id,
            location=job.location,
            department=info.get("jobCategory", {}).get("descriptor", ""),
            description=description,
            posted_date=job.posted_date,
        )


def _strip_html(raw: str) -> str:
    """Remove HTML tags, decode entities, and collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
