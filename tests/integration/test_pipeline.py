from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.fetchers.workday import WorkdayConfig, WorkdayFetcher
from src.main import filter_by_region, process_company
from src.store import JobStore

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def workday_config() -> WorkdayConfig:
    return WorkdayConfig(
        company="NVIDIA",
        base_url="https://nvidia.wd5.myworkdayjobs.com",
        site_path="/wday/cxs/nvidia/NVIDIAExternalCareerSite",
        site_name="NVIDIAExternalCareerSite",
        fetch_descriptions=False,
    )


@pytest.fixture
def listings_response() -> dict:
    return json.loads((FIXTURES / "workday_listings.json").read_text())


@pytest.fixture
def detail_responses() -> dict:
    return {
        "JR1234567": json.loads((FIXTURES / "workday_detail_jr1234567.json").read_text()),
        "JR7654321": json.loads((FIXTURES / "workday_detail_jr7654321.json").read_text()),
    }


class TestFetchFilterStorePipeline:
    """Wires WorkdayFetcher → filter_by_region → JobStore using fixture data."""

    @patch("src.fetchers.workday.requests.post")
    def test_region_filter_drops_non_germany_jobs(
        self, mock_post: MagicMock, workday_config: WorkdayConfig, listings_response: dict, tmp_path: Path
    ) -> None:
        mock_post.return_value.json.return_value = listings_response
        mock_post.return_value.raise_for_status = MagicMock()

        fetcher = WorkdayFetcher(workday_config)
        jobs, raw = fetcher.fetch_listings()

        jobs, raw = filter_by_region(jobs, raw, ["Germany"])

        assert len(jobs) == 2
        assert all(j.location.startswith("Germany") for j in jobs)
        assert all(j.company == "NVIDIA" for j in jobs)

    @patch("src.fetchers.workday.requests.get")
    @patch("src.fetchers.workday.requests.post")
    def test_descriptions_fetched_after_region_filter(
        self,
        mock_post: MagicMock,
        mock_get: MagicMock,
        workday_config: WorkdayConfig,
        listings_response: dict,
        detail_responses: dict,
        tmp_path: Path,
    ) -> None:
        workday_config.fetch_descriptions = False
        mock_post.return_value.json.return_value = listings_response
        mock_post.return_value.raise_for_status = MagicMock()

        detail_calls = [
            MagicMock(json=MagicMock(return_value=detail_responses["JR1234567"]), raise_for_status=MagicMock()),
            MagicMock(json=MagicMock(return_value=detail_responses["JR7654321"]), raise_for_status=MagicMock()),
        ]
        mock_get.side_effect = detail_calls

        fetcher = WorkdayFetcher(workday_config)
        jobs, raw = fetcher.fetch_listings()
        jobs, raw = filter_by_region(jobs, raw, ["Germany"])
        jobs = fetcher.enrich_descriptions(jobs, raw)

        assert len(jobs) == 2
        assert "Senior Software Engineer" in jobs[0].description or "ML Research" in jobs[0].description
        assert all(j.description != "" for j in jobs)
        assert all(j.department != "" for j in jobs)
        # Descriptions were only fetched for the 2 Germany jobs, not the US one
        assert mock_get.call_count == 2

    @patch("src.fetchers.workday.requests.get")
    @patch("src.fetchers.workday.requests.post")
    def test_new_jobs_saved_to_store(
        self,
        mock_post: MagicMock,
        mock_get: MagicMock,
        workday_config: WorkdayConfig,
        listings_response: dict,
        detail_responses: dict,
        tmp_path: Path,
    ) -> None:
        mock_post.return_value.json.return_value = listings_response
        mock_post.return_value.raise_for_status = MagicMock()

        detail_calls = [
            MagicMock(json=MagicMock(return_value=detail_responses["JR1234567"]), raise_for_status=MagicMock()),
            MagicMock(json=MagicMock(return_value=detail_responses["JR7654321"]), raise_for_status=MagicMock()),
        ]
        mock_get.side_effect = detail_calls

        fetcher = WorkdayFetcher(workday_config)
        store = JobStore(db_path=tmp_path / "jobs.db")

        jobs, raw = fetcher.fetch_listings()
        jobs, raw = filter_by_region(jobs, raw, ["Germany"])
        jobs = fetcher.enrich_descriptions(jobs, raw)
        new_jobs = store.filter_new(jobs)

        assert len(new_jobs) == 2
        assert store.count() == 2
        assert store.count(active_only=True) == 2
        store.close()

    @patch("src.fetchers.workday.requests.post")
    def test_second_run_deduplicates(
        self, mock_post: MagicMock, workday_config: WorkdayConfig, listings_response: dict, tmp_path: Path
    ) -> None:
        mock_post.return_value.json.return_value = listings_response
        mock_post.return_value.raise_for_status = MagicMock()

        fetcher = WorkdayFetcher(workday_config)
        store = JobStore(db_path=tmp_path / "jobs.db")

        jobs, raw = fetcher.fetch_listings()
        jobs, _ = filter_by_region(jobs, raw, ["Germany"])

        store.filter_new(jobs)
        new_on_second_run = store.filter_new(jobs)

        assert new_on_second_run == []
        assert store.count() == 2
        store.close()


