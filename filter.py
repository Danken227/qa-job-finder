"""Dopasowanie ofert do ustalonego profilu QA."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from collectors.base import JobOffer
from collectors.parsing import normalize_title
from config.settings import (
    CANDIDATES_FOR_VERIFICATION,
    MIN_B2B,
    MIN_MATCH_SCORE,
    MIN_UOP,
    PREFERRED_B2B,
)
from config.profile import PROFILE


TITLE_KEYWORDS = PROFILE.title_keywords
AUTOMATION_FIRST_TITLES = PROFILE.automation_first_titles
SENIORITY_OR_LEADERSHIP_TITLES = PROFILE.excluded_seniority_titles
MATCHING_SKILLS = PROFILE.matching_skills


@dataclass(frozen=True, slots=True)
class FilterResult:
    offers: list[JobOffer]
    rejected_title: int = 0
    rejected_automation: int = 0
    rejected_seniority: int = 0
    rejected_location: int = 0
    rejected_salary: int = 0
    rejected_score: int = 0


def deduplicate_offers(offers: list[JobOffer]) -> list[JobOffer]:
    """Usuwa duplikaty między portalami po firmie i znormalizowanym tytule."""

    best: dict[tuple[str, str], JobOffer] = {}
    for offer in offers:
        key = (offer.company.casefold().strip(), normalize_title(offer.title))
        existing = best.get(key)
        if existing is None or _offer_richness(offer) > _offer_richness(existing):
            best[key] = offer
    return list(best.values())


def _offer_richness(offer: JobOffer) -> tuple[bool, int, int, bool]:
    return (
        bool(offer.salary),
        len(offer.skills),
        len(offer.contract_types),
        offer.source != "LinkedIn",
    )


def filter_offers(offers: list[JobOffer]) -> list[JobOffer]:
    """Zwraca najlepsze kandydatury do późniejszej weryfikacji linków.

    Nie wymusza liczby ofert: oferty z widełkami poniżej progów odpadają,
    a oferty bez podanego wynagrodzenia zostają w puli.
    """

    return filter_offers_with_diagnostics(offers).offers


def filter_offers_with_diagnostics(offers: list[JobOffer]) -> FilterResult:
    """Filtruje oferty i zwraca liczby odrzuceń według powodu."""

    shortlisted: list[JobOffer] = []
    rejected_title = rejected_automation = rejected_seniority = 0
    rejected_location = rejected_salary = rejected_score = 0
    for offer in offers:
        if not _has_relevant_title(offer.title):
            rejected_title += 1
            continue
        if _is_automation_first(offer.title):
            rejected_automation += 1
            continue
        if _is_out_of_scope_seniority(offer.title):
            rejected_seniority += 1
            continue
        if not _is_allowed_location(offer):
            rejected_location += 1
            continue

        salary_ok, salary_assessment = _assess_salary(offer)
        if not salary_ok:
            rejected_salary += 1
            continue

        score, reasons = _score_offer(offer, salary_assessment)
        if score < MIN_MATCH_SCORE:
            rejected_score += 1
            continue
        shortlisted.append(
            replace(
                offer,
                match_score=score,
                match_reasons=tuple(reasons),
                salary_assessment=salary_assessment,
            )
        )

    result = sorted(
        shortlisted,
        key=lambda item: (item.match_score, item.work_mode.casefold() == "remote"),
        reverse=True,
    )[:CANDIDATES_FOR_VERIFICATION]
    return FilterResult(
        offers=result,
        rejected_title=rejected_title,
        rejected_automation=rejected_automation,
        rejected_seniority=rejected_seniority,
        rejected_location=rejected_location,
        rejected_salary=rejected_salary,
        rejected_score=rejected_score,
    )


def _has_relevant_title(title: str) -> bool:
    normalized = title.casefold()
    return any(keyword in normalized for keyword in TITLE_KEYWORDS)


def _is_automation_first(title: str) -> bool:
    normalized = title.casefold()
    return any(keyword in normalized for keyword in AUTOMATION_FIRST_TITLES) and "manual" not in normalized


def _is_out_of_scope_seniority(title: str) -> bool:
    normalized = title.casefold()
    return any(keyword in normalized for keyword in SENIORITY_OR_LEADERSHIP_TITLES)


def _is_allowed_location(offer: JobOffer) -> bool:
    if PROFILE.allow_remote and offer.work_mode.casefold() == "remote":
        return True
    if PROFILE.preferred_city.casefold() in offer.location.casefold():
        return True
    return PROFILE.allow_hybrid_outside_preferred_city and offer.work_mode.casefold() == "hybrid"


def _assess_salary(offer: JobOffer) -> tuple[bool, str]:
    if not offer.salary:
        return PROFILE.include_offers_without_salary, "Brak widełek — pokaż ofertę"

    if "PLN" not in offer.salary.upper():
        return True, "Widełki w walucie obcej — do indywidualnej oceny"

    values = _numbers_from_salary(offer.salary)
    if not values:
        return True, "Nie udało się odczytać widełek — pokaż ofertę"

    maximum = max(values)
    contracts = {contract.casefold() for contract in offer.contract_types}
    has_b2b = "b2b" in contracts
    has_uop = "permanent" in contracts
    per_hour = "/h" in offer.salary.casefold() or "/hour" in offer.salary.casefold()

    if has_b2b:
        hourly_rate = maximum if per_hour else maximum / 160
        if hourly_rate >= PREFERRED_B2B:
            return True, f"B2B ok (ok. {hourly_rate:.0f} zł/h)"
        if hourly_rate >= MIN_B2B:
            return True, f"B2B do rozważenia (ok. {hourly_rate:.0f} zł/h)"
        if not has_uop:
            return False, f"B2B poniżej {MIN_B2B} zł/h"

    if has_uop:
        if maximum >= MIN_UOP:
            return True, f"UoP ok (do {maximum:,.0f} zł brutto)".replace(",", " ")
        return False, f"UoP poniżej {MIN_UOP:,.0f} zł brutto".replace(",", " ")

    return True, "Nieznany typ umowy — pokaż ofertę"


def _numbers_from_salary(salary: str) -> list[float]:
    numbers = []
    for raw_value in re.findall(r"\d[\d\s\u00a0,.]*", salary):
        normalized = raw_value.replace("\u00a0", " ").replace(" ", "").replace(",", ".")
        try:
            numbers.append(float(normalized))
        except ValueError:
            continue
    return numbers


def _score_offer(offer: JobOffer, salary_assessment: str) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    title = offer.title.casefold()

    if "manual" in title:
        score += 6
        reasons.append("testy manualne")
    if "tester" in title or "qa" in title:
        score += 3

    skills = {skill.casefold() for skill in offer.skills}
    for skill, points in MATCHING_SKILLS:
        if skill.casefold() in skills:
            score += points
            reasons.append(skill)

    if offer.work_mode.casefold() == "remote":
        score += 3
        reasons.append("100% remote")
    elif PROFILE.preferred_city.casefold() in offer.location.casefold():
        score += 2
        reasons.append(PROFILE.preferred_city)

    if salary_assessment.startswith("B2B ok") or salary_assessment.startswith("UoP ok"):
        score += 2
    if "Brak widełek" in salary_assessment:
        score += 1

    unique_reasons = list(dict.fromkeys(reasons))
    return score, unique_reasons[:6]
