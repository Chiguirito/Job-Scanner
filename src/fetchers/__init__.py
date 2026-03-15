from src.fetchers.base import BaseFetcher
from src.fetchers.bmw import BMWFetcher
from src.fetchers.google import GoogleFetcher
from src.fetchers.greenhouse import GreenhouseFetcher
from src.fetchers.mercedesbenz import MercedesBenzFetcher
from src.fetchers.volkswagen import VolkswagenFetcher
from src.fetchers.workday import WorkdayFetcher

FETCHER_TYPES: dict[str, type[BaseFetcher]] = {
    "bmw": BMWFetcher,
    "google": GoogleFetcher,
    "greenhouse": GreenhouseFetcher,
    "mercedesbenz": MercedesBenzFetcher,
    "volkswagen": VolkswagenFetcher,
    "workday": WorkdayFetcher,
}

__all__ = ["BaseFetcher", "BMWFetcher", "GoogleFetcher", "GreenhouseFetcher", "MercedesBenzFetcher", "VolkswagenFetcher", "WorkdayFetcher", "FETCHER_TYPES"]