class TestProcessCompany:
    """Integration tests for the process_company pipeline function."""

    @patch("src.fetchers.workday.requests.get")
    @patch("src.fetchers.workday.requests.post")
    def test_new_jobs_get_descriptions(
        self,
        mock_post: MagicMock,
        mock_get: MagicMock,
        listings_response: dict,
        detail_responses: dict,
    ) -> None:
        mock_post.return_value.json.return_value = listings_response
        mock_post.return_value.raise_for_status = MagicMock()
        mock_get.side_effect = [
            MagicMock(json=MagicMock(return_value=detail_responses["JR1234567"]), raise_for_status=MagicMock()),
            MagicMock(json=MagicMock(return_value=detail_responses["JR7654321"]), raise_for_status=MagicMock()),
        ]

        company_cfg = {
            "name": "NVIDIA",
            "ats": "workday",
            "config": {
                "base_url": "https://nvidia.wd5.myworkdayjobs.com",
                "site_path": "/wday/cxs/nvidia/NVIDIAExternalCareerSite",
                "site_name": "NVIDIAExternalCareerSite",
            },
        }
        name, new_jobs, seen_jobs, active_keys = process_company(company_cfg, ["Germany"], known_keys=set())

        assert name == "NVIDIA"
        assert len(new_jobs) == 2
        assert seen_jobs == []
        assert all(j.description != "" for j in new_jobs)
        assert mock_get.call_count == 2

    @patch("src.fetchers.workday.requests.get")
    @patch("src.fetchers.workday.requests.post")
    def test_known_jobs_skip_description_fetch(
        self,
        mock_post: MagicMock,
        mock_get: MagicMock,
        listings_response: dict,
    ) -> None:
        mock_post.return_value.json.return_value = listings_response
        mock_post.return_value.raise_for_status = MagicMock()

        company_cfg = {
            "name": "NVIDIA",
            "ats": "workday",
            "config": {
                "base_url": "https://nvidia.wd5.myworkdayjobs.com",
                "site_path": "/wday/cxs/nvidia/NVIDIAExternalCareerSite",
                "site_name": "NVIDIAExternalCareerSite",
            },
        }
        # Both Germany jobs are already known
        known_keys = {"NVIDIA::JR1234567", "NVIDIA::JR7654321"}
        name, new_jobs, seen_jobs, active_keys = process_company(company_cfg, ["Germany"], known_keys=known_keys)

        assert new_jobs == []
        assert len(seen_jobs) == 2
        mock_get.assert_not_called()  # no description fetches for known jobs
