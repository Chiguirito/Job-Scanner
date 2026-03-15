from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.models import Job, SearchScore
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

    def test_save_updates_last_seen_on_duplicate(self, store: JobStore) -> None:
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

    def test_filter_new_saves_all_jobs(self, store: JobStore) -> None:
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


class TestJobStoreClosedTracking:
    def test_new_jobs_are_active(self, store: JobStore) -> None:
        store.save([_make_job(job_id="1")])
        assert store.count(active_only=True) == 1

    def test_mark_closed_deactivates_missing_jobs(self, store: JobStore) -> None:
        job1 = _make_job(job_id="1")
        job2 = _make_job(job_id="2")
        store.save([job1, job2])

        closed = store.mark_closed("Acme", {job1.unique_key})

        assert len(closed) == 1
        assert job2.unique_key in closed
        assert store.count(active_only=True) == 1
        assert store.count() == 2

    def test_mark_closed_returns_empty_when_all_still_active(self, store: JobStore) -> None:
        job1 = _make_job(job_id="1")
        store.save([job1])

        closed = store.mark_closed("Acme", {job1.unique_key})

        assert closed == []
        assert store.count(active_only=True) == 1

    def test_mark_closed_only_affects_specified_company(self, store: JobStore) -> None:
        acme_job = _make_job(company="Acme", job_id="1")
        globex_job = _make_job(company="Globex", job_id="1")
        store.save([acme_job, globex_job])

        closed = store.mark_closed("Acme", set())

        assert len(closed) == 1
        assert acme_job.unique_key in closed
        assert store.count(active_only=True) == 1  # Globex still active

    def test_resave_reactivates_closed_job(self, store: JobStore) -> None:
        job = _make_job(job_id="1")
        store.save([job])
        store.mark_closed("Acme", set())
        assert store.count(active_only=True) == 0

        store.save([job])
        assert store.count(active_only=True) == 1

    def test_filter_new_updates_last_seen_for_existing(self, store: JobStore) -> None:
        job1 = _make_job(job_id="1")
        job2 = _make_job(job_id="2")
        store.save([job1])

        new = store.filter_new([job1, job2])

        assert new == [job2]
        assert store.count() == 2
        assert store.count(active_only=True) == 2


class TestGetAllKnownKeys:
    def test_empty_store_returns_empty_set(self, store: JobStore) -> None:
        assert store.get_all_known_keys() == set()

    def test_returns_all_saved_keys(self, store: JobStore) -> None:
        job1 = _make_job(job_id="1")
        job2 = _make_job(company="Globex", job_id="2")
        store.save([job1, job2])

        keys = store.get_all_known_keys()

        assert keys == {job1.unique_key, job2.unique_key}

    def test_includes_inactive_jobs(self, store: JobStore) -> None:
        job = _make_job(job_id="1")
        store.save([job])
        store.mark_closed("Acme", set())

        assert job.unique_key in store.get_all_known_keys()


def _make_score(job: Job, search_name: str = "Test Search", **kwargs) -> SearchScore:
    defaults = dict(
        unique_key=job.unique_key,
        search_name=search_name,
        fit_score=75,
        desirability_score=70,
        hard_fail=False,
        hard_fail_reason="",
        score_detail={"fit_reasoning": "Good match."},
        stage_reached=3,
        profile_hash="abc123",
        requirements_hash="def456",
    )
    defaults.update(kwargs)
    return SearchScore(**defaults)


