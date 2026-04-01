from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest

from src.fetchers.smartrecruiters import SmartRecruitersConfig, SmartRecruitersFetcher
from src.models import Job

_COMPANY_ID = "BoschGroup"
_COMPANY = "Bosch"
_API_BASE = f"https://api.smartrecruiters.com/v1/companies/{_COMPANY_ID}/postings"


def _listing_response(jobs: list[dict], total: int | None = None) -> dict:
    return {
        "offset": 0,
        "limit": 100,
        "totalFound": total if total is not None else len(jobs),
        "content": jobs,
    }


def _raw_job(
    job_id: str = "111222333",
    title: str = "Software Engineer",
    city: str = "Stuttgart",
    country: str = "de",
    full_location: str = "Stuttgart, BW, Germany",
    function_label: str = "Engineering",
    posting_url: str = "https://jobs.smartrecruiters.com/BoschGroup/111222333-software-engineer",
) -> dict:
    return {
        "id": job_id,
        "name": title,
        "location": {
            "city": city,
            "country": country,
            "fullLocation": full_location,
        },
        "function": {"id": "engineering", "label": function_label},
        "department": {},
        "postingUrl": posting_url,
        "refNumber": "REF001",
    }


def _detail_response(
    job_id: str = "111222333",
    job_desc: str = "Build great software.",
    qualifications: str = "Python skills.",
    additional: str = "Remote OK.",
) -> dict:
    return {
        "id": job_id,
        "jobAd": {
            "sections": {
                "jobDescription": {"title": "Job Description", "text": job_desc},
                "qualifications": {"title": "Qualifications", "text": qualifications},
                "additionalInformation": {"title": "Additional", "text": additional},
            }
        },
    }


@pytest.fixture
def fetcher() -> SmartRecruitersFetcher:
    return SmartRecruitersFetcher(SmartRecruitersConfig(company=_COMPANY, company_id=_COMPANY_ID))


class TestSmartRecruitersFetcher:
    @patch("src.fetchers.smartrecruiters.requests.get")
    def test_fetch_listings_single_page(self, mock_get: MagicMock, fetcher: SmartRecruitersFetcher) -> None:
        mock_get.return_value.json.return_value = _listing_response([_raw_job("1"), _raw_job("2")])
        mock_get.return_value.raise_for_status = MagicMock()

        jobs, raw = fetcher.fetch_listings()

        assert len(jobs) == 2
        assert len(raw) == 2
        assert all(isinstance(j, Job) for j in jobs)
        mock_get.assert_called_once()

    @patch("src.fetchers.smartrecruiters.requests.get")
    def test_fetch_listings_paginates(self, mock_get: MagicMock, fetcher: SmartRecruitersFetcher) -> None:
        page1 = _listing_response([_raw_job(str(i)) for i in range(100)], total=150)
        page2 = _listing_response([_raw_job(str(i)) for i in range(100, 150)], total=150)

        mock_get.return_value.raise_for_status = MagicMock()
        mock_get.return_value.json.side_effect = [page1, page2]

        jobs, _ = fetcher.fetch_listings()

        assert len(jobs) == 150
        assert mock_get.call_count == 2

    @patch("src.fetchers.smartrecruiters.requests.get")
    def test_job_fields_mapped_correctly(self, mock_get: MagicMock, fetcher: SmartRecruitersFetcher) -> None:
        raw = _raw_job(
            job_id="999",
            title="ML Engineer",
            full_location="Munich, Bavaria, Germany",
            function_label="Information Technology",
            posting_url="https://jobs.smartrecruiters.com/BoschGroup/999-ml-engineer",
        )
        mock_get.return_value.json.return_value = _listing_response([raw])
        mock_get.return_value.raise_for_status = MagicMock()

        jobs, _ = fetcher.fetch_listings()
        job = jobs[0]

        assert job.title == "ML Engineer"
        assert job.company == _COMPANY
        assert job.ats_job_id == "999"
        assert job.location == "Munich, Bavaria, Germany"
        assert job.department == "Information Technology"
        assert job.url == "https://jobs.smartrecruiters.com/BoschGroup/999-ml-engineer"
        assert job.description == ""

    @patch("src.fetchers.smartrecruiters.requests.get")
    def test_unique_key_format(self, mock_get: MagicMock, fetcher: SmartRecruitersFetcher) -> None:
        mock_get.return_value.json.return_value = _listing_response([_raw_job("42")])
        mock_get.return_value.raise_for_status = MagicMock()

        jobs, _ = fetcher.fetch_listings()

        assert jobs[0].unique_key == f"{_COMPANY}::42"

    @patch("src.fetchers.smartrecruiters.requests.get")
    def test_enrich_descriptions_fetches_detail(self, mock_get: MagicMock, fetcher: SmartRecruitersFetcher) -> None:
        mock_get.return_value.json.return_value = _detail_response(
            job_id="111",
            job_desc="Build great software.",
            qualifications="Python skills.",
            additional="Remote OK.",
        )
        mock_get.return_value.raise_for_status = MagicMock()

        stub_job = Job(
            title="Software Engineer",
            url="https://jobs.smartrecruiters.com/BoschGroup/111",
            company=_COMPANY,
            ats_job_id="111",
            location="Stuttgart, BW, Germany",
            department="Engineering",
            description="",
        )

        enriched = fetcher.enrich_descriptions([stub_job], [{}])
        job = enriched[0]

        assert "Build great software" in job.description
        assert "Python skills" in job.description
        assert "Remote OK" in job.description
        mock_get.assert_called_once_with(
            f"{_API_BASE}/111",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=30,
        )

    @patch("src.fetchers.smartrecruiters.requests.get")
    def test_enrich_descriptions_empty_noop(self, mock_get: MagicMock, fetcher: SmartRecruitersFetcher) -> None:
        result = fetcher.enrich_descriptions([], [])

        assert result == []
        mock_get.assert_not_called()

    @patch("src.fetchers.smartrecruiters.requests.get")
    def test_enrich_tolerates_failed_request(self, mock_get: MagicMock, fetcher: SmartRecruitersFetcher) -> None:
        mock_get.side_effect = Exception("timeout")

        stub_job = Job(
            title="Engineer",
            url="https://example.com",
            company=_COMPANY,
            ats_job_id="99",
            location="Germany",
            department="",
            description="",
        )

        enriched = fetcher.enrich_descriptions([stub_job], [{}])

        assert enriched[0] is stub_job

    @patch("src.fetchers.smartrecruiters.requests.get")
    def test_fetch_returns_jobs_without_descriptions(self, mock_get: MagicMock, fetcher: SmartRecruitersFetcher) -> None:
        mock_get.return_value.json.return_value = _listing_response([_raw_job("1"), _raw_job("2")])
        mock_get.return_value.raise_for_status = MagicMock()

        jobs = fetcher.fetch()

        assert len(jobs) == 2
        assert all(j.description == "" for j in jobs)
