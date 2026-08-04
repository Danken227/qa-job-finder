"""Wczytywanie prywatnego profilu wyszukiwania ofert.

Prawdziwy plik ``search_profile.json`` jest lokalny i ignorowany przez Git.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


PROFILE_PATH = Path(__file__).with_name("search_profile.json")


@dataclass(frozen=True, slots=True)
class SearchProfile:
    preferred_city: str
    preferred_city_slug: str
    allow_remote: bool
    allow_hybrid_outside_preferred_city: bool
    min_uop_gross_pln: int
    min_b2b_hourly_pln: int
    preferred_b2b_hourly_pln: int
    include_offers_without_salary: bool
    title_keywords: tuple[str, ...]
    automation_first_titles: tuple[str, ...]
    excluded_seniority_titles: tuple[str, ...]
    matching_skills: tuple[tuple[str, int], ...]
    min_match_score: int
    candidates_for_verification: int
    max_report_offers: int


def load_profile(path: Path = PROFILE_PATH) -> SearchProfile:
    if not path.exists():
        raise RuntimeError(
            "Brakuje config/search_profile.json. Skopiuj "
            "config/search_profile.example.json jako search_profile.json i uzupełnij go lokalnie."
        )

    raw = json.loads(path.read_text(encoding="utf-8"))
    location = raw["location"]
    salary = raw["salary"]
    job_titles = raw["job_titles"]
    filtering = raw["filtering"]
    skills = tuple((item["name"], int(item["points"])) for item in raw["matching_skills"])

    return SearchProfile(
        preferred_city=str(location["preferred_city"]),
        preferred_city_slug=str(location["preferred_city_slug"]),
        allow_remote=bool(location["allow_remote"]),
        allow_hybrid_outside_preferred_city=bool(location["allow_hybrid_outside_preferred_city"]),
        min_uop_gross_pln=int(salary["min_uop_gross_pln"]),
        min_b2b_hourly_pln=int(salary["min_b2b_hourly_pln"]),
        preferred_b2b_hourly_pln=int(salary["preferred_b2b_hourly_pln"]),
        include_offers_without_salary=bool(salary["include_offers_without_salary"]),
        title_keywords=tuple(str(item) for item in job_titles["include"]),
        automation_first_titles=tuple(str(item) for item in job_titles["automation_first_exclude"]),
        excluded_seniority_titles=tuple(str(item) for item in job_titles["seniority_exclude"]),
        matching_skills=skills,
        min_match_score=int(filtering["min_match_score"]),
        candidates_for_verification=int(filtering["candidates_for_verification"]),
        max_report_offers=int(filtering["max_report_offers"]),
    )


PROFILE = load_profile()
