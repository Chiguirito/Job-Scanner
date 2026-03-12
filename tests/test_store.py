from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.models import Job
from src.store import JobStore


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    """Create a JobStore backed by a temporary database."""
    s = JobStore(db_path=tmp_path / "test.db")
    yield s
    s.close()


def _make_job(company: str = "Acme", job_id: str = "123", **kwargs) -> Job:
    defaults = dict(
        title="Software Engineer",
        url="https://example.com/jobs/123",
        company=company,
        ats_job_id=job_id,
    )
    defaults.update(kwargs)
    return Job(**defaults)


class TestJobStore:
    def test_empty_store_has_zero_count(self, store: JobStore) -> None:
        assert store.count() == 0

    def test_save_and_count(self, store: JobStore) -> None:
        jobs = [_make_job(job_id="1"), _make_job(job_id="2")]
        store.save(jobs)
        assert store.count() == 2

    def test_is_new_returns_true_for_unseen_job(self, store: JobStore) -> None:
        job = _make_job()
        assert store.is_new(job) is True

    def test_is_new_returns_false_after_save(self, store: JobStore) -> None:
        job = _make_job()
        store.save([job])
        assert store.is_new(job) is False

    def test_save_ignores_duplicates(self, store: JobStore) -> None:
        job = _make_job()
        store.save([job])
        store.save([job])
        assert store.count() == 1

    def test_filter_new_returns_only_unseen(self, store: JobStore) -> None:
        job1 = _make_job(job_id="1")
        job2 = _make_job(job_id="2")
        store.save([job1])

        new = store.filter_new([job1, job2])
        assert new == [job2]
        assert store.count() == 2

    def test_filter_new_with_empty_list(self, store: JobStore) -> None:
        assert store.filter_new([]) == []

    def test_filter_new_saves_new_jobs(self, store: JobStore) -> None:
        job = _make_job()
        store.filter_new([job])
        assert store.is_new(job) is False

    def test_job_with_posted_date(self, store: JobStore) -> None:
        job = _make_job(posted_date=date(2026, 3, 1))
        store.save([job])
        assert store.count() == 1

    def test_different_companies_are_separate(self, store: JobStore) -> None:
        job1 = _make_job(company="Acme", job_id="1")
        job2 = _make_job(company="Globex", job_id="1")
        store.save([job1, job2])
        assert store.count() == 2
