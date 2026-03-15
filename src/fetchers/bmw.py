from __future__ import annotations

import html as html_mod
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from typing import Any

import requests

from src.fetchers.base import BaseFetcher
from src.models import Job

logger = logging.getLogger(__name__)

_SITEMAP_URL = "https://www.bmwgroup.jobs/sitemap.xml"
_JOB_ID_RE = re.compile(
    r"https://www\.bmwgroup\.jobs/en/jobfinder/job-description-copy\.(\d+)\.html"
)
_JOB_PAGE_URL = "https://www.bmwgroup.jobs/en/jobfinder/job-description-copy.{}.html"
_FETCH_WORKERS = 20
# Standard browser UA — works from real user networks; Akamai's bot detection
# primarily targets cloud/proxy IPs, not individual end-user machines.
_HEADERS = {"User-Agent": "Mozilla/5.0"}


@dataclass
class BMWConfig:
    """Configuration for the BMW Group careers site fetcher."""

    company: str = "BMW Group"


class BMWFetcher(BaseFetcher):
    """Fetches job postings from BMW Group careers site (bmwgroup.jobs).

    BMW does not expose a structured JSON/RSS API. The sitemap is used to
    discover all ~1000 job IDs; pages are then fetched concurrently to extract
    title, location, department, and description. Descriptions are included
    inline, so enrich_descriptions() is a no-op.
    """

    def __init__(self, config: BMWConfig) -> None:
        self.config = config

    def fetch(self) -> list[Job]:
        jobs, _ = self.fetch_listings()
        return jobs

    def fetch_listings(self) -> tuple[list[Job], list[dict[str, Any]]]:
        job_ids = self._get_job_ids_from_sitemap()

        jobs: list[Job] = []
        with ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as executor:
            futures = {
                executor.submit(self._fetch_job, job_id): job_id for job_id in job_ids
            }
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    jobs.append(result)

        logger.info("Fetched %d jobs from %s", len(jobs), self.config.company)
        return jobs, [{"url": j.url} for j in jobs]

    def enrich_descriptions(
        self, jobs: list[Job], raw_postings: list[dict[str, Any]]
    ) -> list[Job]:
        """Descriptions are already included in fetch_listings() — nothing to enrich."""
        return jobs

    def _get_job_ids_from_sitemap(self) -> list[str]:
        """Fetch the sitemap and return deduplicated job IDs in order."""
        resp = requests.get(_SITEMAP_URL, headers=_HEADERS, timeout=30)
        resp.raise_for_status()
        return list(dict.fromkeys(_JOB_ID_RE.findall(resp.text)))

    def _fetch_job(self, job_id: str) -> Job | None:
        """Fetch one job detail page and return a parsed Job, or None on failure."""
        url = _JOB_PAGE_URL.format(job_id)
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=30)
            resp.raise_for_status()
            return _parse_job_page(resp.text, job_id, url, self.config.company)
        except Exception:
            logger.warning("Failed to fetch BMW job %s", job_id)
            return None


def _parse_job_page(page_html: str, job_id: str, url: str, company: str) -> Job:
    """Extract job fields from a BMW career page HTML."""
    title_m = re.search(
        r'cmp-title__text-title1">\s*(.*?)\s*</span>', page_html, re.DOTALL
    )
    title = _clean(title_m.group(1)) if title_m else ""

    loc_m = re.search(
        r'grp-jobdescription__jobLocation">\s*(.*?)\s*</div>', page_html, re.DOTALL
    )
    location = _clean(loc_m.group(1)) if loc_m else ""

    field_m = re.search(
        r'grp-jobdescription__jobField">\s*(.*?)\s*</div>', page_html, re.DOTALL
    )
    department = _clean(field_m.group(1)) if field_m else ""

    desc_m = re.search(r'itemprop="description">(.*?)</div>', page_html, re.DOTALL)
    description = _clean(desc_m.group(1)) if desc_m else ""

    posted_date: date | None = None
    pub_m = re.search(
        r"Publication Date:</div>\s*<div[^>]*>\s*(\d{2}\.\d{2}\.\d{4})",
        page_html,
        re.DOTALL,
    )
    if pub_m:
        try:
            d, m, y = pub_m.group(1).split(".")
            posted_date = date(int(y), int(m), int(d))
        except (ValueError, AttributeError):
            pass

    return Job(
        title=title,
        url=url,
        company=company,
        ats_job_id=job_id,
        location=location,
        department=department,
        description=description,
        posted_date=posted_date,
    )


def _clean(text: str) -> str:
    """Strip HTML tags, decode entities, and collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_mod.unescape(text)
    return re.sub(r"\s+", " ", text).strip()
