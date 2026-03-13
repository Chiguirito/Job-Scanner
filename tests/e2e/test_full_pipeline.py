from __future__ import annotations

from pathlib import Path

import pytest

from tests.vcr_config import vcr
from src.main import main
from src.store import JobStore

CASSETTES = Path(__file__).parent.parent / "cassettes"


class TestFullPipeline:
    """End-to-end tests that run main() with HTTP replayed from vcrpy cassettes."""

    @vcr.use_cassette("nvidia_germany_scan.yaml")
    def test_nvidia_germany_scan_stores_jobs(self, tmp_path: Path) -> None:
        config_path = Path("config/companies.yaml")
        db_path = tmp_path / "jobs.db"

        main(config_path=config_path, db_path=db_path)

        store = JobStore(db_path=db_path)
        try:
            # NVIDIA: 2 Germany jobs; Waymo: 1 Germany job; 1 US job filtered out per company
            assert store.count() == 3
            assert store.count(active_only=True) == 3
        finally:
            store.close()

    @vcr.use_cassette("nvidia_germany_scan_two_runs.yaml")
    def test_second_run_marks_no_new_jobs(self, tmp_path: Path) -> None:
        """Running the pipeline twice should not produce new jobs on the second run."""
        config_path = Path("config/companies.yaml")
        db_path = tmp_path / "jobs.db"

        main(config_path=config_path, db_path=db_path)
        main(config_path=config_path, db_path=db_path)

        store = JobStore(db_path=db_path)
        try:
            assert store.count() == 3
        finally:
            store.close()


@pytest.mark.live
class TestLivePipeline:
    """Runs against the real Workday API. Excluded from CI — run with: pytest -m live"""

    def test_nvidia_live_scan(self, tmp_path: Path) -> None:
        db_path = tmp_path / "jobs.db"
        main(db_path=db_path)

        store = JobStore(db_path=db_path)
        try:
            assert store.count() > 0
        finally:
            store.close()
