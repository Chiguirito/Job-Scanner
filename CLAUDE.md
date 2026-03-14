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
  → store.filter_new()   # save all jobs (all regions) to DB
  → store.mark_closed()  # mark jobs absent from this scan as inactive
  → filter_by_region()   # narrow to configured regions for description fetching
  → enrich_descriptions() # fetch full JDs only for region-filtered jobs
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

### Pyramid
Three layers — all live in `tests/`, all run on every commit except `@pytest.mark.live`:

| Layer | Folder | What it tests | HTTP |
|---|---|---|---|
| Unit | `tests/unit/` | Single class/function in isolation | Mocked via `unittest.mock.patch` |
| Integration | `tests/integration/` | Multiple modules wired together | Fixture JSON files (no network) |
| E2E recorded | `tests/e2e/` | Full `main()` pipeline | `vcrpy` cassettes (recorded once, replayed) |
| E2E live | `tests/e2e/` | Same, against real endpoints | Real network — mark `@pytest.mark.live` |

Run all non-live tests: `pytest`
Run live tests only: `pytest -m live`

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

# Run all tests (unit + integration + E2E recorded)
pytest

# Run live E2E tests (requires network + real API access)
pytest -m live

# Run scanner
python src/main.py
```

- Never hardcode API keys or credentials — always read from environment variables.
- `data/` is gitignored and created at runtime; never commit it.
