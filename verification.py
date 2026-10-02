"""Sprawdzanie, czy raport zawiera wyłącznie aktywne, bezpośrednie linki."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace

import requests
from bs4 import BeautifulSoup

from collectors.base import JobOffer
from collectors.careers import DESCRIPTION_LIMIT, main_text
from collectors.parsing import json_ld_title, normalize_title, parse_json_ld_jobs


REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; qa-job-finder/1.0; +https://github.com/Danken227/qa-job-finder)",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}
# Strony karier firm częściej niż portale blokują nietypowy User-Agent.
CAREER_REQUEST_HEADERS = {
    **REQUEST_HEADERS,
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/138.0.0.0 Safari/537.36"
    ),
}
# Źródła z bezpośrednimi stronami pracodawców (a nie portali z ogłoszeniami).
DIRECT_SOURCES = ("Kariera:", "Strona kariery", "Budżetówka")
CLOSED_MARKERS = (
    "no longer accepting applications",
    "nie przyjmujemy już aplikacji",
    "oferta wygasła",
    "offer expired",
    "this job is no longer available",
    "this position has been filled",
    "rekrutacja została zakończona",
    "ogłoszenie wygasło",
    "job not found",
    "nabór został zakończony",
    "ogłoszenie nieaktualne",
)

_TITLE_STOP_WORDS = frozenset(
    {
        "and",
        "or",
        "the",
        "a",
        "an",
        "i",
        "w",
        "z",
        "na",
        "do",
        "dla",
        "m",
        "k",
        "f",
        "mid",
        "senior",
        "junior",
        "specialist",
        "engineer",
        "tester",
    }
)


@dataclass(slots=True)
class VerificationResult:
    offers: list[JobOffer]
    passed: int
    rejected: int


def verify_offers(offers: list[JobOffer]) -> VerificationResult:
    """Sprawdza stronę każdej oferty; przy okazji uzupełnia pełny opis oferty.

    Limit liczby ofert w raporcie nakłada dopiero pipeline - po analizie opisu
    (języki obce, automatyzacja), żeby odrzucone oferty nie zajmowały miejsc.
    """

    with ThreadPoolExecutor(max_workers=6) as executor:
        checked = list(executor.map(_verify_offer, offers))

    passed_offers = [offer for offer in checked if offer.verified]
    return VerificationResult(
        offers=passed_offers,
        passed=len(passed_offers),
        rejected=len(checked) - len(passed_offers),
    )


def page_description(html: str) -> str:
    """Opis oferty ze strony: JSON-LD, a gdy jest skąpy - treść strony bez menu i stopki."""

    description = ""
    for posting in parse_json_ld_jobs(html):
        text = BeautifulSoup(str(posting.get("description", "")), "lxml").get_text(" ", strip=True)
        if len(text) > len(description):
            description = text
    if len(description.split()) < 80:
        text = main_text(BeautifulSoup(html, "lxml"))
        if len(text) > len(description):
            description = text
    return " ".join(description.split())[:DESCRIPTION_LIMIT]


def _with_description(offer: JobOffer, html: str, verified: bool) -> JobOffer:
    description = page_description(html)
    if len(description) <= len(offer.description):
        description = offer.description
    return replace(offer, verified=verified, description=description)


def _titles_match(offer_title: str, page_title: str) -> bool:
    normalized_offer = normalize_title(offer_title)
    normalized_page = normalize_title(page_title)
    if not normalized_page:
        return False
    if normalized_offer in normalized_page or normalized_page in normalized_offer:
        return True

    offer_tokens = {
        token
        for token in normalized_offer.split()
        if len(token) > 2 and token not in _TITLE_STOP_WORDS
    }
    page_tokens = {
        token
        for token in normalized_page.split()
        if len(token) > 2 and token not in _TITLE_STOP_WORDS
    }
    if not offer_tokens or not page_tokens:
        return False

    overlap = len(offer_tokens & page_tokens)
    min_tokens = min(len(offer_tokens), len(page_tokens))
    return overlap / min_tokens >= 0.5


def _verify_offer(offer: JobOffer) -> JobOffer:
    is_company_career = offer.source.startswith(DIRECT_SOURCES)
    try:
        response = requests.get(
            offer.url,
            headers=CAREER_REQUEST_HEADERS if is_company_career else REQUEST_HEADERS,
            timeout=20,
            allow_redirects=True,
        )
        if offer.api_confirmed and response.status_code in (401, 403, 429):
            # Oferta jest aktywna według API ATS; strona tylko blokuje skrypty.
            return replace(offer, verified=True)
        if response.status_code != 200:
            return replace(offer, verified=False)

        known_offer_path = (
            "/job-offer/" in response.url
            or offer.source == "LinkedIn" and "/jobs/view/" in response.url
            or offer.source == "No Fluff Jobs" and "/pl/job/" in response.url
            or offer.source == "RocketJobs" and "/oferta-pracy/" in response.url
            or offer.source == "Pracuj.pl" and ",oferta," in response.url
        )
        if not is_company_career and not known_offer_path:
            return replace(offer, verified=False)

        soup = BeautifulSoup(response.text, "lxml")
        page_text = soup.get_text(" ", strip=True).casefold()
        if any(marker in page_text for marker in CLOSED_MARKERS):
            return replace(offer, verified=False)

        if offer.api_confirmed:
            # Strony ofert w ATS (np. Workday) renderują treść JavaScriptem,
            # więc w HTML nie ma tytułu. Aktywność potwierdziło już API.
            return _with_description(offer, response.text, True)

        candidates = [json_ld_title(posting) for posting in parse_json_ld_jobs(response.text)]
        page_title = soup.find("h1")
        if page_title:
            candidates.append(page_title.get_text(" ", strip=True))
        og_title = soup.select_one('meta[property="og:title"]')
        if og_title:
            candidates.append(og_title.get("content", ""))
        if soup.title:
            candidates.append(soup.title.get_text(" ", strip=True))

        matched = any(_titles_match(offer.title, candidate) for candidate in candidates if candidate)
        return _with_description(offer, response.text, matched)
    except requests.RequestException:
        return replace(offer, verified=False)
