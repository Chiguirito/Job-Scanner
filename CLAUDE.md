# Claude Guidelines for Job-Scanner

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
    base.py      — BaseFetcher abstract class (fetch_listings, enrich_descriptions)
    workday.py   — WorkdayFetcher: paginates Workday CXS API, strips HTML from descriptions
    __init__.py  — FETCHER_TYPES registry mapping ATS name → fetcher class

config/
  companies.yaml — Target companies: ATS type, API coords, optional search filters
  profile.md     — Candidate profile used by scorer for fit comparison (not yet created)

data/
  jobs.db        — SQLite database (gitignored, created at runtime)
```

### Pipeline (per company, each run)
```
fetch_listings()          # paginated API calls, no descriptions yet
  → filter_by_region()   # drop jobs outside configured regions
  → enrich_descriptions() # fetch full JDs only for filtered jobs
  → store.filter_new()   # deduplicate; save all; return only new ones
  → store.mark_closed()  # mark jobs absent from this scan as inactive
  → scorer (pending)     # score new jobs against config/profile.md
  → notifier (pending)   # email digest of matches above score threshold
```

### Key data flow
- `Job` (models.py) is a frozen dataclass — immutable after creation; enrichment returns a new instance.
- `unique_key` = `"<company>::<ats_job_id>"` — stable dedup identifier across runs.
- `JobStore.filter_new()` saves all seen jobs (updating `last_seen`) and returns only the new ones.
- Region filter runs before description fetching to avoid unnecessary API calls.

### Adding a new ATS
1. Create `src/fetchers/<ats_name>.py` with a class subclassing `BaseFetcher`.
2. Implement `fetch_listings() -> tuple[list[Job], list[dict]]` and `enrich_descriptions()`.
3. Register in `FETCHER_TYPES` in `src/fetchers/__init__.py`.
4. Add a matching entry in `config/companies.yaml`.

## Architecture rules
- New ATS fetchers must subclass `BaseFetcher` (`src/fetchers/base.py`) and register in `FETCHER_TYPES` (`src/fetchers/__init__.py`).
- `main.py` is orchestration only — business logic lives in dedicated modules (`scorer.py`, `notifier.py`, `store.py`).
- `models.py` contains plain dataclasses only — no business logic.
- Read env vars at call time, not at import time, so tests can patch them easily.

## Testing conventions
- Run `pytest` before every commit.
- All external HTTP calls must be mocked with `unittest.mock.patch`.
- Use the `tmp_path` pytest fixture for any file or database I/O.
- Tests live in `tests/`; mirror the `src/` module structure for test file names.

## Dev commands & environment
```bash
# Setup
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# Run tests
pytest

# Run scanner
python src/main.py
```

- Never hardcode API keys or credentials — always read from environment variables.
- `data/` is gitignored and created at runtime; never commit it.
