from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.fetchers.bmw import BMWConfig, BMWFetcher, _parse_job_page
from src.models import Job


def _make_sitemap(job_ids: list[str]) -> str:
    urls = "".join(
        f"<url><loc>https://www.bmwgroup.jobs/en/jobfinder/job-description-copy.{jid}.html</loc></url>"
        for jid in job_ids
    )
    return f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'


def _make_job_page(
    title: str = "Software Engineer",
    location: str = "Munich",
    department: str = "IT",
    description: str = "Build great software.",
    pub_date: str = "01.03.2026",
    job_id: str = "123456",
) -> str:
    return f"""<html><body>
    <section class="grp-jobdescription">
        <span class="cmp-title__text-title1">{title}</span>
        <div class="grp-jobdescription__jobLocation">{location}</div>
        <div class="grp-jobdescription__jobField">{department}</div>
        <div class="cmp-text" itemprop="description">{description}</div>
        <div class="grp-jobdescription__attributes">
            <div>Job ID:</div>
            <div class="grp-jobdescription__item grp-jobdescription__jobid" itemprop="identifier">{job_id}</div>
            <div>Publication Date:</div>
            <div class="grp-jobdescription__item">{pub_date}</div>
        </div>
    </section>
    </body></html>"""


@pytest.fixture
def fetcher() -> BMWFetcher:
    return BMWFetcher(BMWConfig(company="BMW Group"))


class TestBMWFetcher:
    @patch("src.fetchers.bmw.requests.get")
    def test_fetch_returns_jobs(self, mock_get: MagicMock, fetcher: BMWFetcher) -> None:
        sitemap = _make_sitemap(["111", "222"])
        page = _make_job_page(location="Munich", job_id="111")

        def side_effect(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if "sitemap" in url:
                resp.text = sitemap
            else:
                resp.text = page
            return resp

        mock_get.side_effect = side_effect

        jobs = fetcher.fetch()

        assert len(jobs) == 2
        assert all(isinstance(j, Job) for j in jobs)

    @patch("src.fetchers.bmw.requests.get")
    def test_fetch_empty_sitemap(self, mock_get: MagicMock, fetcher: BMWFetcher) -> None:
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.text = _make_sitemap([])
        mock_get.return_value = resp

        jobs = fetcher.fetch()

        assert jobs == []

    @patch("src.fetchers.bmw.requests.get")
    def test_failed_job_page_is_skipped(self, mock_get: MagicMock, fetcher: BMWFetcher) -> None:
        sitemap = _make_sitemap(["111", "222"])

        call_count = 0

        def side_effect(url, **kwargs):
            nonlocal call_count
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if "sitemap" in url:
                resp.text = sitemap
            elif "111" in url:
                resp.raise_for_status.side_effect = Exception("timeout")
            else:
                resp.text = _make_job_page(job_id="222")
            return resp

        mock_get.side_effect = side_effect

        jobs = fetcher.fetch()

        assert len(jobs) == 1
        assert jobs[0].ats_job_id == "222"

    @patch("src.fetchers.bmw.requests.get")
    def test_fetch_listings_returns_jobs_and_raw(
        self, mock_get: MagicMock, fetcher: BMWFetcher
    ) -> None:
        def side_effect(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if "sitemap" in url:
                resp.text = _make_sitemap(["111"])
            else:
                resp.text = _make_job_page(job_id="111")
            return resp

        mock_get.side_effect = side_effect

        jobs, raw = fetcher.fetch_listings()

        assert len(jobs) == 1
        assert len(raw) == 1
        assert raw[0]["url"] == jobs[0].url

    @patch("src.fetchers.bmw.requests.get")
    def test_enrich_descriptions_is_noop(
        self, mock_get: MagicMock, fetcher: BMWFetcher
    ) -> None:
        def side_effect(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if "sitemap" in url:
                resp.text = _make_sitemap(["111"])
            else:
                resp.text = _make_job_page(job_id="111")
            return resp

        mock_get.side_effect = side_effect

        jobs, raw = fetcher.fetch_listings()
        call_count_after_listings = mock_get.call_count
        enriched = fetcher.enrich_descriptions(jobs, raw)

        assert enriched is jobs
        assert mock_get.call_count == call_count_after_listings  # no extra requests


class TestParseBMWJobPage:
    def test_fields_parsed_correctly(self) -> None:
        page = _make_job_page(
            title="Senior Engineer",
            location="Munich, DE",
            department="IT & Digital",
            description="<p>Build <b>great</b> things.</p>",
            pub_date="15.03.2026",
            job_id="180561",
        )
        url = "https://www.bmwgroup.jobs/en/jobfinder/job-description-copy.180561.html"

        job = _parse_job_page(page, "180561", url, "BMW Group")

        assert job.title == "Senior Engineer"
        assert job.location == "Munich, DE"
        assert job.department == "IT & Digital"
        assert job.ats_job_id == "180561"
        assert job.company == "BMW Group"
        assert job.url == url
        assert "Build great things" in job.description
        assert "<p>" not in job.description

    def test_publication_date_parsed(self) -> None:
        page = _make_job_page(pub_date="15.03.2026")
        job = _parse_job_page(page, "1", "http://x", "BMW")
        from datetime import date
        assert job.posted_date == date(2026, 3, 15)

    def test_missing_fields_return_empty_strings(self) -> None:
        job = _parse_job_page("<html><body></body></html>", "999", "http://x", "BMW")
        assert job.title == ""
        assert job.location == ""
        assert job.department == ""
        assert job.description == ""
        assert job.posted_date is None

    def test_html_stripped_from_description(self) -> None:
        page = _make_job_page(description="<ul><li>Task A</li><li>Task B</li></ul>")
        job = _parse_job_page(page, "1", "http://x", "BMW")
        assert "<li>" not in job.description
        assert "Task A" in job.description

    def test_unique_key_format(self) -> None:
        page = _make_job_page(job_id="180561")
        job = _parse_job_page(page, "180561", "http://x", "BMW Group")
        assert job.unique_key == "BMW Group::180561"
