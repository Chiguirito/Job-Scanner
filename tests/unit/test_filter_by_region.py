from __future__ import annotations

from src.fetchers.greenhouse import GreenhouseConfig, GreenhouseFetcher
from src.fetchers.workday import WorkdayConfig, WorkdayFetcher
from src.main import filter_by_region
from src.models import Job


def _job(location: str, job_id: str = "1") -> Job:
    return Job(title="Eng", url="https://example.com", company="Acme",
               ats_job_id=job_id, location=location)


class TestFilterByRegion:
    def test_no_regions_returns_all(self) -> None:
        jobs = [_job("Germany, Munich"), _job("USA, California", "2")]
        result_jobs, _ = filter_by_region(jobs, [{}, {}], [])
        assert result_jobs == jobs

    def test_workday_format_country_first(self) -> None:
        jobs = [_job("Germany, Munich"), _job("USA, California", "2")]
        result_jobs, _ = filter_by_region(jobs, [{}, {}], ["Germany"])
        assert len(result_jobs) == 1
        assert result_jobs[0].location == "Germany, Munich"

    def test_greenhouse_format_city_first(self) -> None:
        jobs = [_job("Munich, Germany"), _job("Mountain View, CA", "2")]
        result_jobs, _ = filter_by_region(jobs, [{}, {}], ["Germany"])
        assert len(result_jobs) == 1
        assert result_jobs[0].location == "Munich, Germany"

    def test_case_insensitive_match(self) -> None:
        jobs = [_job("BERLIN, GERMANY")]
        result_jobs, _ = filter_by_region(jobs, [{}], ["germany"])
        assert len(result_jobs) == 1

    def test_multiple_regions(self) -> None:
        jobs = [_job("Munich, Germany"), _job("Paris, France", "2"), _job("London, UK", "3")]
        result_jobs, _ = filter_by_region(jobs, [{}, {}, {}], ["Germany", "France"])
        assert len(result_jobs) == 2

    def test_no_match_returns_empty(self) -> None:
        jobs = [_job("Mountain View, CA")]
        result_jobs, raw = filter_by_region(jobs, [{}], ["Germany"])
        assert result_jobs == []
        assert raw == []
