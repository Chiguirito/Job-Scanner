from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

from src.fetchers.base import BaseFetcher
from src.fetchers.workday import _strip_html
from src.models import Job

logger = logging.getLogger(__name__)

_SITEMAP_URL = "https://verbund.edeka/sitemap-job.xml"
_DETAIL_WORKERS = 20
_REQUEST_TIMEOUT = 30
_HEADERS = {"User-Agent": "Mozilla/5.0"}


@dataclass
class EdekaConfig:
    company: str = "Edeka"


class EdekaFetcher(BaseFetcher):
    """Fetches Edeka job postings via sitemap-job.xml and JSON-LD page scraping.

    verbund.edeka uses d.vinci ATS with a CORS-protected API. The public career
    site exposes a standard XML sitemap listing all job URLs, and each job page
    includes JSON-LD JobPosting structured data with full details.
    """

    def __init__(self, config: EdekaConfig) -> None:
        self.config = config

    def fetch(self) -> list[Job]:
        jobs, raw = self.fetch_listings()
        return self.enrich_descriptions(jobs, raw)

    def fetch_listings(self) -> tuple[list[Job], list[dict[str, Any]]]:
        resp = requests.get(_SITEMAP_URL, timeout=_REQUEST_TIMEOUT, headers=_HEADERS)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        job_urls = [
            el.text
            for el in root.iter()
            if (el.tag.endswith("}loc") or el.tag == "loc") and el.text
        ]
        jobs = []
        raw = []
        for url in job_urls:
            job_id = self._extract_job_id(url)
            if not job_id:
                continue
            # "Germany" placeholder so region filter passes; overwritten by enrich_descriptions()
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

    def _extract_job_id(self, url: str) -> str | None:
        qs = parse_qs(urlparse(url).query)
        ids = qs.get("id", [])
        return ids[0] if ids else None

    def _fetch_job_detail(self, job: Job) -> Job:
        """Fetch a job page and extract JSON-LD JobPosting data."""
        try:
            resp = requests.get(job.url, timeout=_REQUEST_TIMEOUT, headers=_HEADERS)
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
                    location = (
                        f"{locality}, {country}" if locality and country else locality or country
                    )
                else:
                    location = job.location
                department = data.get("occupationalCategory", "")
                return replace(
                    job,
                    title=title,
                    location=location or job.location,
                    description=description,
                    department=department,
                )
        except Exception as exc:
            logger.warning("Failed to enrich %s: %s", job.url, exc)
        return job
