"""Collector publicznych wyników wyszukiwania LinkedIn Jobs.

Korzysta wyłącznie z publicznego endpointu wyników dla niezalogowanych
użytkowników. Nie wymaga konta ani nie omija ograniczeń dostępu.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import requests
from bs4 import BeautifulSoup

from .base import BaseCollector, JobOffer
from .parsing import direct_url, extract_salary, extract_skills, normalize_contracts, normalize_work_mode


SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
SEARCHES = (
    ("manual qa", "Wrocław, Poland", False),
    ("qa engineer", "Wrocław, Poland", False),
    ("software tester", "Wrocław, Poland", False),
    ("manual qa", "Poland", True),
    ("qa engineer", "Poland", True),
    ("software tester", "Poland", True),
)
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; qa-job-finder/1.0; +https://github.com/Danken227/qa-job-finder)",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}


class LinkedInCollector(BaseCollector):
    """Pobiera pierwszą stronę konkretnych, publicznych wyszukiwań QA."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()

    def collect(self) -> list[JobOffer]:
        offers: dict[str, JobOffer] = {}
        for keywords, location, remote_only in SEARCHES:
            params = {"keywords": keywords, "location": location, "start": 0}
            if remote_only:
                params["f_WT"] = "2"
            response = self.session.get(SEARCH_URL, params=params, headers=REQUEST_HEADERS, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")

            for card in soup.select("div.job-search-card"):
                offer = self._parse_card(card, remote_only)
                if offer:
                    offers[offer.url] = offer

        if not offers:
            raise RuntimeError("LinkedIn returned no public job cards; the endpoint may have changed.")

        # Wynik wyszukiwania zawiera tylko podstawowe pola. Szczegóły są
        # potrzebne, by rozpoznać SQL/API/Playwright oraz wykluczyć zamknięte role.
        with ThreadPoolExecutor(max_workers=4) as executor:
            return list(executor.map(self._enrich_offer, offers.values()))

    @staticmethod
    def _parse_card(card, remote_only: bool) -> JobOffer | None:
        link = card.select_one("a.base-card__full-link[href*='/jobs/view/']")
        title_element = card.select_one("h3.base-search-card__title")
        company_element = card.select_one("h4.base-search-card__subtitle")
        location_element = card.select_one("span.job-search-card__location")
        if not all((link, title_element, company_element, location_element)):
            return None

        company_link = company_element.select_one("a")
        return JobOffer(
            company=(company_link or company_element).get_text(" ", strip=True),
            title=title_element.get_text(" ", strip=True),
            location=location_element.get_text(" ", strip=True),
            work_mode="Remote" if remote_only else "Nie podano",
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

        page_text = " ".join(BeautifulSoup(response.text, "lxml").stripped_strings)
        if any(marker in page_text.casefold() for marker in ("no longer accepting applications", "nie przyjmujemy już aplikacji")):
            return replace(offer, expires_in="Zamknięta")

        work_mode = normalize_work_mode(page_text)
        return replace(
            offer,
            work_mode=work_mode if work_mode != "Nie podano" else offer.work_mode,
            contract_types=normalize_contracts(page_text),
            salary=extract_salary(page_text),
            skills=extract_skills(page_text),
        )
