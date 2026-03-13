from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.fetchers.greenhouse import GreenhouseConfig, GreenhouseFetcher
from src.models import Job


@pytest.fixture
def config() -> GreenhouseConfig:
    return GreenhouseConfig(
        company="Waymo",
        board_slug="waymo",
        fetch_descriptions=False,
    )


@pytest.fixture
def fetcher(config: GreenhouseConfig) -> GreenhouseFetcher:
    return GreenhouseFetcher(config)


def _make_listing(
    job_id: int = 1001,
    title: str = "Software Engineer",
    location: str = "Munich, Germany",
    department: str = "Engineering",
) -> dict:
    return {
        "id": job_id,
        "title": title,
        "absolute_url": f"https://careers.withwaymo.com/jobs/{job_id}",
        "location": {"name": location},
        "departments": [{"id": 1, "name": department}],
    }


def _make_detail(job_id: int = 1001, content: str = "<p>Great job</p>") -> dict:
    return {
        "id": job_id,
        "title": "Software Engineer",
        "content": content,
        "absolute_url": f"https://careers.withwaymo.com/jobs/{job_id}",
        "location": {"name": "Munich, Germany"},
        "departments": [{"id": 1, "name": "Engineering"}],
    }


class TestGreenhouseFetcher:
    @patch("src.fetchers.greenhouse.requests.get")
    def test_fetch_returns_all_jobs(self, mock_get: MagicMock, fetcher: GreenhouseFetcher) -> None:
        listings = [_make_listing(1001), _make_listing(1002)]
        mock_get.return_value.json.return_value = {"jobs": listings}
        mock_get.return_value.raise_for_status = MagicMock()

        jobs = fetcher.fetch()

        assert len(jobs) == 2
        assert all(isinstance(j, Job) for j in jobs)

    @patch("src.fetchers.greenhouse.requests.get")
    def test_fetch_empty_board(self, mock_get: MagicMock, fetcher: GreenhouseFetcher) -> None:
        mock_get.return_value.json.return_value = {"jobs": []}
        mock_get.return_value.raise_for_status = MagicMock()

        jobs = fetcher.fetch()

        assert jobs == []

    @patch("src.fetchers.greenhouse.requests.get")
    def test_job_fields_mapped_correctly(self, mock_get: MagicMock, fetcher: GreenhouseFetcher) -> None:
        listing = _make_listing(job_id=7028592, title="ML Engineer", location="Berlin, Germany", department="Research")
        mock_get.return_value.json.return_value = {"jobs": [listing]}
        mock_get.return_value.raise_for_status = MagicMock()

        job = fetcher.fetch()[0]

        assert job.title == "ML Engineer"
        assert job.company == "Waymo"
        assert job.ats_job_id == "7028592"
        assert job.location == "Berlin, Germany"
        assert job.department == "Research"
        assert job.url == "https://careers.withwaymo.com/jobs/7028592"

    @patch("src.fetchers.greenhouse.requests.get")
    def test_job_without_department(self, mock_get: MagicMock, fetcher: GreenhouseFetcher) -> None:
        listing = {
            "id": 999,
            "title": "Designer",
            "absolute_url": "https://careers.withwaymo.com/jobs/999",
            "location": {"name": "Remote"},
            "departments": [],
        }
        mock_get.return_value.json.return_value = {"jobs": [listing]}
        mock_get.return_value.raise_for_status = MagicMock()

        job = fetcher.fetch()[0]

        assert job.department == ""
        assert job.location == "Remote"

    @patch("src.fetchers.greenhouse.requests.get")
    def test_fetch_listings_does_not_fetch_descriptions(
        self, mock_get: MagicMock, fetcher: GreenhouseFetcher
    ) -> None:
        mock_get.return_value.json.return_value = {"jobs": [_make_listing()]}
        mock_get.return_value.raise_for_status = MagicMock()

        jobs, raw = fetcher.fetch_listings()

        assert mock_get.call_count == 1  # only the listings endpoint
        assert jobs[0].description == ""


class TestGreenhouseFetcherWithDescriptions:
    @patch("src.fetchers.greenhouse.requests.get")
    def test_enrich_fetches_description(self, mock_get: MagicMock, config: GreenhouseConfig) -> None:
        config.fetch_descriptions = True
        fetcher = GreenhouseFetcher(config)

        listing = _make_listing(job_id=7028592)
        detail = _make_detail(job_id=7028592, content="<p>Build <b>ML</b> models</p>")

        mock_get.return_value.raise_for_status = MagicMock()
        mock_get.return_value.json.side_effect = [{"jobs": [listing]}, detail]

        job = fetcher.fetch()[0]

        assert "Build ML models" in job.description

    @patch("src.fetchers.greenhouse.requests.get")
    def test_enrich_handles_detail_failure_gracefully(
        self, mock_get: MagicMock, config: GreenhouseConfig
    ) -> None:
        config.fetch_descriptions = True
        fetcher = GreenhouseFetcher(config)

        listing = _make_listing(job_id=1001)
        mock_get.return_value.raise_for_status = MagicMock()
        mock_get.return_value.json.return_value = {"jobs": [listing]}

        # Second call (detail fetch) raises
        mock_get.side_effect = [
            MagicMock(json=MagicMock(return_value={"jobs": [listing]}), raise_for_status=MagicMock()),
            Exception("connection error"),
        ]

        job = fetcher.fetch()[0]

        assert job.description == ""
        assert job.ats_job_id == "1001"
