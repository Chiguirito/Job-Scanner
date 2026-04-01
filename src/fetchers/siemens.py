from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from typing import Any

import requests

from src.fetchers.base import BaseFetcher
from src.fetchers.workday import _strip_html
from src.models import Job

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://jobs.siemens.com/en_US/externaljobs/SearchJobs/Germany/"
_DETAIL_URL = "https://jobs.siemens.com/en_US/externaljobs/JobDetail/{job_id}"
_PAGE_SIZE = 6
_SEARCH_WORKERS = 15
_DETAIL_WORKERS = 20
_REQUEST_TIMEOUT = 30
_HEADERS = {"User-Agent": "Mozilla/5.0"}


@dataclass
class SiemensConfig:
    company: str = "Siemens"


class SiemensFetcher(BaseFetcher):
    """Fetches Siemens job postings by scraping the Avature-based careers portal.

    jobs.siemens.com does not expose a JSON API or RSS feed. The Germany-specific
    search URL returns paginated HTML (6 per page). Listings provide job ID, title,
    city, and department; detail pages supply the full description and city/country.
    """

    def __init__(self, config: SiemensConfig) -> None:
        self.config = config

    def fetch(self) -> list[Job]:
        jobs, raw = self.fetch_listings()
        return self.enrich_descriptions(jobs, raw)

    def fetch_listings(self) -> tuple[list[Job], list[dict[str, Any]]]:
        first_html = self._fetch_search_page(0)
        total = self._parse_total(first_html)
        all_jobs, all_raw = self._parse_page(first_html)

        offsets = list(range(_PAGE_SIZE, total, _PAGE_SIZE))
        with ThreadPoolExecutor(max_workers=_SEARCH_WORKERS) as executor:
            futures = {executor.submit(self._fetch_search_page, off): off for off in offsets}
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

    def _fetch_search_page(self, offset: int) -> str:
        resp = requests.get(
            _SEARCH_URL,
            params={"folderRecordsPerPage": _PAGE_SIZE, "folderOffset": offset},
            headers=_HEADERS,
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.text

    def _parse_total(self, html: str) -> int:
        m = re.search(r'aria-label="(\d+) results"', html)
        return int(m.group(1)) if m else 0

    def _parse_page(self, html: str) -> tuple[list[Job], list[dict[str, Any]]]:
        """Extract job cards from a search results HTML page."""
        title_map: dict[str, str] = {}
        for m in re.finditer(
            r'<a[^>]*href="[^"]+/JobDetail/(\d+)"[^>]*>(.*?)</a>', html, re.DOTALL
        ):
            job_id = m.group(1)
            title = re.sub(r"\s+", " ", m.group(2)).strip()
            if job_id not in title_map and title != "Learn more":
                title_map[job_id] = title

        jobs: list[Job] = []
        raw: list[dict[str, Any]] = []
        subtitle_blocks = re.findall(
            r'<div class="article__header__text__subtitle">(.*?)</div>', html, re.DOTALL
        )
        for subtitle_html in subtitle_blocks:
            text = re.sub(r"<[^>]+>", "", subtitle_html)
            text = text.replace("&nbsp;", " ").replace("&#8226;", "•").replace("&amp;", "&")
            text = re.sub(r"\s+", " ", text).strip()
            # Format: "{location} • Job ID: {id} • {department}"
            parts = [p.strip() for p in text.split("•")]
            id_m = re.search(r"Job ID:\s*(\d+)", parts[1]) if len(parts) > 1 else None
            if not id_m:
                continue
            job_id = id_m.group(1)
            department = parts[2] if len(parts) > 2 else ""
            jobs.append(
                Job(
                    title=title_map.get(job_id, ""),
                    url=_DETAIL_URL.format(job_id=job_id),
                    company=self.config.company,
                    ats_job_id=job_id,
                    # "Germany" placeholder so region filter passes;
                    # overwritten in enrich_descriptions() with real city/country
                    location="Germany",
                    department=department,
                    description="",
                )
            )
            raw.append({"job_id": job_id})
        return jobs, raw

    def _fetch_detail(self, job: Job) -> Job:
        """Fetch a job detail page to extract full location and description."""
        try:
            resp = requests.get(
                _DETAIL_URL.format(job_id=job.ats_job_id),
                headers=_HEADERS,
                timeout=_REQUEST_TIMEOUT,
            )
            if resp.status_code != 200:
                return job

            location = self._extract_location(resp.text) or job.location
            description = self._extract_description(resp.text)
            return replace(job, location=location, description=description)
        except Exception as exc:
            logger.warning("Failed to enrich %s: %s", job.url, exc)
        return job

    def _extract_location(self, html: str) -> str:
        loc_block = re.search(r"list--locations(.*?)</ul>", html, re.DOTALL)
        if not loc_block:
            return ""
        items = re.findall(r"list__item[^>]*>\s*([^\s<][^<]+)", loc_block.group(1))
        if not items:
            return ""
        return _parse_avature_location(items[0].strip())

    def _extract_description(self, html: str) -> str:
        m = re.search(
            r'<div class="article__content__view__field tf_replaceFieldVideoTokens">(.*?)'
            r"</div>\s*</div>\s*</div>",
            html,
            re.DOTALL,
        )
        if not m:
            return ""
        return _strip_html(m.group(1))


def _parse_avature_location(raw: str) -> str:
    """Convert Avature location format 'City -  - Country' to 'City, Country'."""
    m = re.match(r"^(.+?)\s+-\s+-\s+(.+)$", raw)
    if m:
        city, country = m.group(1).strip(), m.group(2).strip()
        return f"{city}, {country}"
    return raw
