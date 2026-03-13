from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml

from src.fetchers import FETCHER_TYPES
from src.fetchers.greenhouse import GreenhouseConfig
from src.fetchers.workday import WorkdayConfig
from src.models import Job
from src.store import DEFAULT_DB_PATH, JobStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

CONFIG_PATH = Path("config/companies.yaml")
COMPANY_WORKERS = 8


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
    elif ats == "greenhouse":
        config = GreenhouseConfig(
            company=company_cfg["name"],
            board_slug=cfg["board_slug"],
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
    """Keep only jobs whose location contains any region term (case-insensitive).

    Supports both "Germany, Munich" (Workday) and "Munich, Germany" (Greenhouse)
    location formats. Returns filtered (jobs, raw_postings) in parallel.
    """
    if not region_prefixes:
        return jobs, raw_postings
    filtered = [
        (job, posting)
        for job, posting in zip(jobs, raw_postings)
        if any(prefix.lower() in job.location.lower() for prefix in region_prefixes)
    ]
    if not filtered:
        return [], []
    filtered_jobs, filtered_postings = zip(*filtered)
    return list(filtered_jobs), list(filtered_postings)


def process_company(
    company_cfg: dict,
    regions: list[str],
    known_keys: set[str],
) -> tuple[str, list[Job], list[Job], set[str]]:
    """Fetch, filter, and enrich one company's jobs. Pure I/O — no store access.

    Returns (company_name, enriched_new_jobs, seen_jobs, active_keys).
    Descriptions are fetched only for jobs absent from known_keys, so repeat
    runs skip description fetches for already-stored listings.
    """
    name = company_cfg["name"]
    fetcher = build_fetcher(company_cfg)

    jobs, raw_postings = fetcher.fetch_listings()
    logger.info("Found %d total listings for %s", len(jobs), name)

    jobs, raw_postings = filter_by_region(jobs, raw_postings, regions)
    logger.info("%d listings after region filter for %s", len(jobs), name)

    active_keys = {j.unique_key for j in jobs}
    raw_by_key = {j.unique_key: r for j, r in zip(jobs, raw_postings)}

    new_jobs = [j for j in jobs if j.unique_key not in known_keys]
    seen_jobs = [j for j in jobs if j.unique_key in known_keys]

    if new_jobs:
        new_raw = [raw_by_key[j.unique_key] for j in new_jobs]
        new_jobs = fetcher.enrich_descriptions(new_jobs, new_raw)
        logger.info("Fetched descriptions for %d new jobs at %s", len(new_jobs), name)

    return name, new_jobs, seen_jobs, active_keys


def main(config_path: Path = CONFIG_PATH, db_path: Path = DEFAULT_DB_PATH) -> None:
    config = load_config(config_path)
    regions = config.get("regions", [])
    companies = config.get("companies", [])
    store = JobStore(db_path)

    if regions:
        logger.info("Region filter: %s", regions)

    # Snapshot of known keys before this run — passed to threads so they can
    # determine which jobs are new without accessing the store concurrently.
    known_keys = store.get_all_known_keys()

    workers = min(len(companies), COMPANY_WORKERS)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(process_company, cfg, regions, known_keys): cfg
            for cfg in companies
        }
        for future in as_completed(futures):
            name, new_jobs, seen_jobs, active_keys = future.result()

            store.save(new_jobs + seen_jobs)
            closed = store.mark_closed(name, active_keys)

            logger.info("%d new jobs for %s", len(new_jobs), name)
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
