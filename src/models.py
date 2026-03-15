from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional, Any


@dataclass(frozen=True)
class Job:
    """A normalised job posting returned by any fetcher."""

    title: str
    url: str
    company: str
    ats_job_id: str
    location: str = ""
    department: str = ""
    description: str = ""
    posted_date: Optional[date] = None
    metadata: dict = field(default_factory=dict)

    @property
    def unique_key(self) -> str:
        """Stable identifier used for deduplication."""
        return f"{self.company}::{self.ats_job_id}"


@dataclass
class HardRequirements:
    """Job requirements that automatically disqualify a posting if not met."""

    salary_min: Optional[int] = None
    title_keywords: list[str] = field(default_factory=list)


@dataclass
class SoftRequirements:
    """Preferred job attributes that contribute to the desirability score."""

    prefers_remote: bool = False
    preferred_industries: list[str] = field(default_factory=list)


@dataclass
class SearchConfig:
    """A named job search combining region filter, scoring requirements, and notification target."""

    name: str
    regions: list[str]
    profile_path: str
    hard: HardRequirements = field(default_factory=HardRequirements)
    soft: SoftRequirements = field(default_factory=SoftRequirements)
    notify: str = ""


@dataclass
class SearchScore:
    """Scoring result for a job evaluated against a specific search config."""

    unique_key: str
    search_name: str
    fit_score: int
    desirability_score: int
    hard_fail: bool
    hard_fail_reason: str
    score_detail: dict[str, Any]
    stage_reached: int
    profile_hash: str
    requirements_hash: str
    scored_at: str = ""
