from __future__ import annotations

from abc import ABC, abstractmethod

from src.models import Job


class BaseFetcher(ABC):
    """Common interface for all ATS fetchers."""

    @abstractmethod
    def fetch(self) -> list[Job]:
        """Fetch all current job postings and return normalised Job objects."""
        ...