class TestSearchScores:
    def test_save_and_retrieve_top_jobs(self, store: JobStore) -> None:
        job = _make_job(description="A great role.")
        store.save([job])
        store.save_score(_make_score(job, fit_score=80, desirability_score=75))

        results = store.get_top_jobs_for_search("Test Search")
        assert len(results) == 1
        assert results[0][0].unique_key == job.unique_key
        assert results[0][1].fit_score == 80

    def test_upsert_updates_existing_score(self, store: JobStore) -> None:
        job = _make_job(description="A role.")
        store.save([job])
        store.save_score(_make_score(job, fit_score=50))
        store.save_score(_make_score(job, fit_score=90))

        results = store.get_top_jobs_for_search("Test Search", min_fit=0, min_desirability=0)
        assert len(results) == 1
        assert results[0][1].fit_score == 90

    def test_hard_fail_excluded_from_top_jobs(self, store: JobStore) -> None:
        job = _make_job(description="A role.")
        store.save([job])
        store.save_score(_make_score(job, hard_fail=True, hard_fail_reason="Wrong title"))

        results = store.get_top_jobs_for_search("Test Search", min_fit=0, min_desirability=0)
        assert results == []

    def test_top_jobs_ordered_by_combined_score(self, store: JobStore) -> None:
        job_a = _make_job(job_id="A", description="Role A.")
        job_b = _make_job(job_id="B", description="Role B.")
        store.save([job_a, job_b])
        store.save_score(_make_score(job_a, fit_score=60, desirability_score=60))  # sum=120
        store.save_score(_make_score(job_b, fit_score=90, desirability_score=80))  # sum=170

        results = store.get_top_jobs_for_search("Test Search", min_fit=0, min_desirability=0)
        assert results[0][0].unique_key == job_b.unique_key

    def test_top_jobs_respects_min_thresholds(self, store: JobStore) -> None:
        job = _make_job(description="A role.")
        store.save([job])
        store.save_score(_make_score(job, fit_score=50, desirability_score=50))

        assert store.get_top_jobs_for_search("Test Search", min_fit=60) == []

    def test_get_unscored_returns_new_jobs(self, store: JobStore) -> None:
        job = _make_job(description="A role.", location="Munich, Germany")
        store.save([job])

        unscored = store.get_unscored_jobs_for_search("Test Search", "p_hash", "r_hash", ["Germany"])
        assert len(unscored) == 1
        assert unscored[0].unique_key == job.unique_key

    def test_get_unscored_skips_already_scored(self, store: JobStore) -> None:
        job = _make_job(description="A role.", location="Munich, Germany")
        store.save([job])
        store.save_score(_make_score(job, profile_hash="p_hash", requirements_hash="r_hash"))

        unscored = store.get_unscored_jobs_for_search("Test Search", "p_hash", "r_hash", ["Germany"])
        assert unscored == []

    def test_get_unscored_rescores_on_profile_change(self, store: JobStore) -> None:
        job = _make_job(description="A role.", location="Munich, Germany")
        store.save([job])
        store.save_score(_make_score(job, profile_hash="old_hash", requirements_hash="r_hash"))

        unscored = store.get_unscored_jobs_for_search("Test Search", "new_hash", "r_hash", ["Germany"])
        assert len(unscored) == 1

    def test_get_unscored_rescores_on_requirements_change(self, store: JobStore) -> None:
        job = _make_job(description="A role.", location="Munich, Germany")
        store.save([job])
        store.save_score(_make_score(job, profile_hash="p_hash", requirements_hash="old_req"))

        unscored = store.get_unscored_jobs_for_search("Test Search", "p_hash", "new_req", ["Germany"])
        assert len(unscored) == 1

    def test_get_unscored_skips_jobs_without_description(self, store: JobStore) -> None:
        job = _make_job(description="", location="Munich, Germany")
        store.save([job])

        unscored = store.get_unscored_jobs_for_search("Test Search", "p_hash", "r_hash", ["Germany"])
        assert unscored == []

    def test_get_unscored_skips_inactive_jobs(self, store: JobStore) -> None:
        job = _make_job(description="A role.", location="Munich, Germany")
        store.save([job])
        store.mark_closed("Acme", set())

        unscored = store.get_unscored_jobs_for_search("Test Search", "p_hash", "r_hash", ["Germany"])
        assert unscored == []

    def test_get_unscored_filters_by_region(self, store: JobStore) -> None:
        job_de = _make_job(job_id="1", description="A role.", location="Munich, Germany")
        job_us = _make_job(job_id="2", description="A role.", location="San Francisco, US")
        store.save([job_de, job_us])

        unscored = store.get_unscored_jobs_for_search("Test Search", "p", "r", ["Germany"])
        assert len(unscored) == 1
        assert unscored[0].unique_key == job_de.unique_key

    def test_get_unscored_no_region_filter_returns_all(self, store: JobStore) -> None:
        job_de = _make_job(job_id="1", description="A role.", location="Munich, Germany")
        job_us = _make_job(job_id="2", description="A role.", location="San Francisco, US")
        store.save([job_de, job_us])

        unscored = store.get_unscored_jobs_for_search("Test Search", "p", "r", [])
        assert len(unscored) == 2
