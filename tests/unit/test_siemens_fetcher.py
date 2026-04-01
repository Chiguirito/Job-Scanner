from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.fetchers.siemens import SiemensConfig, SiemensFetcher, _parse_avature_location
from src.models import Job


def _search_page(jobs: list[dict], total: int = 0) -> str:
    """Build a minimal search results HTML page."""
    actual_total = total or len(jobs)
    cards = ""
    for j in jobs:
        cards += f"""
        <h3 class="title">
          <a class="link" href="https://jobs.siemens.com/en_US/externaljobs/JobDetail/{j['id']}"
             data-au="ag-a-1">{j['title']}</a>
        </h3>
        <div class="article__header__text__subtitle">
          {j.get('location', 'Munich')} &nbsp;&#8226;&nbsp;
          <span class="list-item-jobId">Job ID: {j['id']}</span>
          &nbsp;&#8226;&nbsp; {j.get('dept', 'Engineering')}
        </div>
        <a href="https://jobs.siemens.com/en_US/externaljobs/JobDetail/{j['id']}">Learn more</a>
        """
    return f"""<!DOCTYPE html><html><head></head><body>
    <div class="list-controls__text__legend" aria-label="{actual_total} results">
      1 - {len(jobs)}
    </div>
    {cards}
    </body></html>"""


def _detail_page(
    city: str = "Munich",
    country: str = "Germany",
    description: str = "Build great products.",
) -> str:
    location_li = f'<li class="list__item">{city} -  - {country}</li>' if city else f'<li class="list__item">{country}</li>'
    return f"""<!DOCTYPE html><html><head></head><body>
    <ul class="list list--bullet list--locations">
      {location_li}
    </ul>
    <div class="article__content__view">
    <div class="article__content__view__field tf_replaceFieldVideoTokens">
      <div class="article__content__view__field__label">Job Description</div>
      <div class="article__content__view__field__value">
        <p>{description}</p>
      </div>
    </div>
    </div>
    </body></html>"""


_JOB_A = {"id": "111111", "title": "Software Engineer (m/f/d)", "location": "Munich", "dept": "Engineering"}
_JOB_B = {"id": "222222", "title": "Product Manager", "location": "Berlin", "dept": "Product"}


@pytest.fixture
def fetcher() -> SiemensFetcher:
    return SiemensFetcher(SiemensConfig(company="Siemens"))


class TestSiemensFetcher:
    @patch("src.fetchers.siemens.requests.get")
    def test_fetch_listings_returns_jobs(
        self, mock_get: MagicMock, fetcher: SiemensFetcher
    ) -> None:
        r = MagicMock()
        r.raise_for_status = MagicMock()
        r.text = _search_page([_JOB_A, _JOB_B], total=2)
        mock_get.return_value = r

        jobs, raw = fetcher.fetch_listings()

        assert len(jobs) == 2
        assert all(isinstance(j, Job) for j in jobs)

    @patch("src.fetchers.siemens.requests.get")
    def test_fetch_listings_extracts_title_and_id(
        self, mock_get: MagicMock, fetcher: SiemensFetcher
    ) -> None:
        r = MagicMock()
        r.raise_for_status = MagicMock()
        r.text = _search_page([_JOB_A], total=1)
        mock_get.return_value = r

        jobs, _ = fetcher.fetch_listings()

        assert jobs[0].ats_job_id == "111111"
        assert jobs[0].title == "Software Engineer (m/f/d)"
        assert jobs[0].unique_key == "Siemens::111111"

    @patch("src.fetchers.siemens.requests.get")
    def test_fetch_listings_placeholder_location(
        self, mock_get: MagicMock, fetcher: SiemensFetcher
    ) -> None:
        r = MagicMock()
        r.raise_for_status = MagicMock()
        r.text = _search_page([_JOB_A], total=1)
        mock_get.return_value = r

        jobs, _ = fetcher.fetch_listings()

        assert jobs[0].location == "Germany"
        assert jobs[0].description == ""

    @patch("src.fetchers.siemens.requests.get")
    def test_fetch_listings_paginates(
        self, mock_get: MagicMock, fetcher: SiemensFetcher
    ) -> None:
        # total=12 means 2 pages; first call returns total=12 with 6 jobs,
        # second call (concurrent page) returns 6 more
        page1 = _search_page([
            {"id": str(i), "title": f"Job {i}", "dept": "Eng"} for i in range(6)
        ], total=12)
        page2 = _search_page([
            {"id": str(i), "title": f"Job {i}", "dept": "Eng"} for i in range(6, 12)
        ], total=12)
        mock_get.return_value.raise_for_status = MagicMock()
        mock_get.side_effect = [
            _make_response(page1), _make_response(page2),
        ]

        jobs, _ = fetcher.fetch_listings()

        assert len(jobs) == 12

    @patch("src.fetchers.siemens.requests.get")
    def test_enrich_descriptions_fills_fields(
        self, mock_get: MagicMock, fetcher: SiemensFetcher
    ) -> None:
        mock_get.return_value.status_code = 200
        mock_get.return_value.text = _detail_page(
            city="Berlin", country="Germany", description="Great engineering role."
        )

        stub = Job(
            title="Software Engineer", url="https://jobs.siemens.com/en_US/externaljobs/JobDetail/111111",
            company="Siemens", ats_job_id="111111", location="Germany", department="", description="",
        )

        enriched = fetcher.enrich_descriptions([stub], [{"job_id": "111111"}])

        assert len(enriched) == 1
        assert enriched[0].location == "Berlin, Germany"
        assert "engineering role" in enriched[0].description

    @patch("src.fetchers.siemens.requests.get")
    def test_enrich_descriptions_empty_list_noop(
        self, mock_get: MagicMock, fetcher: SiemensFetcher
    ) -> None:
        result = fetcher.enrich_descriptions([], [])

        assert result == []
        mock_get.assert_not_called()

    @patch("src.fetchers.siemens.requests.get")
    def test_enrich_descriptions_tolerates_failed_fetch(
        self, mock_get: MagicMock, fetcher: SiemensFetcher
    ) -> None:
        mock_get.return_value.status_code = 503

        stub = Job(
            title="", url="https://jobs.siemens.com/en_US/externaljobs/JobDetail/111111",
            company="Siemens", ats_job_id="111111", location="Germany", department="", description="",
        )

        enriched = fetcher.enrich_descriptions([stub], [{"job_id": "111111"}])

        assert enriched[0] is stub

    def test_parse_avature_location_city_country(self) -> None:
        assert _parse_avature_location("Berlin -  - Germany") == "Berlin, Germany"

    def test_parse_avature_location_country_only(self) -> None:
        assert _parse_avature_location("Germany") == "Germany"


def _make_response(text: str) -> MagicMock:
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.text = text
    return r
