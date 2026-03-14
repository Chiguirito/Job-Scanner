from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

import requests

from src.fetchers.base import BaseFetcher
from src.fetchers.workday import _strip_html
from src.models import Job

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://jobs.api.mercedes-benz.com/search"
_PAGE_SIZE = 100


@dataclass
class MercedesBenzConfig:
    """Configuration for the Mercedes-Benz Careers fetcher."""

    company: str = "Mercedes-Benz"


class MercedesBenzFetcher(BaseFetcher):
    """Fetches job postings from the Mercedes-Benz Careers internal JSON API.

    The API is undocumented but publicly accessible — it backs the jobs.mercedes-benz.com
    Nuxt.js frontend. Descriptions are included inline, so no separate detail fetch needed.
    """

    _HEADERS = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Referer": "https://jobs.mercedes-benz.com/",
        "Origin": "https://jobs.mercedes-benz.com",
    }

    def __init__(self, config: MercedesBenzConfig) -> None:
        self.config = config

    def fetch(self) -> list[Job]:
        jobs, _ = self.fetch_listings()
        return jobs

    def fetch_listings(self) -> tuple[list[Job], list[dict[str, Any]]]:
        raw_postings = self._fetch_all_postings()
        jobs = [self._to_job(p) for p in raw_postings]
        logger.info("Fetched %d jobs from %s", len(jobs), self.config.company)
        return jobs, raw_postings

    def enrich_descriptions(
        self, jobs: list[Job], raw_postings: list[dict[str, Any]]
    ) -> list[Job]:
        """Descriptions are already included in the search response — nothing to enrich."""
        return jobs

    def _fetch_all_postings(self) -> list[dict[str, Any]]:
        postings: list[dict[str, Any]] = []
        offset = 0

        while True:
            resp = requests.get(
                _SEARCH_URL,
                headers=self._HEADERS,
                params={"from": offset, "size": _PAGE_SIZE},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

            result = data.get("SearchResult", {})
            items = result.get("SearchResultItems", [])
            postings.extend(i["MatchedObjectDescriptor"] for i in items if "MatchedObjectDescriptor" in i)

            total = result.get("SearchResultCountAll", 0)
            offset += len(items)
            if offset >= total or not items:
                break

        return postings

    def _to_job(self, p: dict[str, Any]) -> Job:
        locations = p.get("PositionLocation") or []
        if isinstance(locations, list) and locations:
            loc = locations[0]
            city = loc.get("CityName", "")
            country_code = loc.get("CountryCode", "")
            location = f"{city}, {country_code}".strip(", ")
        else:
            location = ""

        descriptions = p.get("PositionFormattedDescription") or []
        if isinstance(descriptions, list) and descriptions:
            raw_desc = descriptions[0].get("Tasks", "") or descriptions[0].get("Content", "")
        else:
            raw_desc = ""

        categories = p.get("JobCategory") or []
        department = categories[0].get("Name", "") if categories else ""

        posted_str = p.get("PublicationStartDate", "")
        try:
            posted = date.fromisoformat(posted_str[:10])
        except (ValueError, TypeError):
            posted = None

        return Job(
            title=p.get("PositionTitle", ""),
            url=p.get("PositionURI", ""),
            company=self.config.company,
            ats_job_id=p.get("ID", ""),
            location=location,
            department=department,
            description=_strip_html(raw_desc),
            posted_date=posted,
        )
