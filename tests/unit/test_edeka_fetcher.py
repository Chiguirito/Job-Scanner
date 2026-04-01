from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.fetchers.edeka import EdekaConfig, EdekaFetcher
from src.models import Job


def _sitemap(job_urls: list[str]) -> str:
    items = "\n".join(
        f"<url><loc>{u.replace('&', '&amp;')}</loc></url>" for u in job_urls
    )
    return f"""<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  {items}
</urlset>"""


def _job_page(
    title: str = "Marktmanager",
    locality: str = "Berlin",
    country: str = "Germany",
    description: str = "Leite deinen Markt.",
    category: str = "Management",
) -> str:
    return f"""<!DOCTYPE html><html><head>
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "JobPosting",
  "title": "{title}",
  "description": "{description}",
  "occupationalCategory": "{category}",
  "jobLocation": {{
    "@type": "Place",
    "address": {{
      "@type": "PostalAddress",
      "addressLocality": "{locality}",
      "addressCountry": "{country}"
    }}
  }}
}}
</script>
</head><body></body></html>"""


_JOB_URL_1 = "https://verbund.edeka/karriere/stellenb%C3%B6rse/stelle-marktmanager-m-w-d-berlin?id=12345_67890&type=j"
_JOB_URL_2 = "https://verbund.edeka/karriere/stellenb%C3%B6rse/stelle-kassierer-m-w-d-hamburg?id=22222_33333&type=j"
_NON_JOB_URL = "https://verbund.edeka/karriere/ueber-uns"
# XML-escaped versions for embedding inside <loc> elements


@pytest.fixture
def fetcher() -> EdekaFetcher:
    return EdekaFetcher(EdekaConfig(company="Edeka"))


class TestEdekaFetcher:
    @patch("src.fetchers.edeka.requests.get")
    def test_fetch_listings_returns_jobs(
        self, mock_get: MagicMock, fetcher: EdekaFetcher
    ) -> None:
        r = MagicMock()
        r.raise_for_status = MagicMock()
        r.text = _sitemap([_JOB_URL_1, _JOB_URL_2])
        mock_get.return_value = r

        jobs, raw = fetcher.fetch_listings()

        assert len(jobs) == 2
        assert len(raw) == 2
        assert all(isinstance(j, Job) for j in jobs)

    @patch("src.fetchers.edeka.requests.get")
    def test_fetch_listings_extracts_id_from_query_param(
        self, mock_get: MagicMock, fetcher: EdekaFetcher
    ) -> None:
        r = MagicMock()
        r.raise_for_status = MagicMock()
        r.text = _sitemap([_JOB_URL_1])
        mock_get.return_value = r

        jobs, _ = fetcher.fetch_listings()

        assert jobs[0].ats_job_id == "12345_67890"
        assert jobs[0].unique_key == "Edeka::12345_67890"

    @patch("src.fetchers.edeka.requests.get")
    def test_fetch_listings_placeholder_location(
        self, mock_get: MagicMock, fetcher: EdekaFetcher
    ) -> None:
        r = MagicMock()
        r.raise_for_status = MagicMock()
        r.text = _sitemap([_JOB_URL_1])
        mock_get.return_value = r

        jobs, _ = fetcher.fetch_listings()

        assert jobs[0].location == "Germany"
        assert jobs[0].title == ""
        assert jobs[0].description == ""

    @patch("src.fetchers.edeka.requests.get")
    def test_fetch_listings_skips_urls_without_id(
        self, mock_get: MagicMock, fetcher: EdekaFetcher
    ) -> None:
        r = MagicMock()
        r.raise_for_status = MagicMock()
        r.text = _sitemap([_JOB_URL_1, _NON_JOB_URL])
        mock_get.return_value = r

        jobs, _ = fetcher.fetch_listings()

        assert len(jobs) == 1
        assert jobs[0].ats_job_id == "12345_67890"

    @patch("src.fetchers.edeka.requests.get")
    def test_enrich_descriptions_fills_fields(
        self, mock_get: MagicMock, fetcher: EdekaFetcher
    ) -> None:
        mock_get.return_value.status_code = 200
        mock_get.return_value.text = _job_page(
            title="Marktmanager", locality="Munich", country="Germany",
            description="Run your market."
        )

        stub_job = Job(
            title="", url=_JOB_URL_1, company="Edeka",
            ats_job_id="12345_67890", location="Germany", department="", description="",
        )

        enriched = fetcher.enrich_descriptions([stub_job], [{"url": _JOB_URL_1}])

        assert len(enriched) == 1
        job = enriched[0]
        assert job.title == "Marktmanager"
        assert "Munich" in job.location
        assert "Germany" in job.location
        assert "market" in job.description

    @patch("src.fetchers.edeka.requests.get")
    def test_enrich_descriptions_empty_list_noop(
        self, mock_get: MagicMock, fetcher: EdekaFetcher
    ) -> None:
        result = fetcher.enrich_descriptions([], [])

        assert result == []
        mock_get.assert_not_called()

    @patch("src.fetchers.edeka.requests.get")
    def test_enrich_descriptions_tolerates_failed_fetch(
        self, mock_get: MagicMock, fetcher: EdekaFetcher
    ) -> None:
        mock_get.return_value.status_code = 503

        stub_job = Job(
            title="", url=_JOB_URL_1, company="Edeka",
            ats_job_id="12345_67890", location="Germany", department="", description="",
        )

        enriched = fetcher.enrich_descriptions([stub_job], [{"url": _JOB_URL_1}])

        assert enriched[0] is stub_job

    @patch("src.fetchers.edeka.requests.get")
    def test_fetch_calls_enrich(
        self, mock_get: MagicMock, fetcher: EdekaFetcher
    ) -> None:
        sitemap_resp = MagicMock()
        sitemap_resp.raise_for_status = MagicMock()
        sitemap_resp.text = _sitemap([_JOB_URL_1])

        detail_resp = MagicMock()
        detail_resp.status_code = 200
        detail_resp.text = _job_page(title="Kassierer", locality="Hamburg", country="Germany")

        mock_get.side_effect = [sitemap_resp, detail_resp]

        jobs = fetcher.fetch()

        assert len(jobs) == 1
        assert jobs[0].title == "Kassierer"
