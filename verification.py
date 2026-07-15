"""Sprawdzanie, czy raport zawiera wyłącznie aktywne, bezpośrednie linki."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace

import requests
from bs4 import BeautifulSoup

from collectors.base import JobOffer
from collectors.parsing import normalize_title
from config.settings import MAX_REPORT_OFFERS


REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; qa-job-finder/1.0; +https://github.com/Danken227/qa-job-finder)",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}

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
    trimmed: int


def verify_offers(offers: list[JobOffer]) -> VerificationResult:
    """Sprawdza stronę każdej oferty i zwraca potwierdzone (do MAX_REPORT_OFFERS)."""

    with ThreadPoolExecutor(max_workers=6) as executor:
        checked = list(executor.map(_verify_offer, offers))

    passed_offers = [offer for offer in checked if offer.verified]
    trimmed = max(0, len(passed_offers) - MAX_REPORT_OFFERS)
    return VerificationResult(
        offers=passed_offers[:MAX_REPORT_OFFERS],
        passed=len(passed_offers),
        rejected=len(checked) - len(passed_offers),
        trimmed=trimmed,
    )


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
    try:
        response = requests.get(
            offer.url,
            headers=REQUEST_HEADERS,
            timeout=20,
            allow_redirects=True,
        )
        if response.status_code != 200 or "/job-offer/" not in response.url:
            if offer.source == "LinkedIn" and "/jobs/view/" in response.url:
                pass
            elif offer.source == "No Fluff Jobs" and "/pl/job/" in response.url:
                pass
            elif offer.source == "RocketJobs" and "/oferta-pracy/" in response.url:
                pass
            else:
                return replace(offer, verified=False)

        soup = BeautifulSoup(response.text, "lxml")
        page_title = soup.find("h1")
        title_text = page_title.get_text(" ", strip=True) if page_title else ""
        page_text = soup.get_text(" ", strip=True).casefold()
        closed_markers = (
            "no longer accepting applications",
            "nie przyjmujemy już aplikacji",
            "oferta wygasła",
            "offer expired",
        )
        if any(marker in page_text for marker in closed_markers):
            return replace(offer, verified=False)

        return replace(offer, verified=_titles_match(offer.title, title_text))
    except requests.RequestException:
        return replace(offer, verified=False)
