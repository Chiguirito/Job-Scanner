from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
import requests

from src.fetchers.base import BaseFetcher
from src.models import Job

logger = logging.getLogger(__name__)

BATCH_SIZE = 20  # Workday API maximum per request


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


class WorkdayFetcher(BaseFetcher):
    """Fetches job postings from a Workday CXS career site."""

    def __init__(self, config: WorkdayConfig) -> None:
        self.config = config
        self._jobs_url = f"{config.base_url}{config.site_path}/jobs"
        self._job_detail_url = f"{config.base_url}{config.site_path}/job"

    def fetch(self) -> list[Job]:
        """Fetch all job postings from the Workday career site."""
        raw_postings = self._fetch_all_postings()
        return [self._to_job(p) for p in raw_postings]

    def _fetch_all_postings(self) -> list[dict[str, Any]]:
        """Paginate through the Workday jobs endpoint."""
        postings: list[dict[str, Any]] = []
        offset = 0
        total_limit = self.config.limit

        while True:
            batch = self._fetch_page(offset)
            total = batch.get("total", 0)
            page_postings = batch.get("jobPostings", [])

            if not page_postings:
                break

            postings.extend(page_postings)
            offset += len(page_postings)

            logger.debug("Fetched %d/%d jobs from %s", len(postings), total, self.config.company)

            if offset >= total:
                break
            if total_limit and len(postings) >= total_limit:
                postings = postings[:total_limit]
                break

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
        job_url = f"{self.config.base_url}/{self.config.site_name}/job{external_path}"

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
