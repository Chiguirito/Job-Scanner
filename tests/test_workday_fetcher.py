from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.fetchers.workday import WorkdayConfig, WorkdayFetcher
from src.models import Job


@pytest.fixture
def config() -> WorkdayConfig:
    return WorkdayConfig(
        company="TestCorp",
        base_url="https://testcorp.wd5.myworkdayjobs.com",
        site_path="/wday/cxs/testcorp/TestCorpSite",
        site_name="TestCorpSite",
    )


@pytest.fixture
def fetcher(config: WorkdayConfig) -> WorkdayFetcher:
    return WorkdayFetcher(config)


def _make_api_response(
    postings: list[dict], total: int | None = None
) -> dict:
    if total is None:
        total = len(postings)
    return {"total": total, "jobPostings": postings}


def _make_posting(
    title: str = "Software Engineer",
    job_id: str = "JR001",
    location: str = "US, CA, Santa Clara",
) -> dict:
    return {
        "title": title,
        "externalPath": f"/job/location/{title.replace(' ', '-')}_{job_id}",
        "locationsText": location,
        "postedOn": "Posted Today",
        "bulletFields": [job_id],
    }


class TestWorkdayFetcher:
    @patch("src.fetchers.workday.requests.post")
    def test_fetch_single_page(self, mock_post: MagicMock, fetcher: WorkdayFetcher) -> None:
        postings = [_make_posting(job_id="JR001"), _make_posting(job_id="JR002")]
        mock_post.return_value.json.return_value = _make_api_response(postings)
        mock_post.return_value.raise_for_status = MagicMock()

        jobs = fetcher.fetch()

        assert len(jobs) == 2
        assert all(isinstance(j, Job) for j in jobs)
        assert jobs[0].ats_job_id == "JR001"
        assert jobs[1].ats_job_id == "JR002"

    @patch("src.fetchers.workday.requests.post")
    def test_fetch_paginates(self, mock_post: MagicMock, fetcher: WorkdayFetcher) -> None:
        page1 = _make_api_response([_make_posting(job_id=f"JR{i:03d}") for i in range(20)], total=25)
        page2 = _make_api_response([_make_posting(job_id=f"JR{i:03d}") for i in range(20, 25)], total=25)

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.side_effect = [page1, page2]
        mock_post.return_value = mock_resp

        jobs = fetcher.fetch()

        assert len(jobs) == 25
        assert mock_post.call_count == 2

    @patch("src.fetchers.workday.requests.post")
    def test_fetch_empty_response(self, mock_post: MagicMock, fetcher: WorkdayFetcher) -> None:
        mock_post.return_value.json.return_value = _make_api_response([])
        mock_post.return_value.raise_for_status = MagicMock()

        jobs = fetcher.fetch()

        assert jobs == []

    @patch("src.fetchers.workday.requests.post")
    def test_fetch_respects_limit(self, mock_post: MagicMock, config: WorkdayConfig) -> None:
        config.limit = 5
        fetcher = WorkdayFetcher(config)

        postings = [_make_posting(job_id=f"JR{i:03d}") for i in range(20)]
        mock_post.return_value.json.return_value = _make_api_response(postings, total=100)
        mock_post.return_value.raise_for_status = MagicMock()

        jobs = fetcher.fetch()

        assert len(jobs) == 5

    @patch("src.fetchers.workday.requests.post")
    def test_job_fields_mapped_correctly(self, mock_post: MagicMock, fetcher: WorkdayFetcher) -> None:
        posting = _make_posting(title="ML Engineer", job_id="JR042", location="US, WA, Seattle")
        mock_post.return_value.json.return_value = _make_api_response([posting])
        mock_post.return_value.raise_for_status = MagicMock()

        job = fetcher.fetch()[0]

        assert job.title == "ML Engineer"
        assert job.company == "TestCorp"
        assert job.ats_job_id == "JR042"
        assert job.location == "US, WA, Seattle"
        assert "TestCorpSite/job/" in job.url

    @patch("src.fetchers.workday.requests.post")
    def test_job_url_format(self, mock_post: MagicMock, fetcher: WorkdayFetcher) -> None:
        posting = _make_posting(title="Engineer", job_id="JR001")
        mock_post.return_value.json.return_value = _make_api_response([posting])
        mock_post.return_value.raise_for_status = MagicMock()

        job = fetcher.fetch()[0]

        assert job.url == "https://testcorp.wd5.myworkdayjobs.com/TestCorpSite/job/job/location/Engineer_JR001"

    @patch("src.fetchers.workday.requests.post")
    def test_posting_without_bullet_fields_uses_external_path(
        self, mock_post: MagicMock, fetcher: WorkdayFetcher
    ) -> None:
        posting = {
            "title": "Designer",
            "externalPath": "/job/loc/Designer_JR999",
            "locationsText": "Remote",
            "postedOn": "Posted 3 Days Ago",
            "bulletFields": [],
        }
        mock_post.return_value.json.return_value = _make_api_response([posting])
        mock_post.return_value.raise_for_status = MagicMock()

        job = fetcher.fetch()[0]

        assert job.ats_job_id == "/job/loc/Designer_JR999"

    @patch("src.fetchers.workday.requests.post")
    def test_fetch_sends_correct_payload(self, mock_post: MagicMock, config: WorkdayConfig) -> None:
        config.search_text = "data scientist"
        config.applied_facets = {"jobFamilyGroup": ["abc123"]}
        fetcher = WorkdayFetcher(config)

        mock_post.return_value.json.return_value = _make_api_response([])
        mock_post.return_value.raise_for_status = MagicMock()

        fetcher.fetch()

        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["searchText"] == "data scientist"
        assert payload["appliedFacets"] == {"jobFamilyGroup": ["abc123"]}
        assert payload["limit"] == 20
        assert payload["offset"] == 0
