# Job Scanner

Fetches job postings from multiple company career pages, deduplicates them in SQLite, and scores each posting against named search profiles using Claude AI. Designed to run daily and surface only the highest-fit, highest-desirability opportunities.

---

## How it works

There are two independent pipelines, both run via `src/main.py`:

### 1. Fetch pipeline

```
python src/main.py
```

Fetches all current job postings from every company in `config/companies.yaml` and keeps the local database in sync.

```
Load config + snapshot known_keys from DB
        │
        ▼  (up to 8 concurrent workers)
┌─────────────────────────────────────────────────────┐
│  per company (no DB access):                        │
│                                                     │
│  fetch_listings()     — paginated API calls         │
│    → filter_by_region()  — narrow to config regions │
│    → enrich_descriptions()  — fetch full JDs only   │
│      for new region-matched jobs                    │
└─────────────────────────────────────────────────────┘
        │  (back in main thread)
        ▼
  store.save(all_jobs)      — upsert all regions into DB
  store.mark_closed()       — mark absent jobs inactive
```

**Key behaviours:**
- All jobs from all regions are stored — the DB is a complete mirror of every company's board.
- Full job descriptions are fetched only for **new** jobs that match the configured regions, minimising API calls.
- `known_keys` is snapshotted before threads start so workers can identify new jobs without touching the DB concurrently.
- Jobs that reappear after being marked closed are automatically reactivated on the next fetch.

### 2. Scoring pipeline

```
python src/main.py --score                         # all searches
python src/main.py --score "Engineering Manager Germany"  # one search
```

Runs after fetching. Each entry in `config/searches.yaml` is an independent pass over the database. A job is scored for a given search only if it has never been scored for that search before, **or** if the candidate profile or requirements have changed since the last score (detected via SHA-256 hashes). Adding a new search to the config automatically backfills all existing jobs on the next run.

```
For each SearchConfig:
    compute profile_hash + requirements_hash
    fetch unscored jobs from DB (active, with description, matching regions)
            │
            ▼  Stage 1 — Rule-based (free)
    Does job title contain any required keyword?
      No  → hard_fail immediately, skip LLM call
      Yes → continue
            │
            ▼  Stage 3 — Claude Haiku
    Prompt: candidate profile + hard/soft requirements + full job description
    Response (JSON):
      fit_score          0–100   likelihood of getting an offer
      desirability_score 0–100   how well the job matches the candidate's wants
      hard_fail          bool    true if salary or other hard req clearly not met
      hard_fail_reason   string
    → save to search_scores table
```

**Fit score** answers: *can I get it?* It measures alignment between the candidate's background and what the job requires — skills, seniority, domain experience.

**Desirability score** answers: *do I want it?* It measures alignment between the job's offering and the candidate's requirements — salary (estimated if not stated), remote policy, role scope, growth.

These are kept separate intentionally. A high-fit / low-desirability job (you'd get it but it underpays) and a low-fit / high-desirability job (dream role, but a stretch) are both worth knowing about for different reasons.

---

## Supported ATS platforms

| ATS | Mechanism | Descriptions |
|---|---|---|
| Workday | CXS JSON API, concurrent pagination | Separate detail fetch |
| Greenhouse | Public board API, single GET | Separate detail fetch |
| Google Careers | RSS feed (XML) | Inline in feed |
| Mercedes-Benz | Undocumented JSON search API | Inline in response |
| Volkswagen Group | SAP SuccessFactors RSS (Google Base XML) | Inline in feed |

---

## Configuration

### `config/companies.yaml`

Defines which companies to scan and how to reach their ATS:

```yaml
regions:
  - "Germany"
  - "DE"

companies:
  - name: NVIDIA
    ats: workday
    config:
      base_url: "https://nvidia.wd5.myworkdayjobs.com"
      site_path: "/wday/cxs/nvidia/NVIDIAExternalCareerSite"
      site_name: "NVIDIAExternalCareerSite"

  - name: Waymo
    ats: greenhouse
    config:
      board_slug: "waymo"
```

`regions` controls which jobs get full descriptions fetched. All jobs are stored regardless of region.

### `config/searches.yaml`

Defines named job searches. Each search scores the DB independently:

```yaml
searches:
  - name: Engineering Manager Germany
    regions:
      - Germany
    profile_path: ~/private/profile.md   # outside the repo
    requirements:
      hard:
        salary_min: 150000              # auto-fail if clearly below
        title_keywords:                 # stage 1 free filter
          - engineering manager
          - head of engineering
      soft:
        prefers_remote: true
    notify: you@email.com
```

**`profile_path`** points to a Markdown file with the candidate's background. Keep this outside the repository. Each search can have its own profile (useful for targeting different roles with different narratives).

**Hard requirements** are enforced in two places:
- `title_keywords` — checked locally in Stage 1, costs zero tokens
- `salary_min` — evaluated by Claude in Stage 3, since salary is rarely stated explicitly in JDs

**Soft requirements** are factored into `desirability_score` but never cause an automatic failure.

---

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Set ANTHROPIC_API_KEY in .env
```

Create your candidate profile somewhere outside the repo and point `profile_path` in `searches.yaml` at it.

---

## Running

```bash
# Fetch all companies into the local DB
python src/main.py

# Score all configured searches against the DB
python src/main.py --score

# Score a single search by name
python src/main.py --score "Engineering Manager Germany"
```

Run fetch first, then score. They are intentionally separate so you can iterate on search configs and re-score without re-fetching.

---

## Database

SQLite at `data/jobs.db` (gitignored, created at runtime). Two tables:

**`jobs`** — one row per unique job posting, keyed by `<company>::<ats_job_id>`. Upserted on every fetch; `is_active` flipped to 0 when a job disappears from the company's board.

**`search_scores`** — one row per `(unique_key, search_name)` pair. Records both scores, the hard_fail status, the full JSON detail from Claude, and the profile/requirements hashes used. Stale rows (hash mismatch) are automatically re-scored on the next run.

---

## Deployment

A GitHub Actions workflow (`.github/workflows/daily-scan.yml`) runs the fetch pipeline daily at 07:00 UTC. The SQLite database is persisted between runs using the Actions cache.

Required secrets: `ANTHROPIC_API_KEY`, `NOTIFY_EMAIL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`.

---

## Adding a new company

1. Find the ATS type (Workday, Greenhouse, or add a new fetcher).
2. Add an entry to `config/companies.yaml`.
3. For a new ATS: create `src/fetchers/<ats>.py` subclassing `BaseFetcher`, register it in `FETCHER_TYPES` (`src/fetchers/__init__.py`), and add a `build_fetcher()` branch in `src/main.py`. See `CLAUDE.md` for the full checklist.
