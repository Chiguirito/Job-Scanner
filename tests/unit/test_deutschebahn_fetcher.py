from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.fetchers.deutschebahn import DeutscheBahnConfig, DeutscheBahnFetcher, _normalize_location
from src.models import Job


def _search_page(jobs: list[dict], total: int | None = None) -> str:
    """Build a minimal search results HTML page."""
    count = total if total is not None else len(jobs)
    cards = ""
    for j in jobs:
        job_id = j["id"]
        title = j.get("title", f"Job {job_id}")
        location = j.get("location", "Berlin, Deutschland")
        company = j.get("company", "DB AG")
        dept = j.get("dept", "Engineering")
        slug = title.lower().replace(" ", "-")
        cards += f"""
        <a href="/de-de/Suche/{slug}?jobId={job_id}"
           class="m-search-hit"
           data-job-id="{job_id}">
          <header class="m-search-hit__header">
            <h3 class="m-search-hit__title">
              <span class="m-search-hit__title-text"
              >
              {title}
              </span>
            </h3>
          </header>
          <button class="m-search-hit__bookmark"
            track-interaction="bookmark job|{job_id}|{location}|Bayern|Deutschland|{company}|ab sofort|Vollzeit|{dept}|Fachkraft"
          ></button>
        </a>
        """
    return f"""<!DOCTYPE html><html><head></head><body>
    <div aria-label="{count} Stellen">
      {count} Stellen zu deinen Suchkriterien gefunden
    </div>
    {cards}
    </body></html>"""


def _detail_page(description: str = "Great job at Deutsche Bahn.") -> str:
    return f"""<!DOCTYPE html><html><head>
    <script type="application/ld+json">
    {{
      "@context": "https://schema.org/",
      "@type": "JobPosting",
      "title": "Some Job",
      "description": "<p>{description}</p>",
      "hiringOrganization": {{"@type": "Organization", "name": "Deutsche Bahn AG"}},
      "jobLocation": [{{"@type": "Place", "address": {{"addressLocality": "Berlin", "addressCountry": "Deutschland"}}}}]
    }}
    </script>
    </head><body></body></html>"""


_JOB_A = {"id": "111111", "title": "Software Engineer", "location": "Berlin, Deutschland", "dept": "IT"}
_JOB_B = {"id": "222222", "title": "Project Manager", "location": "München, Deutschland", "dept": "PM"}


@pytest.fixture
def fetcher() -> DeutscheBahnFetcher:
    return DeutscheBahnFetcher(DeutscheBahnConfig(company="Deutsche Bahn"))


class TestDeutscheBahnFetcher:
    @patch("src.fetchers.deutschebahn.requests.get")
    def test_fetch_listings_returns_jobs(
        self, mock_get: MagicMock, fetcher: DeutscheBahnFetcher
    ) -> None:
        r = MagicMock()
        r.raise_for_status = MagicMock()
        r.text = _search_page([_JOB_A, _JOB_B], total=2)
        mock_get.return_value = r

        jobs, raw = fetcher.fetch_listings()

        assert len(jobs) == 2
        assert all(isinstance(j, Job) for j in jobs)

    @patch("src.fetchers.deutschebahn.requests.get")
    def test_fetch_listings_extracts_title_and_id(
        self, mock_get: MagicMock, fetcher: DeutscheBahnFetcher
    ) -> None:
        r = MagicMock()
        r.raise_for_status = MagicMock()
        r.text = _search_page([_JOB_A], total=1)
        mock_get.return_value = r

        jobs, _ = fetcher.fetch_listings()

        assert jobs[0].ats_job_id == "111111"
        assert jobs[0].title == "Software Engineer"
        assert jobs[0].unique_key == "Deutsche Bahn::111111"

    @patch("src.fetchers.deutschebahn.requests.get")
    def test_fetch_listings_normalizes_location(
        self, mock_get: MagicMock, fetcher: DeutscheBahnFetcher
    ) -> None:
        r = MagicMock()
        r.raise_for_status = MagicMock()
        r.text = _search_page([_JOB_A], total=1)
        mock_get.return_value = r

        jobs, _ = fetcher.fetch_listings()

        assert "Germany" in jobs[0].location
        assert "Deutschland" not in jobs[0].location

    @patch("src.fetchers.deutschebahn.requests.get")
    def test_fetch_listings_paginates(
        self, mock_get: MagicMock, fetcher: DeutscheBahnFetcher
    ) -> None:
        page1 = _search_page(
            [{"id": str(i), "title": f"Job {i}"} for i in range(20)], total=40
        )
        page2 = _search_page(
            [{"id": str(i), "title": f"Job {i}"} for i in range(20, 40)], total=40
        )
        mock_get.side_effect = [_make_response(page1), _make_response(page2)]

        jobs, _ = fetcher.fetch_listings()

        assert len(jobs) == 40

    @patch("src.fetchers.deutschebahn.requests.get")
    def test_enrich_descriptions_fills_description(
        self, mock_get: MagicMock, fetcher: DeutscheBahnFetcher
    ) -> None:
        mock_get.return_value.status_code = 200
        mock_get.return_value.text = _detail_page("Innovative railway tech role.")

        stub = Job(
            title="Software Engineer",
            url="https://db.jobs/de-de/Suche/some-job?jobId=111111",
            company="Deutsche Bahn",
            ats_job_id="111111",
            location="Berlin, Germany",
            department="IT",
            description="",
        )

        enriched = fetcher.enrich_descriptions([stub], [{"job_id": "111111"}])

        assert len(enriched) == 1
        assert "railway tech" in enriched[0].description

    @patch("src.fetchers.deutschebahn.requests.get")
    def test_enrich_descriptions_empty_list_noop(
        self, mock_get: MagicMock, fetcher: DeutscheBahnFetcher
    ) -> None:
        result = fetcher.enrich_descriptions([], [])

        assert result == []
        mock_get.assert_not_called()

    @patch("src.fetchers.deutschebahn.requests.get")
    def test_enrich_descriptions_tolerates_failed_fetch(
        self, mock_get: MagicMock, fetcher: DeutscheBahnFetcher
    ) -> None:
        mock_get.return_value.status_code = 503

        stub = Job(
            title="", url="https://db.jobs/de-de/Suche/some-job?jobId=111111",
            company="Deutsche Bahn", ats_job_id="111111",
            location="Berlin, Germany", department="", description="",
        )

        enriched = fetcher.enrich_descriptions([stub], [{"job_id": "111111"}])

        assert enriched[0] is stub

    def test_normalize_location_replaces_deutschland(self) -> None:
        assert _normalize_location("Berlin, Deutschland") == "Berlin, Germany"

    def test_normalize_location_multiple_cities(self) -> None:
        result = _normalize_location("Augsburg, München, Deutschland")
        assert "Germany" in result
        assert "Deutschland" not in result

    def test_parse_total_german_number_format(self, fetcher: DeutscheBahnFetcher) -> None:
        html = '<div aria-label="3.223 Stellen">3.223 Stellen zu deinen Suchkriterien gefunden</div>'
        assert fetcher._parse_total(html) == 3223


def _make_response(text: str) -> MagicMock:
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.text = text
    return r
