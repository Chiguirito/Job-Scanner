from src.fetchers.base import BaseFetcher
from src.fetchers.workday import WorkdayFetcher

FETCHER_TYPES: dict[str, type[BaseFetcher]] = {
    "workday": WorkdayFetcher,
}

__all__ = ["BaseFetcher", "WorkdayFetcher", "FETCHER_TYPES"]
