from __future__ import annotations

import hashlib
import json
from pathlib import Path

import anthropic

from src.models import HardRequirements, Job, SearchConfig, SearchScore, SoftRequirements

_MODEL = "claude-haiku-4-5-20251001"

_PROMPT_TEMPLATE = """\
You are evaluating a job posting for a specific candidate.

## Candidate Profile
{profile}

## Search Requirements
Hard requirements (fail if clearly not met):
{hard_requirements}

Soft preferences:
{soft_preferences}

## Job Posting
Title: {title}
Company: {company}
Location: {location}
Department: {department}
Description:
{description}

## Task
Score this job on two dimensions:

**Fit score (0–100)**: How likely is this candidate to get an offer if they apply?
- 0–30: Wrong skills, seniority, or domain
- 31–60: Partial overlap but significant gaps
- 61–80: Most requirements met
- 81–100: Strong match across skills, seniority, and domain

**Desirability score (0–100)**: How well does this job match the candidate's requirements?
- Consider salary (estimate a likely range if not stated; flag low confidence)
- Consider remote/on-site policy, role scope, growth potential
- Set hard_fail=true if a hard requirement is clearly not met

Respond with valid JSON only, no other text:
{{
  "fit_score": <integer 0-100>,
  "fit_reasoning": "<one sentence>",
  "desirability_score": <integer 0-100>,
  "desirability_reasoning": "<one sentence>",
  "hard_fail": <true or false>,
  "hard_fail_reason": "<empty string or brief reason>"
}}\
"""


class JobScorer:
    """Multi-stage job scorer that evaluates both candidate fit and job desirability.

    Stage 1 (free): rule-based hard-requirement checks against job title.
    Stage 3 (LLM): dual fit + desirability scoring via Claude Haiku.
    """

    def __init__(self) -> None:
        self._profile_cache: dict[str, str] = {}

    def score(self, job: Job, search: SearchConfig) -> SearchScore:
        """Run the scoring funnel for a job against a search config."""
        p_hash = self.profile_hash(search)
        r_hash = self.requirements_hash(search)

        stage1_result = self._stage1(job, search, p_hash, r_hash)
        if stage1_result is not None:
            return stage1_result

        return self._stage3(job, search, p_hash, r_hash)

    def profile_hash(self, search: SearchConfig) -> str:
        """SHA-256 (truncated) of the profile file contents."""
        content = self._load_profile(search)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def requirements_hash(self, search: SearchConfig) -> str:
        """SHA-256 (truncated) of the serialised hard + soft requirements."""
        data = json.dumps(
            {
                "hard": {
                    "salary_min": search.hard.salary_min,
                    "title_keywords": sorted(search.hard.title_keywords),
                },
                "soft": {
                    "prefers_remote": search.soft.prefers_remote,
                    "preferred_industries": sorted(search.soft.preferred_industries),
                },
            },
            sort_keys=True,
        )
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    # ------------------------------------------------------------------
    # Funnel stages
    # ------------------------------------------------------------------

    def _stage1(
        self, job: Job, search: SearchConfig, p_hash: str, r_hash: str
    ) -> SearchScore | None:
        """Rule-based pre-filter on title keywords. Returns a hard-fail score or None."""
        if search.hard.title_keywords:
            title_lower = job.title.lower()
            if not any(kw.lower() in title_lower for kw in search.hard.title_keywords):
                return SearchScore(
                    unique_key=job.unique_key,
                    search_name=search.name,
                    fit_score=0,
                    desirability_score=0,
                    hard_fail=True,
                    hard_fail_reason=(
                        f"Title '{job.title}' does not match required keywords: "
                        f"{search.hard.title_keywords}"
                    ),
                    score_detail={},
                    stage_reached=1,
                    profile_hash=p_hash,
                    requirements_hash=r_hash,
                )
        return None

    def _stage3(
        self, job: Job, search: SearchConfig, p_hash: str, r_hash: str
    ) -> SearchScore:
        """LLM-based dual scoring via Claude Haiku with the full job description."""
        profile = self._load_profile(search)
        client = anthropic.Anthropic()

        prompt = _PROMPT_TEMPLATE.format(
            profile=profile,
            hard_requirements=_format_hard(search.hard),
            soft_preferences=_format_soft(search.soft),
            title=job.title,
            company=job.company,
            location=job.location,
            department=job.department,
            description=job.description,
        )
        message = client.messages.create(
            model=_MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        detail = _parse_json_response(message.content[0].text)

        return SearchScore(
            unique_key=job.unique_key,
            search_name=search.name,
            fit_score=int(detail.get("fit_score", 0)),
            desirability_score=int(detail.get("desirability_score", 0)),
            hard_fail=bool(detail.get("hard_fail", False)),
            hard_fail_reason=detail.get("hard_fail_reason", ""),
            score_detail=detail,
            stage_reached=3,
            profile_hash=p_hash,
            requirements_hash=r_hash,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_profile(self, search: SearchConfig) -> str:
        path = str(Path(search.profile_path).expanduser())
        if path not in self._profile_cache:
            p = Path(path)
            if not p.exists():
                raise FileNotFoundError(f"Candidate profile not found: {p}")
            self._profile_cache[path] = p.read_text()
        return self._profile_cache[path]


def _format_hard(hard: HardRequirements) -> str:
    lines = []
    if hard.salary_min:
        lines.append(
            f"- Minimum salary: {hard.salary_min:,} "
            "(estimate if not stated; hard_fail if clearly below)"
        )
    if hard.title_keywords:
        lines.append(f"- Title must match one of: {', '.join(hard.title_keywords)}")
    return "\n".join(lines) if lines else "None specified"


def _format_soft(soft: SoftRequirements) -> str:
    lines = []
    if soft.prefers_remote:
        lines.append("- Prefers remote or hybrid")
    if soft.preferred_industries:
        lines.append(f"- Preferred industries: {', '.join(soft.preferred_industries)}")
    return "\n".join(lines) if lines else "None specified"


def _parse_json_response(text: str) -> dict:
    """Extract and parse the first JSON object from Claude's response."""
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        return json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return {}
