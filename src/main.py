from __future__ import annotations

import logging
from pathlib import Path

import yaml

from src.fetchers import FETCHER_TYPES
from src.fetchers.workday import WorkdayConfig
from src.models import Job
from src.store import JobStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

CONFIG_PATH = Path("config/companies.yaml")


def load_config(path: Path = CONFIG_PATH) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def build_fetcher(company_cfg: dict):
    ats = company_cfg["ats"]
    fetcher_cls = FETCHER_TYPES[ats]
    cfg = company_cfg["config"]

    if ats == "workday":
        config = WorkdayConfig(
            company=company_cfg["name"],
            base_url=cfg["base_url"],
            site_path=cfg["site_path"],
            site_name=cfg["site_name"],
            search_text=cfg.get("search_text", ""),
            applied_facets=cfg.get("applied_facets"),
            fetch_descriptions=False,  # descriptions fetched separately after filtering
        )
    else:
        raise ValueError(f"Unknown ATS type: {ats}")

    return fetcher_cls(config)


def filter_by_region(
    jobs: list[Job],
    raw_postings: list[dict],
    region_prefixes: list[str],
) -> tuple[list[Job], list[dict]]:
    """Keep only jobs whose location matches any region prefix.

    Returns filtered (jobs, raw_postings) in parallel.
    """
    if not region_prefixes:
        return jobs, raw_postings
    filtered = [
        (job, posting)
        for job, posting in zip(jobs, raw_postings)
        if any(job.location.startswith(prefix) for prefix in region_prefixes)
    ]
    if not filtered:
        return [], []
    filtered_jobs, filtered_postings = zip(*filtered)
    return list(filtered_jobs), list(filtered_postings)


def main() -> None:
    config = load_config()
    regions = config.get("regions", [])
    companies = config.get("companies", [])
    store = JobStore()

    if regions:
        logger.info("Region filter: %s", regions)

    for company_cfg in companies:
        name = company_cfg["name"]
        logger.info("Scanning %s...", name)

        fetcher = build_fetcher(company_cfg)

        # 1. Fetch listings (fast — no descriptions)
        jobs, raw_postings = fetcher.fetch_listings()
        logger.info("Found %d total listings for %s", len(jobs), name)

        # 2. Filter by region
        jobs, raw_postings = filter_by_region(jobs, raw_postings, regions)
        logger.info("%d listings after region filter", len(jobs))

        # 3. Fetch descriptions only for filtered jobs
        if jobs:
            jobs = fetcher.enrich_descriptions(jobs, raw_postings)
            logger.info("Fetched descriptions for %d jobs", len(jobs))

        # 4. Store and dedup
        new_jobs = store.filter_new(jobs)
        logger.info("%d new jobs for %s", len(new_jobs), name)

        # 5. Mark closed listings
        active_keys = {j.unique_key for j in jobs}
        closed = store.mark_closed(name, active_keys)
        if closed:
            logger.info("%d listings closed for %s", len(closed), name)

    logger.info(
        "Done. Total: %d jobs (%d active)",
        store.count(),
        store.count(active_only=True),
    )
    store.close()


if __name__ == "__main__":
    main()
