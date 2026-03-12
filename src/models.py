from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


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
