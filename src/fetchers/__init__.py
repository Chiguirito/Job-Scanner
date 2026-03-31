from src.fetchers.base import BaseFetcher
from src.fetchers.google import GoogleFetcher
from src.fetchers.greenhouse import GreenhouseFetcher
from src.fetchers.mercedesbenz import MercedesBenzFetcher
from src.fetchers.successfactors import SuccessFactorsFetcher
from src.fetchers.volkswagen import VolkswagenFetcher
from src.fetchers.workday import WorkdayFetcher

FETCHER_TYPES: dict[str, type[BaseFetcher]] = {
    "google": GoogleFetcher,
    "greenhouse": GreenhouseFetcher,
    "mercedesbenz": MercedesBenzFetcher,
    "successfactors": SuccessFactorsFetcher,
    "volkswagen": VolkswagenFetcher,
    "workday": WorkdayFetcher,
}

__all__ = ["BaseFetcher", "GoogleFetcher", "GreenhouseFetcher", "MercedesBenzFetcher", "SuccessFactorsFetcher", "VolkswagenFetcher", "WorkdayFetcher", "FETCHER_TYPES"]
