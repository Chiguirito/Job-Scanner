from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.fetchers.volkswagen import VolkswagenConfig, VolkswagenFetcher
from src.models import Job

_G_NS = "http://base.google.com/ns/1.0"


def _make_feed(items: list[str]) -> str:
    body = "\n".join(items)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:g="{_G_NS}">
  <channel>
    <title>Your job at the Volkswagen Group</title>
    {body}
  </channel>
</rss>"""


def _make_item(
    job_id: str = "1271811901",
    title: str = "Software Engineer (Berlin, DE, 10587)",
    url: str = "https://jobs.volkswagen-group.com/Volkswagen/job/Berlin-Software-Engineer/1271811901/",
    location: str = "Berlin, DE, 10587",
    department: str = "IT Digitalisation",
    description: str = "Build great things.",
) -> str:
    return f"""<item>
      <title>{title}</title>
      <description>{description}</description>
      <link>{url}</link>
      <guid isPermaLink="false">{job_id}</guid>
      <g:id>{job_id}</g:id>
      <g:expiration_date>2026-04-14</g:expiration_date>
      <g:employer>Volkswagen AG</g:employer>
      <g:job_function>{department}</g:job_function>
      <g:location>{location}</g:location>
    </item>"""


@pytest.fixture
def fetcher() -> VolkswagenFetcher:
    return VolkswagenFetcher(VolkswagenConfig(company="Volkswagen"))


class TestVolkswagenFetcher:
    @patch("src.fetchers.volkswagen.requests.get")
    def test_fetch_returns_all_jobs(self, mock_get: MagicMock, fetcher: VolkswagenFetcher) -> None:
        feed = _make_feed([_make_item("111"), _make_item("222")])
        mock_get.return_value.text = feed
        mock_get.return_value.raise_for_status = MagicMock()

        jobs = fetcher.fetch()

        assert len(jobs) == 2
        assert all(isinstance(j, Job) for j in jobs)

    @patch("src.fetchers.volkswagen.requests.get")
    def test_fetch_empty_feed(self, mock_get: MagicMock, fetcher: VolkswagenFetcher) -> None:
        mock_get.return_value.text = _make_feed([])
        mock_get.return_value.raise_for_status = MagicMock()

        jobs = fetcher.fetch()

        assert jobs == []

    @patch("src.fetchers.volkswagen.requests.get")
    def test_job_fields_mapped_correctly(self, mock_get: MagicMock, fetcher: VolkswagenFetcher) -> None:
        item = _make_item(
            job_id="1271811901",
            title="ML Engineer (Berlin, DE, 10587)",
            url="https://jobs.volkswagen-group.com/Volkswagen/job/Berlin-ML-Engineer/1271811901/",
            location="Berlin, DE, 10587",
            department="IT Digitalisation",
            description="Build ML models.",
        )
        mock_get.return_value.text = _make_feed([item])
        mock_get.return_value.raise_for_status = MagicMock()

        job = fetcher.fetch()[0]

        assert job.title == "ML Engineer (Berlin, DE, 10587)"
        assert job.company == "Volkswagen"
        assert job.ats_job_id == "1271811901"
        assert job.location == "Berlin, DE, 10587"
        assert job.department == "IT Digitalisation"
        assert job.url == "https://jobs.volkswagen-group.com/Volkswagen/job/Berlin-ML-Engineer/1271811901/"
        assert "Build ML models" in job.description

    @patch("src.fetchers.volkswagen.requests.get")
    def test_description_html_is_stripped(self, mock_get: MagicMock, fetcher: VolkswagenFetcher) -> None:
        item = _make_item(description="Join &lt;strong&gt;our&lt;/strong&gt; team &amp;amp; grow.")
        mock_get.return_value.text = _make_feed([item])
        mock_get.return_value.raise_for_status = MagicMock()

        job = fetcher.fetch()[0]

        assert "<strong>" not in job.description
        assert "Join" in job.description

    @patch("src.fetchers.volkswagen.requests.get")
    def test_fetch_listings_returns_jobs_and_raw(self, mock_get: MagicMock, fetcher: VolkswagenFetcher) -> None:
        mock_get.return_value.text = _make_feed([_make_item("111"), _make_item("222")])
        mock_get.return_value.raise_for_status = MagicMock()

        jobs, raw = fetcher.fetch_listings()

        assert len(jobs) == 2
        assert len(raw) == 2
        assert mock_get.call_count == 1

    @patch("src.fetchers.volkswagen.requests.get")
    def test_enrich_descriptions_is_noop(self, mock_get: MagicMock, fetcher: VolkswagenFetcher) -> None:
        mock_get.return_value.text = _make_feed([_make_item()])
        mock_get.return_value.raise_for_status = MagicMock()

        jobs, raw = fetcher.fetch_listings()
        enriched = fetcher.enrich_descriptions(jobs, raw)

        assert enriched is jobs
        assert mock_get.call_count == 1  # no extra requests

    @patch("src.fetchers.volkswagen.requests.get")
    def test_unique_key_format(self, mock_get: MagicMock, fetcher: VolkswagenFetcher) -> None:
        mock_get.return_value.text = _make_feed([_make_item(job_id="9999")])
        mock_get.return_value.raise_for_status = MagicMock()

        job = fetcher.fetch()[0]

        assert job.unique_key == "Volkswagen::9999"
