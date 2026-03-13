# Claude Guidelines for Job-Scanner

## Commenting style
- Add docstrings to classes and any method where the name alone doesn't convey intent or important caveats.
- Do not add docstrings to simple helpers or one-liners.
- Do not add inline comments unless explaining a non-obvious external API quirk or a non-trivial algorithm step.
- Never add comments that restate what the code already says.

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
