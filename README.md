# Job Scanner

Daily job scanner that fetches new postings from target companies and scores them for fit using Claude AI.

## How it works

1. **Fetches** new job postings from target company career pages (Greenhouse, Lever, etc.)
2. **Deduplicates** against previously seen jobs (SQLite store)
3. **Scores** each new job for fit against a candidate profile using Claude
4. **Notifies** with a digest of high-scoring matches

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in your API keys in .env
```

## Configuration

- `config/companies.yaml` — list of target companies and their ATS details
- `config/profile.md` — candidate profile used for fit scoring

## Running

```bash
python src/main.py
```

## Deployment

Runs daily via GitHub Actions (.github/workflows/daily-scan.yml).
API keys are stored as GitHub Actions Secrets.
