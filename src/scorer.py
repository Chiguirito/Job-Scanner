from __future__ import annotations

import os
from pathlib import Path

import anthropic

from src.models import Job

_MODEL = "claude-haiku-4-5-20251001"

_PROMPT_TEMPLATE = """\
You are evaluating job fit for a candidate.

Candidate profile:
{profile}

Job posting:
Title: {title}
Company: {company}
Location: {location}
Department: {department}
Description:
{description}

Rate how well this job matches the candidate on a scale from 0 to 100, where:
- 0–30: Poor fit (wrong skills, seniority, or domain)
- 31–60: Partial fit (some overlap but significant gaps)
- 61–80: Good fit (most requirements met)
- 81–100: Excellent fit (strong match across skills, seniority, and domain)

Respond in exactly this format (no other text):
SCORE: <integer>
REASON: <one sentence>\
"""


class JobScorer:
    """Scores job postings against a candidate profile using the Claude API."""

    def score(self, job: Job) -> tuple[int, str]:
        """Score a job against the candidate profile.

        Reads CANDIDATE_PROFILE_PATH and ANTHROPIC_API_KEY from env at call time.
        Returns (score, reason) where score is 0–100 and reason is one sentence.
        """
        profile = _load_profile()
        client = anthropic.Anthropic()
        prompt = _PROMPT_TEMPLATE.format(
            profile=profile,
            title=job.title,
            company=job.company,
            location=job.location,
            department=job.department,
            description=job.description,
        )
        message = client.messages.create(
            model=_MODEL,
            max_tokens=128,
            messages=[{"role": "user", "content": prompt}],
        )
        return _parse_response(message.content[0].text)


def _load_profile() -> str:
    path = os.getenv("CANDIDATE_PROFILE_PATH")
    if not path:
        raise RuntimeError("CANDIDATE_PROFILE_PATH env var is not set")
    profile_path = Path(path)
    if not profile_path.exists():
        raise FileNotFoundError(f"Candidate profile not found: {profile_path}")
    return profile_path.read_text()


def _parse_response(text: str) -> tuple[int, str]:
    score = 0
    reason = ""
    for line in text.strip().splitlines():
        line = line.strip()
        if line.startswith("SCORE:"):
            score = int(line.split(":", 1)[1].strip())
        elif line.startswith("REASON:"):
            reason = line.split(":", 1)[1].strip()
    return score, reason
