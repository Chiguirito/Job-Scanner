from __future__ import annotations

from unittest.mock import MagicMock, patch, call
import xml.etree.ElementTree as ET

import pytest

from src.fetchers.deutschepost import DeutschePostConfig, DeutschePostFetcher
from src.models import Job


def _sitemap_index(sub_urls: list[str]) -> str:
    items = "\n".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in sub_urls)
    return f"""<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  {items}
</sitemapindex>"""


def _sub_sitemap(job_urls: list[str]) -> str:
    items = "\n".join(f"<url><loc>{u}</loc></url>" for u in job_urls)
    return f"""<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  {items}
</urlset>"""


def _job_page(
    title: str = "Software Engineer",
    locality: str = "Bonn",
    country: str = "Germany",
    description: str = "Build great things.",
    job_id: str = "AV-123456",
) -> str:
    return f"""<!DOCTYPE html><html><head>
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "JobPosting",
  "title": "{title}",
  "description": "{description}",
  "identifier": {{"@type": "PropertyValue", "name": "Deutsche Post AG", "value": "{job_id}"}},
  "jobLocation": {{
    "@type": "Place",
    "address": {{
      "@type": "PostalAddress",
      "addressLocality": "{locality}",
      "addressCountry": "{country}"
    }}
  }}
}}
</script>
</head><body></body></html>"""


_JOB_URL = "https://careers.dhl.com/eu/de/job/DPDHGLOBALAV123456DEEUEXTERNAL/Software-Engineer"
_JOB_URL_2 = "https://careers.dhl.com/eu/de/job/DPDHGLOBALAV789012DEEUEXTERNAL/Data-Scientist"


@pytest.fixture
def fetcher() -> DeutschePostFetcher:
    return DeutschePostFetcher(DeutschePostConfig(company="Deutsche Post"))


