from src.fetchers.base import BaseFetcher
from src.fetchers.deutschepost import DeutschePostFetcher
from src.fetchers.edeka import EdekaFetcher
from src.fetchers.google import GoogleFetcher
from src.fetchers.greenhouse import GreenhouseFetcher
from src.fetchers.mercedesbenz import MercedesBenzFetcher
from src.fetchers.siemens import SiemensFetcher
from src.fetchers.smartrecruiters import SmartRecruitersFetcher
from src.fetchers.successfactors import SuccessFactorsFetcher
from src.fetchers.volkswagen import VolkswagenFetcher
from src.fetchers.workday import WorkdayFetcher

FETCHER_TYPES: dict[str, type[BaseFetcher]] = {
    "deutschepost": DeutschePostFetcher,
    "edeka": EdekaFetcher,
    "google": GoogleFetcher,
    "greenhouse": GreenhouseFetcher,
    "mercedesbenz": MercedesBenzFetcher,
    "siemens": SiemensFetcher,
    "smartrecruiters": SmartRecruitersFetcher,
    "successfactors": SuccessFactorsFetcher,
    "volkswagen": VolkswagenFetcher,
    "workday": WorkdayFetcher,
}

__all__ = ["BaseFetcher", "DeutschePostFetcher", "EdekaFetcher", "GoogleFetcher", "GreenhouseFetcher", "MercedesBenzFetcher", "SiemensFetcher", "SmartRecruitersFetcher", "SuccessFactorsFetcher", "VolkswagenFetcher", "WorkdayFetcher", "FETCHER_TYPES"]
