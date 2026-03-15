# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commenting style
- Add docstrings to classes and any method where the name alone doesn't convey intent or important caveats.
- Do not add docstrings to simple helpers or one-liners.
- Do not add inline comments unless explaining a non-obvious external API quirk or a non-trivial algorithm step.
- Never add comments that restate what the code already says.

## Architecture

### Module map
```
src/
  main.py        — Orchestrator: loads config, runs the pipeline per company
  models.py      — Job dataclass (plain data, no logic)
  store.py       — JobStore: SQLite persistence, deduplication, closed-listing tracking
  scorer.py      — JobScorer: scores jobs for candidate fit using Claude API (not yet implemented)
  notifier.py    — Sends email digest of high-scoring matches (not yet implemented)
  fetchers/
    base.py        — BaseFetcher abstract class; single abstract method: fetch() -> list[Job]
    workday.py     — WorkdayFetcher: concurrent pagination of Workday CXS API
    greenhouse.py  — GreenhouseFetcher: Greenhouse public board API (single GET for listings)
    google.py      — GoogleFetcher: Google Careers RSS feed (descriptions included inline)
    mercedesbenz.py — MercedesBenzFetcher: undocumented Mercedes-Benz JSON API (descriptions included inline)
    __init__.py    — FETCHER_TYPES registry mapping ATS name → fetcher class

config/
  companies.yaml — Target companies: ATS type, API coords, optional search filters
  profile.md     — Candidate profile used by scorer for fit comparison (not yet created)

data/
  jobs.db        — SQLite database (gitignored, created at runtime)

logs/
  scan.log       — Scan log file (gitignored, created at runtime)
```

### Pipeline (per company, each run)
Companies are processed concurrently via `ThreadPoolExecutor` (up to 8 workers). Each `process_company` call is pure I/O with no store access — all store operations happen in the main thread after each future completes.

```
# Per company (process_company — no store access):
fetch_listings()           # paginated API calls, no descriptions yet
  → filter_by_region()    # narrow to configured regions for description fetching
  → enrich_descriptions() # fetch full JDs only for new region-filtered jobs

# Main thread (after future resolves):
store.save(all_jobs)       # upsert all jobs from all regions into DB
store.mark_closed()        # mark jobs absent from this scan as inactive
```

`known_keys` is snapshotted via `store.get_all_known_keys()` before any threads start and passed to each worker to determine which jobs are new without concurrent store access.

### Key data flow
- `Job` (models.py) is a frozen dataclass — immutable after creation; enrichment returns a new instance.
- `unique_key` = `"<company>::<ats_job_id>"` — stable dedup identifier across runs.
- `JobStore.save()` upserts jobs (inserts new, updates `last_seen` for existing).
- Region filter applies only to description fetching — **all jobs from all regions are stored in the DB**.
- Descriptions are fetched only for region-matched new jobs; already-stored and out-of-region jobs are saved without descriptions.

### Fetcher interface
`BaseFetcher` requires only `fetch() -> list[Job]`. All concrete fetchers also implement two additional methods used by the pipeline:
- `fetch_listings() -> tuple[list[Job], list[dict]]` — returns jobs and raw API dicts (no descriptions)
- `enrich_descriptions(jobs, raw_postings) -> list[Job]` — fetches full JDs; no-op for feeds that include descriptions inline (Google, Mercedes-Benz)

### Location matching
`filter_by_region` uses case-insensitive substring matching so it works across ATS location formats:
- Workday: `"Germany, Munich"` → matches region `"Germany"`
- Greenhouse: `"Munich, Germany"` → matches region `"Germany"`
- Mercedes-Benz: `"Stuttgart, DE"` → matches region `"DE"`
- Google: `"Berlin, Germany"` → matches region `"Germany"`

### Adding a new ATS
1. Create `src/fetchers/<ats_name>.py` with a class subclassing `BaseFetcher`.
2. Implement `fetch()`, `fetch_listings() -> tuple[list[Job], list[dict]]`, and `enrich_descriptions()`.
3. Register in `FETCHER_TYPES` in `src/fetchers/__init__.py`.
4. Add a `elif ats == "<ats_name>"` branch in `build_fetcher()` in `main.py`.
5. Add a matching entry in `config/companies.yaml`.

## Architecture rules
- New ATS fetchers must subclass `BaseFetcher` (`src/fetchers/base.py`) and register in `FETCHER_TYPES` (`src/fetchers/__init__.py`).
- `process_company` in `main.py` must remain pure I/O with no store access — store operations are single-threaded in `main()`.
- `main.py` is orchestration only — business logic lives in dedicated modules (`scorer.py`, `notifier.py`, `store.py`).
- `models.py` contains plain dataclasses only — no business logic.
- Read env vars at call time, not at import time, so tests can patch them easily.

## Testing conventions

### Pyramid
Three layers — all live in `tests/`, all run on every commit except `@pytest.mark.live`:

| Layer | Folder | What it tests | HTTP |
|---|---|---|---|
| Unit | `tests/unit/` | Single class/function in isolation | Mocked via `unittest.mock.patch` |
| Integration | `tests/integration/` | Multiple modules wired together | Fixture JSON files (no network) |
| E2E recorded | `tests/e2e/` | Full `main()` pipeline | `vcrpy` cassettes (recorded once, replayed) |
| E2E live | `tests/e2e/` | Same, against real endpoints | Real network — mark `@pytest.mark.live` |

### Rules
- Unit tests mock all external I/O (`requests`, filesystem, env vars).
- Integration tests use realistic JSON fixture files stored in `tests/fixtures/`; no mocking of business logic.
- E2E recorded tests use `vcrpy` cassettes stored in `tests/cassettes/`; re-record with `VCR_RECORD=all pytest tests/e2e/`.
- Live tests are excluded from CI; use them manually to detect upstream API changes.
- Use the `tmp_path` pytest fixture for any file or database I/O.
- Mirror `src/` module names for test files (e.g. `src/store.py` → `tests/unit/test_store.py`).

## Dev commands & environment
```bash
# Setup
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# Copy and fill in env vars
cp .env.example .env

# Run all tests (unit + integration + E2E recorded)
pytest

# Run a single test file or test function
pytest tests/unit/test_store.py
pytest tests/unit/test_store.py::test_save_upserts

# Run live E2E tests (requires network + real API access)
pytest -m live

# Run scanner
python src/main.py
```

### Required environment variables
See `.env.example` for the full list. Key variables:
- `ANTHROPIC_API_KEY` — required by scorer (not yet implemented)
- `NOTIFY_EMAIL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` — required by notifier (not yet implemented)

`data/` and `logs/` are gitignored and created at runtime; never commit them.
