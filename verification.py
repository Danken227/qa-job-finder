"""Sprawdzanie, czy raport zawiera wyłącznie aktywne, bezpośrednie linki."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import requests
from bs4 import BeautifulSoup

from collectors.base import JobOffer
from config.settings import MAX_REPORT_OFFERS


REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; qa-job-finder/1.0; +https://github.com/Danken227/qa-job-finder)",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}


def verify_offers(offers: list[JobOffer]) -> list[JobOffer]:
    """Sprawdza stronę każdej oferty i zwraca maksymalnie 10 potwierdzonych."""

    with ThreadPoolExecutor(max_workers=6) as executor:
        verified = list(executor.map(_verify_offer, offers))

    return [offer for offer in verified if offer.verified][:MAX_REPORT_OFFERS]


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
        normalized_page = title_text.casefold()
        normalized_offer = offer.title.casefold()
        page_text = soup.get_text(" ", strip=True).casefold()
        closed_markers = (
            "no longer accepting applications",
            "nie przyjmujemy już aplikacji",
            "oferta wygasła",
            "offer expired",
        )
        if any(marker in page_text for marker in closed_markers):
            return replace(offer, verified=False)
        is_same_offer = bool(normalized_page) and (
            normalized_offer in normalized_page or normalized_page in normalized_offer
        )
        is_same_company = offer.company.casefold() in page_text

        return replace(offer, verified=is_same_offer and is_same_company)
    except requests.RequestException:
        return replace(offer, verified=False)