class TestDeutschePostFetcher:
    @patch("src.fetchers.deutschepost.requests.get")
    def test_fetch_listings_collects_job_urls(
        self, mock_get: MagicMock, fetcher: DeutschePostFetcher
    ) -> None:
        def side_effect(url, **kwargs):
            r = MagicMock()
            r.raise_for_status = MagicMock()
            if "sitemap.xml" in url and "sitemap1" not in url:
                r.text = _sitemap_index(
                    ["https://careers.dhl.com/eu/de/sitemap1.xml"]
                )
            else:
                r.text = _sub_sitemap([_JOB_URL, _JOB_URL_2])
            return r

        mock_get.side_effect = side_effect

        jobs, raw = fetcher.fetch_listings()

        assert len(jobs) == 2
        assert len(raw) == 2
        assert all(isinstance(j, Job) for j in jobs)

    @patch("src.fetchers.deutschepost.requests.get")
    def test_fetch_listings_placeholder_location(
        self, mock_get: MagicMock, fetcher: DeutschePostFetcher
    ) -> None:
        def side_effect(url, **kwargs):
            r = MagicMock()
            r.raise_for_status = MagicMock()
            if "sitemap.xml" in url and "sitemap1" not in url:
                r.text = _sitemap_index(["https://careers.dhl.com/eu/de/sitemap1.xml"])
            else:
                r.text = _sub_sitemap([_JOB_URL])
            return r

        mock_get.side_effect = side_effect

        jobs, _ = fetcher.fetch_listings()

        assert jobs[0].location == "Germany"
        assert jobs[0].title == ""
        assert jobs[0].description == ""

    @patch("src.fetchers.deutschepost.requests.get")
    def test_fetch_listings_extracts_job_id_from_url(
        self, mock_get: MagicMock, fetcher: DeutschePostFetcher
    ) -> None:
        def side_effect(url, **kwargs):
            r = MagicMock()
            r.raise_for_status = MagicMock()
            if "sitemap.xml" in url and "sitemap1" not in url:
                r.text = _sitemap_index(["https://careers.dhl.com/eu/de/sitemap1.xml"])
            else:
                r.text = _sub_sitemap([_JOB_URL])
            return r

        mock_get.side_effect = side_effect

        jobs, _ = fetcher.fetch_listings()

        assert jobs[0].ats_job_id == "DPDHGLOBALAV123456DEEUEXTERNAL"
        assert jobs[0].unique_key == "Deutsche Post::DPDHGLOBALAV123456DEEUEXTERNAL"

    @patch("src.fetchers.deutschepost.requests.get")
    def test_fetch_listings_filters_non_job_urls(
        self, mock_get: MagicMock, fetcher: DeutschePostFetcher
    ) -> None:
        def side_effect(url, **kwargs):
            r = MagicMock()
            r.raise_for_status = MagicMock()
            if "sitemap.xml" in url and "sitemap1" not in url:
                r.text = _sitemap_index(["https://careers.dhl.com/eu/de/sitemap1.xml"])
            else:
                r.text = _sub_sitemap([
                    _JOB_URL,
                    "https://careers.dhl.com/eu/de/jobs-in-hamburg",
                    "https://careers.dhl.com/eu/de/about",
                ])
            return r

        mock_get.side_effect = side_effect

        jobs, _ = fetcher.fetch_listings()

        assert len(jobs) == 1
        assert jobs[0].ats_job_id == "DPDHGLOBALAV123456DEEUEXTERNAL"

    @patch("src.fetchers.deutschepost.requests.get")
    def test_enrich_descriptions_fills_job_fields(
        self, mock_get: MagicMock, fetcher: DeutschePostFetcher
    ) -> None:
        page = _job_page(
            title="Logistics Manager",
            locality="Frankfurt",
            country="Germany",
            description="Manage supply chains.",
        )
        mock_get.return_value.status_code = 200
        mock_get.return_value.text = page

        stub_job = Job(
            title="",
            url=_JOB_URL,
            company="Deutsche Post",
            ats_job_id="DPDHGLOBALAV123456DEEUEXTERNAL",
            location="Germany",
            department="",
            description="",
        )

        enriched = fetcher.enrich_descriptions([stub_job], [{"url": _JOB_URL}])

        assert len(enriched) == 1
        job = enriched[0]
        assert job.title == "Logistics Manager"
        assert "Frankfurt" in job.location
        assert "Germany" in job.location
        assert "supply chains" in job.description

    @patch("src.fetchers.deutschepost.requests.get")
    def test_enrich_descriptions_empty_list_noop(
        self, mock_get: MagicMock, fetcher: DeutschePostFetcher
    ) -> None:
        result = fetcher.enrich_descriptions([], [])

        assert result == []
        mock_get.assert_not_called()

    @patch("src.fetchers.deutschepost.requests.get")
    def test_enrich_descriptions_tolerates_failed_fetch(
        self, mock_get: MagicMock, fetcher: DeutschePostFetcher
    ) -> None:
        mock_get.return_value.status_code = 503

        stub_job = Job(
            title="",
            url=_JOB_URL,
            company="Deutsche Post",
            ats_job_id="DPDHGLOBALAV123456DEEUEXTERNAL",
            location="Germany",
            department="",
            description="",
        )

        enriched = fetcher.enrich_descriptions([stub_job], [{"url": _JOB_URL}])

        assert enriched[0] is stub_job  # unchanged on failure

    @patch("src.fetchers.deutschepost.requests.get")
    def test_fetch_returns_jobs(
        self, mock_get: MagicMock, fetcher: DeutschePostFetcher
    ) -> None:
        def side_effect(url, **kwargs):
            r = MagicMock()
            r.raise_for_status = MagicMock()
            if "sitemap.xml" in url and "sitemap1" not in url:
                r.text = _sitemap_index(["https://careers.dhl.com/eu/de/sitemap1.xml"])
            else:
                r.text = _sub_sitemap([_JOB_URL])
            return r

        mock_get.side_effect = side_effect

        jobs = fetcher.fetch()

        assert len(jobs) == 1
        assert isinstance(jobs[0], Job)
