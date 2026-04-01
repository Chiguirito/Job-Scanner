from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

import requests

from src.fetchers.base import BaseFetcher
from src.fetchers.workday import _strip_html
from src.models import Job

logger = logging.getLogger(__name__)

_API_BASE = "https://api.smartrecruiters.com/v1/companies"
_PAGE_SIZE = 100
_PAGINATION_WORKERS = 10
_DETAIL_WORKERS = 20
_TIMEOUT = 30
_HEADERS = {"User-Agent": "Mozilla/5.0"}


@dataclass
class SmartRecruitersConfig:
    """Configuration for a SmartRecruiters public jobs API fetcher."""

    company: str
    company_id: str  # SmartRecruiters company identifier, e.g. "BoschGroup"


class SmartRecruitersFetcher(BaseFetcher):
    """Fetches job postings from the SmartRecruiters public postings API.

    Uses two endpoints:
      - GET /v1/companies/{id}/postings?limit=100&offset=N  — paginated listings
        (includes location and function inline; no description)
      - GET /v1/companies/{id}/postings/{job_id}            — full job detail
        (includes jobAd sections for description enrichment)
    """

    def __init__(self, config: SmartRecruitersConfig) -> None:
        self.config = config

    def fetch(self) -> list[Job]:
        jobs, _ = self.fetch_listings()
        return jobs

    def fetch_listings(self) -> tuple[list[Job], list[dict[str, Any]]]:
        base_url = f"{_API_BASE}/{self.config.company_id}/postings"

        first = requests.get(
            base_url,
            params={"limit": _PAGE_SIZE, "offset": 0},
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        first.raise_for_status()
        data = first.json()
        total = data["totalFound"]
        all_raw = list(data["content"])

        offsets = range(_PAGE_SIZE, total, _PAGE_SIZE)
        if offsets:
            with ThreadPoolExecutor(max_workers=_PAGINATION_WORKERS) as executor:
                futures = {
                    executor.submit(self._fetch_page, base_url, offset): offset
                    for offset in offsets
                }
                for future in as_completed(futures):
                    try:
                        all_raw.extend(future.result())
                    except Exception as exc:
                        logger.warning(
                            "Page fetch failed for %s: %s", self.config.company, exc
                        )

        jobs = [self._to_job(raw) for raw in all_raw]
        logger.info("Fetched %d jobs from %s", len(jobs), self.config.company)
        return jobs, all_raw

    def enrich_descriptions(
        self, jobs: list[Job], raw_postings: list[dict[str, Any]]
    ) -> list[Job]:
        if not jobs:
            return jobs
        base_url = f"{_API_BASE}/{self.config.company_id}/postings"
        with ThreadPoolExecutor(max_workers=_DETAIL_WORKERS) as executor:
            futures = {
                executor.submit(self._fetch_description, base_url, job): job
                for job in jobs
            }
            enriched = [f.result() for f in as_completed(futures)]
        logger.info(
            "Enriched %d job descriptions for %s", len(enriched), self.config.company
        )
        return enriched

    def _fetch_page(self, base_url: str, offset: int) -> list[dict[str, Any]]:
        r = requests.get(
            base_url,
            params={"limit": _PAGE_SIZE, "offset": offset},
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()["content"]

    def _fetch_description(self, base_url: str, job: Job) -> Job:
        try:
            r = requests.get(
                f"{base_url}/{job.ats_job_id}",
                headers=_HEADERS,
                timeout=_TIMEOUT,
            )
            r.raise_for_status()
            sections = r.json().get("jobAd", {}).get("sections", {})
            parts = [
                sections.get(k, {}).get("text", "")
                for k in ("jobDescription", "qualifications", "additionalInformation")
            ]
            description = _strip_html("\n".join(p for p in parts if p))
            return Job(
                title=job.title,
                url=job.url,
                company=job.company,
                ats_job_id=job.ats_job_id,
                location=job.location,
                department=job.department,
                description=description,
            )
        except Exception as exc:
            logger.warning("Failed to enrich %s: %s", job.ats_job_id, exc)
            return job

    def _to_job(self, raw: dict[str, Any]) -> Job:
        loc = raw.get("location") or {}
        location = loc.get("fullLocation", "")
        function = raw.get("function") or {}
        department = function.get("label", "")
        return Job(
            title=raw.get("name", ""),
            url=raw.get("postingUrl", ""),
            company=self.config.company,
            ats_job_id=str(raw.get("id", "")),
            location=location,
            department=department,
            description="",
        )
