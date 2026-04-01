from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml

from src.fetchers import FETCHER_TYPES
from src.fetchers.deutschepost import DeutschePostConfig
from src.fetchers.google import GoogleConfig
from src.fetchers.greenhouse import GreenhouseConfig
from src.fetchers.mercedesbenz import MercedesBenzConfig
from src.fetchers.smartrecruiters import SmartRecruitersConfig
from src.fetchers.successfactors import SuccessFactorsConfig
from src.fetchers.volkswagen import VolkswagenConfig
from src.fetchers.workday import WorkdayConfig
from src.models import HardRequirements, Job, SearchConfig, SoftRequirements
from src.scorer import JobScorer
from src.store import DEFAULT_DB_PATH, JobStore

LOG_PATH = Path("logs/scan.log")
LOG_PATH.parent.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_PATH),
    ],
)
logger = logging.getLogger(__name__)

CONFIG_PATH = Path("config/companies.yaml")
SEARCHES_CONFIG_PATH = Path("config/searches.yaml")
COMPANY_WORKERS = 8


def load_config(path: Path = CONFIG_PATH) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def load_searches(path: Path = SEARCHES_CONFIG_PATH) -> list[SearchConfig]:
    with open(path) as f:
        data = yaml.safe_load(f)
    searches = []
    for s in data.get("searches", []):
        reqs = s.get("requirements", {})
        hard_cfg = reqs.get("hard", {})
        soft_cfg = reqs.get("soft", {})
        searches.append(
            SearchConfig(
                name=s["name"],
                regions=s.get("regions", []),
                profile_path=s["profile_path"],
                hard=HardRequirements(
                    salary_min=hard_cfg.get("salary_min"),
                    title_keywords=hard_cfg.get("title_keywords", []),
                ),
                soft=SoftRequirements(
                    prefers_remote=soft_cfg.get("prefers_remote", False),
                    preferred_industries=soft_cfg.get("preferred_industries", []),
                ),
                notify=s.get("notify", ""),
            )
        )
    return searches


def build_fetcher(company_cfg: dict):
    ats = company_cfg["ats"]
    fetcher_cls = FETCHER_TYPES[ats]
    cfg = company_cfg["config"]

    if ats == "deutschepost":
        config = DeutschePostConfig(company=company_cfg["name"])
    elif ats == "workday":
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
    elif ats == "google":
        config = GoogleConfig(company=company_cfg["name"])
    elif ats == "mercedesbenz":
        config = MercedesBenzConfig(company=company_cfg["name"])
    elif ats == "smartrecruiters":
        config = SmartRecruitersConfig(
            company=company_cfg["name"],
            company_id=cfg["company_id"],
        )
    elif ats == "successfactors":
        config = SuccessFactorsConfig(
            company=company_cfg["name"],
            feed_url=cfg["feed_url"],
        )
    elif ats == "volkswagen":
        config = VolkswagenConfig(company=company_cfg["name"])
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
) -> tuple[str, list[Job], set[str]]:
    """Fetch, filter, and enrich one company's jobs. Pure I/O — no store access.

    Storage design:
    - ALL jobs (every region) are returned for storage so the DB is a complete mirror.
    - Descriptions are fetched only for region-matched NEW jobs to avoid unnecessary
      API calls. Already-stored jobs and out-of-region jobs are saved without descriptions.

    Returns (company_name, all_jobs_with_enriched_descriptions_where_applicable, all_active_keys).
    """
    name = company_cfg["name"]
    fetcher = build_fetcher(company_cfg)

    jobs, raw_postings = fetcher.fetch_listings()
    logger.info("Found %d total listings for %s", len(jobs), name)

    all_active_keys = {j.unique_key for j in jobs}

    # Fetch descriptions only for region-matched new jobs
    regional_jobs, regional_postings = filter_by_region(jobs, raw_postings, regions)
    logger.info("%d listings match region filter for %s", len(regional_jobs), name)

    new_regional_keys = {j.unique_key for j in regional_jobs if j.unique_key not in known_keys}
    if new_regional_keys:
        new_regional = [j for j in regional_jobs if j.unique_key in new_regional_keys]
        new_raw = [r for j, r in zip(regional_jobs, regional_postings) if j.unique_key in new_regional_keys]
        enriched = fetcher.enrich_descriptions(new_regional, new_raw)
        logger.info("Fetched descriptions for %d new jobs at %s", len(enriched), name)
        enriched_by_key = {j.unique_key: j for j in enriched}
        jobs = [enriched_by_key.get(j.unique_key, j) for j in jobs]

    return name, jobs, all_active_keys


def score_search(search: SearchConfig, store: JobStore, scorer: JobScorer) -> None:
    """Score all unscored (or stale) jobs for a single search config."""
    p_hash = scorer.profile_hash(search)
    r_hash = scorer.requirements_hash(search)

    jobs = store.get_unscored_jobs_for_search(search.name, p_hash, r_hash, search.regions)
    logger.info("Scoring %d jobs for search '%s'", len(jobs), search.name)

    for job in jobs:
        result = scorer.score(job, search)
        store.save_score(result)
        if result.hard_fail:
            logger.debug("[%s] SKIP %s — %s", search.name, job.title, result.hard_fail_reason)
        else:
            logger.info(
                "[%s] fit=%d desire=%d — %s @ %s",
                search.name, result.fit_score, result.desirability_score,
                job.title, job.company,
            )

    logger.info("Done scoring '%s' (%d jobs processed).", search.name, len(jobs))


def _run_fetch(config_path: Path, store: JobStore) -> None:
    config = load_config(config_path)
    regions = config.get("regions", [])
    companies = config.get("companies", [])

    if regions:
        logger.info("Region filter: %s", regions)

    known_keys = store.get_all_known_keys()

    workers = min(len(companies), COMPANY_WORKERS)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(process_company, cfg, regions, known_keys): cfg
            for cfg in companies
        }
        for future in as_completed(futures):
            name, all_jobs, all_active_keys = future.result()

            new_count = len([j for j in all_jobs if j.unique_key not in known_keys])
            store.save(all_jobs)
            closed = store.mark_closed(name, all_active_keys)

            logger.info("%d new jobs for %s", new_count, name)
            if closed:
                logger.info("%d listings closed for %s", len(closed), name)

    logger.info(
        "Done. Total: %d jobs (%d active)",
        store.count(),
        store.count(active_only=True),
    )


def _run_scoring(target: str | None, searches_path: Path, store: JobStore) -> None:
    searches = load_searches(searches_path)
    if target is not None:
        searches = [s for s in searches if s.name == target]
        if not searches:
            logger.error("No search named '%s' in %s", target, searches_path)
            return
    scorer = JobScorer()
    for search in searches:
        score_search(search, store, scorer)


def main(
    config_path: Path = CONFIG_PATH,
    db_path: Path = DEFAULT_DB_PATH,
    searches_path: Path = SEARCHES_CONFIG_PATH,
    score: str | None = None,
) -> None:
    store = JobStore(db_path)
    if score is not None:
        _run_scoring(score if score != "__all__" else None, searches_path, store)
    else:
        _run_fetch(config_path, store)
    store.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Job Scanner")
    parser.add_argument(
        "--score",
        nargs="?",
        const="__all__",
        metavar="SEARCH_NAME",
        help="Score jobs. Omit SEARCH_NAME to run all searches.",
    )
    args = parser.parse_args()
    main(score=args.score)
