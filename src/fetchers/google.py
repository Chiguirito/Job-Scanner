from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, timezone
from typing import Any

import requests

from src.fetchers.base import BaseFetcher
from src.fetchers.workday import _strip_html
from src.models import Job

logger = logging.getLogger(__name__)

_FEED_URL = "https://www.google.com/about/careers/applications/jobs/feed.xml"


@dataclass
class GoogleConfig:
    """Configuration for the Google Careers RSS feed fetcher."""

    company: str = "Google"


class GoogleFetcher(BaseFetcher):
    """Fetches job postings from the Google Careers RSS feed.

    Descriptions are included inline in the feed — no separate detail fetch needed.
    """

    def __init__(self, config: GoogleConfig) -> None:
        self.config = config

    def fetch(self) -> list[Job]:
        jobs, _ = self.fetch_listings()
        return jobs

    def fetch_listings(self) -> tuple[list[Job], list[dict[str, Any]]]:
        resp = requests.get(_FEED_URL, timeout=60)
        resp.raise_for_status()

        root = ET.fromstring(resp.text)
        raw_postings = root.findall("job")
        jobs = [self._to_job(el) for el in raw_postings]
        logger.info("Fetched %d jobs from %s", len(jobs), self.config.company)
        return jobs, [{"_el": el} for el in raw_postings]

    def enrich_descriptions(
        self, jobs: list[Job], raw_postings: list[dict[str, Any]]
    ) -> list[Job]:
        """Descriptions are already included in the feed — nothing to enrich."""
        return jobs

    def _to_job(self, el: ET.Element) -> Job:
        loc_el = el.find("locations/location")
        if loc_el is not None:
            city = loc_el.findtext("city", "")
            country = loc_el.findtext("country", "")
            location = f"{city}, {country}".strip(", ")
        else:
            location = ""

        published_str = el.findtext("published", "")
        try:
            posted = date.fromisoformat(published_str[:10])
        except (ValueError, TypeError):
            posted = None

        return Job(
            title=el.findtext("title", ""),
            url=el.findtext("url", ""),
            company=self.config.company,
            ats_job_id=el.findtext("jobid", ""),
            location=location,
            department=el.findtext("employer", ""),
            description=_strip_html(el.findtext("description", "")),
            posted_date=posted,
        )
