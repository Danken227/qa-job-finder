"""Dopasowanie ofert do ustalonego profilu QA."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from analysis import required_foreign_languages
from collectors.base import JobOffer
from collectors.parsing import contains_keyword, fold_text, normalize_title
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
    rejected_language: int = 0
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


def _offer_richness(offer: JobOffer) -> tuple[bool, bool, int, int, bool]:
    # Ta sama oferta bywa publikowana osobno dla kilku miast - zostawiamy
    # wersję, która przejdzie filtr lokalizacji (np. Wrocław zamiast Szczecina).
    return (
        _is_allowed_location(offer),
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


def filter_offers_with_diagnostics(
    offers: list[JobOffer],
    title_keywords: tuple[str, ...] = (),
    seniority_exclude: tuple[str, ...] = (),
) -> FilterResult:
    """Filtruje oferty i zwraca liczby odrzuceń według powodu.

    ``title_keywords`` i ``seniority_exclude`` rozszerzają reguły z profilu,
    np. o urzędowe tytuły w budżetówce ("Specjalista ds. testów").
    """

    extra_title_keywords = title_keywords
    title_keywords = (*TITLE_KEYWORDS, *title_keywords)
    seniority_exclude = (*SENIORITY_OR_LEADERSHIP_TITLES, *seniority_exclude)
    shortlisted: list[JobOffer] = []
    rejected_title = rejected_language = rejected_automation = rejected_seniority = 0
    rejected_location = rejected_salary = rejected_score = 0
    for offer in offers:
        if not contains_keyword(offer.title, title_keywords):
            rejected_title += 1
            continue
        # Wstępnie po tytule i opisie z listy; pełny opis sprawdza pipeline po weryfikacji.
        if required_foreign_languages(offer.title, offer.description):
            rejected_language += 1
            continue
        if _is_automation_first(offer.title):
            rejected_automation += 1
            continue
        if contains_keyword(offer.title, seniority_exclude):
            rejected_seniority += 1
            continue
        if not _is_allowed_location(offer):
            rejected_location += 1
            continue

        salary_ok, salary_assessment = _assess_salary(offer)
        if not salary_ok:
            rejected_salary += 1
            continue

        score, reasons = _score_offer(offer, salary_assessment, extra_title_keywords)
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
        rejected_language=rejected_language,
        rejected_automation=rejected_automation,
        rejected_seniority=rejected_seniority,
        rejected_location=rejected_location,
        rejected_salary=rejected_salary,
        rejected_score=rejected_score,
    )


def _is_automation_first(title: str) -> bool:
    return contains_keyword(title, AUTOMATION_FIRST_TITLES) and not contains_keyword(title, ("manual",))


def is_preferred_city(location: str) -> bool:
    """Porównuje miasto bez polskich znaków i z aliasami (Wrocław == Wroclaw)."""
    folded_location = fold_text(location)
    return any(fold_text(city) in folded_location for city in PROFILE.city_names if city)


def _is_allowed_location(offer: JobOffer) -> bool:
    if PROFILE.allow_remote and offer.work_mode.casefold() == "remote":
        return True
    if is_preferred_city(offer.location):
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


def _score_offer(
    offer: JobOffer,
    salary_assessment: str,
    title_keywords: tuple[str, ...] = (),
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    title = offer.title.casefold()

    if contains_keyword(title, ("manual",)):
        score += 6
        reasons.append("testy manualne")
    if contains_keyword(title, ("tester", "qa", *title_keywords)):
        score += 3

    skills = {skill.casefold() for skill in offer.skills}
    for skill, points in MATCHING_SKILLS:
        if skill.casefold() in skills:
            score += points
            reasons.append(skill)

    if offer.work_mode.casefold() == "remote":
        score += 3
        reasons.append("100% remote")
    elif is_preferred_city(offer.location):
        score += 2
        reasons.append(PROFILE.preferred_city)

    if salary_assessment.startswith("B2B ok") or salary_assessment.startswith("UoP ok"):
        score += 2
    if "Brak widełek" in salary_assessment:
        score += 1

    unique_reasons = list(dict.fromkeys(reasons))
    return score, unique_reasons[:6]
