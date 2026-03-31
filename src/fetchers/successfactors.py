from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import requests

from src.fetchers.base import BaseFetcher
from src.fetchers.workday import _strip_html
from src.models import Job

logger = logging.getLogger(__name__)

_G_NS = "http://base.google.com/ns/1.0"


@dataclass
class SuccessFactorsConfig:
    """Configuration for a generic SAP SuccessFactors Recruiting Marketing feed fetcher."""

    company: str
    feed_url: str


class SuccessFactorsFetcher(BaseFetcher):
    """Fetches job postings from a SAP SuccessFactors Recruiting Marketing sitemal.xml feed.

    The sitemal.xml endpoint is available on all SuccessFactors Recruiting Marketing
    instances and returns a Google Base RSS feed with descriptions included inline —
    no separate detail fetch needed.
    """

    def __init__(self, config: SuccessFactorsConfig) -> None:
        self.config = config

    def fetch(self) -> list[Job]:
        jobs, _ = self.fetch_listings()
        return jobs

    def fetch_listings(self) -> tuple[list[Job], list[dict[str, Any]]]:
        resp = requests.get(self.config.feed_url, timeout=60)
        resp.raise_for_status()

        root = ET.fromstring(resp.text)
        channel = root.find("channel")
        raw_items = channel.findall("item") if channel is not None else []
        jobs = [self._to_job(el) for el in raw_items]
        logger.info("Fetched %d jobs from %s", len(jobs), self.config.company)
        return jobs, [{"_el": el} for el in raw_items]

    def enrich_descriptions(
        self, jobs: list[Job], raw_postings: list[dict[str, Any]]
    ) -> list[Job]:
        """Descriptions are already included in the feed — nothing to enrich."""
        return jobs

    def _to_job(self, el: ET.Element) -> Job:
        job_id = el.findtext("guid", "") or el.findtext(f"{{{_G_NS}}}id", "")
        location = el.findtext(f"{{{_G_NS}}}location", "")
        department = el.findtext(f"{{{_G_NS}}}job_function", "")
        description = _strip_html(el.findtext("description", "") or "")

        return Job(
            title=el.findtext("title", ""),
            url=el.findtext("link", ""),
            company=self.config.company,
            ats_job_id=job_id,
            location=location,
            department=department,
            description=description,
        )
