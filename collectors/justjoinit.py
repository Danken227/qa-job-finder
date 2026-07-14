"""Collector aktywnych ofert z kategorii Testing w JustJoinIT.

JustJoinIT renderuje listę ofert po stronie serwera. Dzięki temu pobieramy
publiczną stronę listy zamiast opierać się na nieudokumentowanym API.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .base import BaseCollector, JobOffer


LISTING_URL = "https://justjoin.it/job-offers/all-locations/testing"
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; qa-job-finder/1.0; +https://github.com/Danken227/qa-job-finder)",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}

WORK_MODES = ("Remote", "Hybrid", "Office", "Mobile")
CONTRACT_TYPES = ("B2B", "Permanent", "Mandate contract", "Contract", "Any")
KNOWN_SKILLS = (
    "SQL",
    "Postman",
    "REST API",
    "REST",
    "Jira",
    "Confluence",
    "Swagger",
    "OpenAPI",
    "ERP",
    "WMS",
    "Playwright",
    "API Testing",
    "Manual Testing",
    "TestRail",
    "Xray",
    "Zephyr",
    "SoapUI",
)
SALARY_PATTERN = re.compile(
    r"(?:\d[\d\s\u00a0,.]*\s*-\s*)?\d[\d\s\u00a0,.]*\s*"
    r"(?:PLN|EUR|USD|CHF)\s*/\s*(?:h|hour|day|month)",
    re.IGNORECASE,
)


class JustJoinItCollector(BaseCollector):
    """Pobiera aktywne karty ofert z publicznej listy JustJoinIT."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()

    def collect(self) -> list[JobOffer]:
        response = self.session.get(
            LISTING_URL,
            headers=REQUEST_HEADERS,
            timeout=30,
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")
        offers: list[JobOffer] = []
        seen_urls: set[str] = set()

        for link in soup.select("a.offer-card[href*='/job-offer/']"):
            url = urljoin(LISTING_URL, link["href"])
            if url in seen_urls:
                continue
            seen_urls.add(url)

            card = link.parent
            offer = self._parse_card(card, url)
            if offer is not None:
                offers.append(offer)

        if not offers:
            raise RuntimeError("JustJoinIT returned no offer cards; the page structure may have changed.")

        return offers

    @staticmethod
    def _parse_card(card, url: str) -> JobOffer | None:
        title_link = card.select_one("a.offer_list_offer_title_link")
        if title_link is None:
            return None

        title = title_link.get_text(" ", strip=True)
        if not title:
            return None

        logo = card.select_one("object img[alt]")
        company = logo.get("alt", "") if logo else ""

        paragraphs = [item.get_text(" ", strip=True) for item in card.find_all("p")]
        if not company and paragraphs:
            company = paragraphs[0]

        location = ""
        for paragraph in paragraphs:
            if paragraph and paragraph != company and paragraph not in WORK_MODES:
                location = paragraph
                break

        card_text = " ".join(card.stripped_strings)
        work_mode = next((mode for mode in WORK_MODES if re.search(rf"\b{mode}\b", card_text, re.I)), "")
        contracts = tuple(
            contract
            for contract in CONTRACT_TYPES
            if re.search(rf"\b{re.escape(contract)}\b", card_text, re.I)
        )
        skills = tuple(
            skill
            for skill in KNOWN_SKILLS
            if re.search(rf"\b{re.escape(skill)}\b", card_text, re.I)
        )

        salary_match = SALARY_PATTERN.search(card_text)
        salary = salary_match.group(0).replace("\u00a0", " ") if salary_match else ""
        expires_match = re.search(r"(?:New|Expires tomorrow|\d+d left)", card_text, re.I)
        expires_in = expires_match.group(0) if expires_match else ""

        return JobOffer(
            company=company or "Nie podano",
            title=title,
            location=location or "Nie podano",
            work_mode=work_mode or "Nie podano",
            contract_types=contracts,
            salary=salary,
            url=url,
            source="JustJoinIT",
            skills=skills,
            expires_in=expires_in,
        )
