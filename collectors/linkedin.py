"""Collector publicznych wyników wyszukiwania LinkedIn Jobs.

Korzysta wyłącznie z publicznego endpointu wyników dla niezalogowanych
użytkowników. Nie wymaga konta ani nie omija ograniczeń dostępu.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import requests
from bs4 import BeautifulSoup

from config.profile import PROFILE
from .base import BaseCollector, JobOffer
from .parsing import (
    contains_keyword,
    direct_url,
    extract_cities,
    extract_salary,
    extract_skills,
    normalize_contracts,
    normalize_work_mode,
)


SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
SEARCH_KEYWORDS = ("manual qa", "qa engineer", "quality assurance", "software tester", "tester")
# Niezalogowani dostają 10 ofert na stronę - pierwsza strona to za mało
# (oferta bywała dopiero na 3. stronie). Najnowsze z ostatnich 30 dni.
PAGE_SIZE = 10
MAX_PAGES = 5
POSTED_WITHIN = "r2592000"  # 30 dni w sekundach (14 dni gubiło aktywne, starsze oferty)
PAGE_DELAY_SECONDS = 1.5
RATE_LIMIT_WAIT_SECONDS = 30
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; qa-job-finder/1.0; +https://github.com/Danken227/qa-job-finder)",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}


class LinkedInCollector(BaseCollector):
    """Pobiera pierwszą stronę konkretnych, publicznych wyszukiwań QA."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        # Ostrzeżenia trafiają do sekcji "problemy ze źródłami" w mailu.
        self.warnings: list[str] = []

    def collect(self) -> list[JobOffer]:
        offers: dict[str, JobOffer] = {}
        searches = [(keywords, f"{PROFILE.preferred_city}, Poland", False) for keywords in SEARCH_KEYWORDS]
        if PROFILE.allow_remote:
            searches.extend((keywords, "Poland", True) for keywords in SEARCH_KEYWORDS)

        for keywords, location, remote_only in searches:
            if self.blocked:
                break  # LinkedIn blokuje mimo odczekania - nie czekamy przy każdym wyszukiwaniu
            for page in range(MAX_PAGES):
                params = {"keywords": keywords, "location": location, "start": page * PAGE_SIZE,
                          "sortBy": "DD", "f_TPR": POSTED_WITHIN}
                if remote_only:
                    params["f_WT"] = "2"
                response = self._get_search_page(params)
                if response is None:
                    break  # limit zapytań mimo odczekania - zostajemy przy tym, co już mamy
                response.raise_for_status()
                cards = BeautifulSoup(response.text, "lxml").select("div.job-search-card")
                for card in cards:
                    offer = self._parse_card(card, remote_only)
                    if offer:
                        offers[offer.url] = offer
                if len(cards) < PAGE_SIZE:
                    break
                time.sleep(PAGE_DELAY_SECONDS)

        if not offers:
            raise RuntimeError("LinkedIn returned no public job cards; the endpoint may have changed.")
        if self.rate_limited:
            self.warnings.append("LinkedIn ograniczył liczbę zapytań - wyniki z LinkedIn mogą być niepełne")

        # Szczegóły (opis: tryb pracy, widełki, umiejętności) tylko dla ofert
        # z pasującym tytułem - setki zapytań o resztę groziłyby blokadą.
        keywords = (*PROFILE.title_keywords, *PROFILE.public_title_keywords)
        relevant = [offer for offer in offers.values() if contains_keyword(offer.title, keywords)]
        with ThreadPoolExecutor(max_workers=4) as executor:
            return list(executor.map(self._enrich_offer, relevant))

    rate_limited = False
    blocked = False

    def _get_search_page(self, params: dict) -> requests.Response | None:
        """Strona wyników; po 429 jedno odczekanie i ponowna próba."""

        for attempt in range(2):
            try:
                response = self.session.get(SEARCH_URL, params=params, headers=REQUEST_HEADERS, timeout=30)
            except requests.ConnectionError:
                # Drugi sposób ograniczania przez LinkedIn: zerwane połączenie.
                response = None
            if response is not None and response.status_code != 429:
                return response
            self.rate_limited = True
            if attempt == 0:
                retry_after = response.headers.get("Retry-After") if response is not None else None
                wait = int(retry_after) if str(retry_after or "").isdigit() else RATE_LIMIT_WAIT_SECONDS
                time.sleep(min(wait, 60))
        self.blocked = True
        return None

    @staticmethod
    def _parse_card(card, remote_only: bool) -> JobOffer | None:
        link = card.select_one("a.base-card__full-link[href*='/jobs/view/']")
        title_element = card.select_one("h3.base-search-card__title")
        company_element = card.select_one("h4.base-search-card__subtitle")
        location_element = card.select_one("span.job-search-card__location")
        if not all((link, title_element, company_element, location_element)):
            return None

        company_link = company_element.select_one("a")
        location = location_element.get_text(" ", strip=True)
        return JobOffer(
            company=(company_link or company_element).get_text(" ", strip=True),
            title=title_element.get_text(" ", strip=True),
            location=location,
            # Filtr "zdalnie" LinkedIn (f_WT=2) zwraca też oferty hybrydowe
            # i stacjonarne w konkretnym mieście (np. "Warszawa"). Ufamy mu tylko
            # przy lokalizacji "cały kraj"; w pozostałych tryb ustala opis oferty.
            work_mode="Remote" if remote_only and not extract_cities(location) else "Nie podano",
            contract_types=(),
            salary="",
            url=direct_url(link["href"]),
            source="LinkedIn",
            expires_in=(card.select_one("time").get("datetime", "") if card.select_one("time") else ""),
        )

    def _enrich_offer(self, offer: JobOffer) -> JobOffer:
        try:
            response = requests.get(offer.url, headers=REQUEST_HEADERS, timeout=20)
            response.raise_for_status()
        except requests.RequestException:
            return offer

        soup = BeautifulSoup(response.text, "lxml")
        page_text = " ".join(soup.stripped_strings)
        if any(marker in page_text.casefold() for marker in ("no longer accepting applications", "nie przyjmujemy już aplikacji")):
            return replace(offer, expires_in="Zamknięta")

        # Wszystko tylko z opisu oferty: reszta strony to menu i "podobne oferty"
        # z cudzymi trybami pracy i kwotami (stąd brały się fałszywe "Remote"
        # i "80 000 PLN").
        box = soup.select_one(".show-more-less-html__markup") or soup.select_one(".description__text")
        description = " ".join(box.get_text(" ").split()) if box else ""
        work_mode = normalize_work_mode(f"{offer.title} {description}")
        return replace(
            offer,
            description=description,
            work_mode=work_mode if work_mode != "Nie podano" else offer.work_mode,
            contract_types=normalize_contracts(description),
            salary=extract_salary(description),
            skills=extract_skills(description),
        )
