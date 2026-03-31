from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.fetchers.successfactors import SuccessFactorsConfig, SuccessFactorsFetcher
from src.models import Job

_G_NS = "http://base.google.com/ns/1.0"
_FEED_URL = "https://basf.jobs/sitemal.xml"


def _make_feed(items: list[str]) -> str:
    body = "\n".join(items)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:g="{_G_NS}">
  <channel>
    <title>BASF Careers</title>
    {body}
  </channel>
</rss>"""


def _make_item(
    job_id: str = "REF123456",
    title: str = "Process Engineer (Ludwigshafen, DE)",
    url: str = "https://basf.jobs/BASF/job/Ludwigshafen-Process-Engineer/REF123456/",
    location: str = "Ludwigshafen, DE",
    department: str = "Engineering",
    description: str = "Drive chemical process innovation.",
) -> str:
    return f"""<item>
      <title>{title}</title>
      <description>{description}</description>
      <link>{url}</link>
      <guid isPermaLink="false">{job_id}</guid>
      <g:id>{job_id}</g:id>
      <g:job_function>{department}</g:job_function>
      <g:location>{location}</g:location>
    </item>"""


@pytest.fixture
def fetcher() -> SuccessFactorsFetcher:
    return SuccessFactorsFetcher(SuccessFactorsConfig(company="BASF", feed_url=_FEED_URL))


class TestSuccessFactorsFetcher:
    @patch("src.fetchers.successfactors.requests.get")
    def test_fetch_returns_all_jobs(self, mock_get: MagicMock, fetcher: SuccessFactorsFetcher) -> None:
        feed = _make_feed([_make_item("A1"), _make_item("A2")])
        mock_get.return_value.text = feed
        mock_get.return_value.raise_for_status = MagicMock()

        jobs = fetcher.fetch()

        assert len(jobs) == 2
        assert all(isinstance(j, Job) for j in jobs)

    @patch("src.fetchers.successfactors.requests.get")
    def test_fetch_empty_feed(self, mock_get: MagicMock, fetcher: SuccessFactorsFetcher) -> None:
        mock_get.return_value.text = _make_feed([])
        mock_get.return_value.raise_for_status = MagicMock()

        jobs = fetcher.fetch()

        assert jobs == []

    @patch("src.fetchers.successfactors.requests.get")
    def test_job_fields_mapped_correctly(self, mock_get: MagicMock, fetcher: SuccessFactorsFetcher) -> None:
        item = _make_item(
            job_id="REF123456",
            title="Process Engineer (Ludwigshafen, DE)",
            url="https://basf.jobs/BASF/job/Ludwigshafen-Process-Engineer/REF123456/",
            location="Ludwigshafen, DE",
            department="Engineering",
            description="Drive chemical process innovation.",
        )
        mock_get.return_value.text = _make_feed([item])
        mock_get.return_value.raise_for_status = MagicMock()

        job = fetcher.fetch()[0]

        assert job.title == "Process Engineer (Ludwigshafen, DE)"
        assert job.company == "BASF"
        assert job.ats_job_id == "REF123456"
        assert job.location == "Ludwigshafen, DE"
        assert job.department == "Engineering"
        assert job.url == "https://basf.jobs/BASF/job/Ludwigshafen-Process-Engineer/REF123456/"
        assert "chemical process" in job.description

    @patch("src.fetchers.successfactors.requests.get")
    def test_description_html_is_stripped(self, mock_get: MagicMock, fetcher: SuccessFactorsFetcher) -> None:
        item = _make_item(description="Join &lt;strong&gt;our&lt;/strong&gt; team &amp;amp; grow.")
        mock_get.return_value.text = _make_feed([item])
        mock_get.return_value.raise_for_status = MagicMock()

        job = fetcher.fetch()[0]

        assert "<strong>" not in job.description
        assert "Join" in job.description

    @patch("src.fetchers.successfactors.requests.get")
    def test_fetch_listings_returns_jobs_and_raw(self, mock_get: MagicMock, fetcher: SuccessFactorsFetcher) -> None:
        mock_get.return_value.text = _make_feed([_make_item("A1"), _make_item("A2")])
        mock_get.return_value.raise_for_status = MagicMock()

        jobs, raw = fetcher.fetch_listings()

        assert len(jobs) == 2
        assert len(raw) == 2
        assert mock_get.call_count == 1

    @patch("src.fetchers.successfactors.requests.get")
    def test_enrich_descriptions_is_noop(self, mock_get: MagicMock, fetcher: SuccessFactorsFetcher) -> None:
        mock_get.return_value.text = _make_feed([_make_item()])
        mock_get.return_value.raise_for_status = MagicMock()

        jobs, raw = fetcher.fetch_listings()
        enriched = fetcher.enrich_descriptions(jobs, raw)

        assert enriched is jobs
        assert mock_get.call_count == 1  # no extra requests

    @patch("src.fetchers.successfactors.requests.get")
    def test_unique_key_format(self, mock_get: MagicMock, fetcher: SuccessFactorsFetcher) -> None:
        mock_get.return_value.text = _make_feed([_make_item(job_id="REF999")])
        mock_get.return_value.raise_for_status = MagicMock()

        job = fetcher.fetch()[0]

        assert job.unique_key == "BASF::REF999"

    @patch("src.fetchers.successfactors.requests.get")
    def test_uses_configured_feed_url(self, mock_get: MagicMock, fetcher: SuccessFactorsFetcher) -> None:
        mock_get.return_value.text = _make_feed([])
        mock_get.return_value.raise_for_status = MagicMock()

        fetcher.fetch()

        mock_get.assert_called_once_with(_FEED_URL, timeout=60)

    @patch("src.fetchers.successfactors.requests.get")
    def test_different_company_config(self, mock_get: MagicMock) -> None:
        other_fetcher = SuccessFactorsFetcher(
            SuccessFactorsConfig(company="Acme Corp", feed_url="https://jobs.acme.com/sitemal.xml")
        )
        mock_get.return_value.text = _make_feed([_make_item(job_id="X1")])
        mock_get.return_value.raise_for_status = MagicMock()

        job = other_fetcher.fetch()[0]

        assert job.company == "Acme Corp"
        assert job.unique_key == "Acme Corp::X1"
        mock_get.assert_called_once_with("https://jobs.acme.com/sitemal.xml", timeout=60)
