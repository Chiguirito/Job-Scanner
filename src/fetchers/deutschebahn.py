from __future__ import annotations

import json
import logging
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from typing import Any

import requests

from src.fetchers.base import BaseFetcher
from src.fetchers.workday import _strip_html
from src.models import Job

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://db.jobs/service/search/de-de/5441588"
_DETAIL_BASE = "https://db.jobs"
_PAGE_SIZE = 20  # server enforces this regardless of numResults parameter
_SEARCH_WORKERS = 15
_DETAIL_WORKERS = 20
_REQUEST_TIMEOUT = 30
_HEADERS = {"User-Agent": "Mozilla/5.0"}


@dataclass
class DeutscheBahnConfig:
    company: str = "Deutsche Bahn"


class DeutscheBahnFetcher(BaseFetcher):
    """Fetches Deutsche Bahn job postings by scraping db.jobs.

    db.jobs is a custom careers portal (SOLR-backed) with no public JSON API.
    The German-locale search URL returns paginated HTML with 20 results per page.
    Each card embeds all listing metadata in a `track-interaction` attribute.
    Detail pages carry JSON-LD JobPosting schemas with full descriptions.
    """

    def __init__(self, config: DeutscheBahnConfig) -> None:
        self.config = config

    def fetch(self) -> list[Job]:
        jobs, raw = self.fetch_listings()
        return self.enrich_descriptions(jobs, raw)

    def fetch_listings(self) -> tuple[list[Job], list[dict[str, Any]]]:
        first_html = self._fetch_search_page(0)
        total = self._parse_total(first_html)
        all_jobs, all_raw = self._parse_page(first_html)

        num_pages = math.ceil(total / _PAGE_SIZE)
        page_nums = list(range(1, num_pages))
        with ThreadPoolExecutor(max_workers=_SEARCH_WORKERS) as executor:
            futures = {executor.submit(self._fetch_search_page, p): p for p in page_nums}
            for future in as_completed(futures):
                try:
                    jobs, raw = self._parse_page(future.result())
                    all_jobs.extend(jobs)
                    all_raw.extend(raw)
                except Exception as exc:
                    logger.warning("Search page fetch failed: %s", exc)

        logger.info("Found %d job listings for %s", len(all_jobs), self.config.company)
        return all_jobs, all_raw

    def enrich_descriptions(
        self, jobs: list[Job], raw_postings: list[dict[str, Any]]
    ) -> list[Job]:
        if not jobs:
            return jobs
        with ThreadPoolExecutor(max_workers=_DETAIL_WORKERS) as executor:
            futures = {executor.submit(self._fetch_detail, job): job for job in jobs}
            enriched = [future.result() for future in as_completed(futures)]
        logger.info(
            "Enriched %d job descriptions for %s", len(enriched), self.config.company
        )
        return enriched

    def _fetch_search_page(self, page_num: int) -> str:
        resp = requests.get(
            _SEARCH_URL,
            params={"qli": "true", "query": "", "sort": "pubExternalDate_tdt", "pageNum": page_num},
            headers=_HEADERS,
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.text

    def _parse_total(self, html: str) -> int:
        """Parse total from German-formatted number like '3.223 Stellen'."""
        m = re.search(r"([\d.]+)\s*Stellen", html)
        if not m:
            return 0
        return int(m.group(1).replace(".", ""))

    def _parse_page(self, html: str) -> tuple[list[Job], list[dict[str, Any]]]:
        """Extract job cards from a search results page."""
        job_ids = re.findall(r'<a href="/de-de/Suche/[^"?]+\?jobId=(\d+)"', html)
        hrefs = re.findall(r'<a href="(/de-de/Suche/[^"?]+\?jobId=\d+)"', html)
        titles = re.findall(
            r'<span class="m-search-hit__title-text"\s*>\s*([^<]+)\s*</span>', html
        )
        # track-interaction="bookmark job|jobId|location|state|country|company|start|type|category|level"
        tracks = re.findall(r'track-interaction="bookmark job\|([^"]+)"', html)

        jobs: list[Job] = []
        raw: list[dict[str, Any]] = []
        for job_id, href, title, track in zip(job_ids, hrefs, titles, tracks):
            parts = track.split("|")
            location = _normalize_location(parts[1]) if len(parts) > 1 else "Germany"
            department = parts[7] if len(parts) > 7 else ""
            jobs.append(
                Job(
                    title=title.strip(),
                    url=f"{_DETAIL_BASE}{href}",
                    company=self.config.company,
                    ats_job_id=job_id,
                    location=location,
                    department=department,
                    description="",
                )
            )
            raw.append({"job_id": job_id})
        return jobs, raw

    def _fetch_detail(self, job: Job) -> Job:
        """Fetch the job detail page and extract description from JSON-LD."""
        try:
            resp = requests.get(job.url, headers=_HEADERS, timeout=_REQUEST_TIMEOUT)
            if resp.status_code != 200:
                return job
            json_blocks = re.findall(
                r'application/ld\+json[^>]*>(.*?)</script>', resp.text, re.DOTALL
            )
            for block in json_blocks:
                if "JobPosting" not in block:
                    continue
                data = json.loads(block.strip())
                description = _strip_html(data.get("description", ""))
                return replace(job, description=description)
        except Exception as exc:
            logger.warning("Failed to enrich %s: %s", job.url, exc)
        return job


def _normalize_location(raw: str) -> str:
    """Replace German 'Deutschland' with 'Germany' so region filters match."""
    return raw.replace("Deutschland", "Germany")
