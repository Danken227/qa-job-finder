"""Collector publicznych ofert QA z No Fluff Jobs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .base import BaseCollector, JobOffer
from .parsing import extract_salary, extract_skills, normalize_contracts, normalize_work_mode


LISTING_URLS = (
    "https://nofluffjobs.com/pl/Wroc%C5%82aw/QA",
    "https://nofluffjobs.com/pl/remote/QA",
)
BASE_URL = "https://nofluffjobs.com"
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; qa-job-finder/1.0; +https://github.com/Danken227/qa-job-finder)",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}


class NoFluffJobsCollector(BaseCollector):
    """Pobiera oferty lokalne i zdalne z publicznych list No Fluff Jobs."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()

    def collect(self) -> list[JobOffer]:
        offers: dict[str, JobOffer] = {}
        for listing_url in LISTING_URLS:
            response = self.session.get(listing_url, headers=REQUEST_HEADERS, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")

            for card in soup.select("a.posting-list-item[href*='/pl/job/']"):
                offer = self._parse_card(card)
                if offer:
                    offers[offer.url] = offer

        if not offers:
            raise RuntimeError("No Fluff Jobs returned no offer cards; the page structure may have changed.")

        # Szczegóły doprecyzowują typ umowy i widełki, których karta listy
        # nie podaje konsekwentnie dla każdego ogłoszenia.
        with ThreadPoolExecutor(max_workers=6) as executor:
            return list(executor.map(self._enrich_offer, offers.values()))

    @staticmethod
    def _parse_card(card) -> JobOffer | None:
        title_element = card.select_one("h3")
        company_element = card.select_one("h4.company-name")
        if title_element is None or company_element is None:
            return None

        card_text = " ".join(card.stripped_strings)
        title = title_element.get_text(" ", strip=True).replace("NOWA", "").strip()
        company = company_element.get_text(" ", strip=True)
        salary_element = card.select_one("[data-cy='salary ranges on the job offer listing']")
        salary = extract_salary(salary_element.get_text(" ", strip=True) if salary_element else "")
        location = "Wrocław" if "wrocław" in card_text.casefold() else "Remote"

        return JobOffer(
            company=company,
            title=title,
            location=location,
            work_mode=normalize_work_mode(card_text),
            contract_types=normalize_contracts(card_text),
            salary=salary,
            url=urljoin(BASE_URL, card["href"]),
            source="No Fluff Jobs",
            skills=extract_skills(card_text),
            expires_in="Nowa" if "nowa" in card_text.casefold() else "",
        )

    def _enrich_offer(self, offer: JobOffer) -> JobOffer:
        try:
            response = requests.get(offer.url, headers=REQUEST_HEADERS, timeout=20)
            response.raise_for_status()
        except requests.RequestException:
            return offer

        page_text = " ".join(BeautifulSoup(response.text, "lxml").stripped_strings)
        work_mode = normalize_work_mode(page_text)
        contracts = normalize_contracts(page_text)
        salary = extract_salary(page_text) or offer.salary
        skills = tuple(dict.fromkeys((*offer.skills, *extract_skills(page_text))))
        return replace(
            offer,
            work_mode=work_mode if work_mode != "Nie podano" else offer.work_mode,
            contract_types=contracts or offer.contract_types,
            salary=salary,
            skills=skills,
        )
