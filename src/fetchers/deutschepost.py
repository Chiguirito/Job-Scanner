from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from typing import Any

import requests

from src.fetchers.base import BaseFetcher
from src.fetchers.workday import _strip_html
from src.models import Job

logger = logging.getLogger(__name__)

_SITEMAP_ROOT = "https://careers.dhl.com/eu/de/sitemap.xml"
# Matches job IDs like DPDHGLOBALAV328548DEEUEXTERNAL in the URL path
_JOB_ID_RE = re.compile(r"/job/(DPDHGLOBAL\w+DEEUEXTERNAL)/")
_SITEMAP_WORKERS = 10
_DETAIL_WORKERS = 20
_REQUEST_TIMEOUT = 30
_HEADERS = {"User-Agent": "Mozilla/5.0"}


@dataclass
class DeutschePostConfig:
    """Configuration for the Deutsche Post / DHL careers site fetcher."""

    company: str = "Deutsche Post"


class DeutschePostFetcher(BaseFetcher):
    """Fetches Deutsche Post / DHL job postings via XML sitemaps and JSON-LD scraping.

    Uses the EU/DE career site (careers.dhl.com/eu/de) which covers German postings.
    The sitemal.xml feed is disabled on this site, so we fall back to:
      1. fetch_listings(): collect job URLs from the sub-sitemaps (10–15 requests)
      2. enrich_descriptions(): concurrently fetch each new job page for JSON-LD data
    """

    def __init__(self, config: DeutschePostConfig) -> None:
        self.config = config

    def fetch(self) -> list[Job]:
        jobs, _ = self.fetch_listings()
        return jobs

    def fetch_listings(self) -> tuple[list[Job], list[dict[str, Any]]]:
        job_urls = self._collect_job_urls()
        jobs = []
        raw = []
        for url in job_urls:
            m = _JOB_ID_RE.search(url)
            if not m:
                continue
            job_id = m.group(1)
            # Use "Germany" as a placeholder location so the region filter
            # (which matches "Germany" / "DE") passes these jobs through for
            # description enrichment. store.save() does not overwrite location
            # for existing jobs, so this placeholder only affects new ones until
            # enrich_descriptions() replaces it with the real value.
            job = Job(
                title="",
                url=url,
                company=self.config.company,
                ats_job_id=job_id,
                location="Germany",
                department="",
                description="",
            )
            jobs.append(job)
            raw.append({"url": url})
        logger.info("Found %d job listings for %s", len(jobs), self.config.company)
        return jobs, raw

    def enrich_descriptions(
        self, jobs: list[Job], raw_postings: list[dict[str, Any]]
    ) -> list[Job]:
        if not jobs:
            return jobs
        with ThreadPoolExecutor(max_workers=_DETAIL_WORKERS) as executor:
            futures = {executor.submit(self._fetch_job_detail, job): job for job in jobs}
            enriched = [future.result() for future in as_completed(futures)]
        logger.info(
            "Enriched %d job descriptions for %s", len(enriched), self.config.company
        )
        return enriched

    def _collect_job_urls(self) -> list[str]:
        """Fetch the sitemap index then all sub-sitemaps concurrently."""
        resp = requests.get(_SITEMAP_ROOT, timeout=_REQUEST_TIMEOUT, headers=_HEADERS)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        sub_urls = [
            el.text
            for el in root.iter()
            if (el.tag.endswith("}loc") or el.tag == "loc") and el.text
        ]
        all_job_urls: list[str] = []
        with ThreadPoolExecutor(max_workers=_SITEMAP_WORKERS) as executor:
            futures = {
                executor.submit(self._fetch_sitemap_job_urls, url): url
                for url in sub_urls
            }
            for future in as_completed(futures):
                try:
                    all_job_urls.extend(future.result())
                except Exception as exc:
                    logger.warning("Sitemap fetch failed: %s", exc)
        return all_job_urls

    def _fetch_sitemap_job_urls(self, sitemap_url: str) -> list[str]:
        resp = requests.get(sitemap_url, timeout=_REQUEST_TIMEOUT, headers=_HEADERS)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        return [
            el.text
            for el in root.iter()
            if (el.tag.endswith("}loc") or el.tag == "loc")
            and el.text
            and _JOB_ID_RE.search(el.text)
        ]

    def _fetch_job_detail(self, job: Job) -> Job:
        """Fetch a job page and extract JSON-LD JobPosting data."""
        try:
            resp = requests.get(
                job.url, timeout=_REQUEST_TIMEOUT, headers=_HEADERS
            )
            if resp.status_code != 200:
                return job
            json_blocks = re.findall(
                r'application/ld\+json[^>]*>(.*?)</script>', resp.text, re.DOTALL
            )
            for block in json_blocks:
                if "JobPosting" not in block:
                    continue
                data = json.loads(block.strip())
                title = data.get("title", job.title)
                description = _strip_html(data.get("description", ""))
                loc_data = data.get("jobLocation", {})
                if isinstance(loc_data, list):
                    loc_data = loc_data[0] if loc_data else {}
                addr = loc_data.get("address", {}) if isinstance(loc_data, dict) else {}
                if isinstance(addr, dict):
                    locality = addr.get("addressLocality", "")
                    country = addr.get("addressCountry", "")
                    location = f"{locality}, {country}" if locality and country else locality or country
                else:
                    location = job.location
                department = data.get("occupationalCategory", "")
                return replace(
                    job,
                    title=title,
                    location=location,
                    description=description,
                    department=department,
                )
        except Exception as exc:
            logger.warning("Failed to enrich %s: %s", job.url, exc)
        return job
