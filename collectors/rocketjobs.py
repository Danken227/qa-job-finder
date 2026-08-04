"""Collector publicznych ofert z RocketJobs."""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

from config.profile import PROFILE
from .base import BaseCollector, JobOffer
from .parsing import extract_salary, extract_skills, normalize_contracts, normalize_work_mode


REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; qa-job-finder/1.0; +https://github.com/Danken227/qa-job-finder)",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}


class RocketJobsCollector(BaseCollector):
    """Pobiera publiczne karty z list Wrocław i praca zdalna."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()

    def collect(self) -> list[JobOffer]:
        offers: dict[str, JobOffer] = {}
        listing_urls = [f"https://rocketjobs.pl/oferty-pracy/{PROFILE.preferred_city_slug}"]
        if PROFILE.allow_remote:
            listing_urls.append("https://rocketjobs.pl/oferty-pracy/praca-zdalna")

        for listing_url in listing_urls:
            response = self.session.get(listing_url, headers=REQUEST_HEADERS, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")
            for link in soup.select("a.offer-card[href*='/oferta-pracy/']"):
                offer = self._parse_card(link)
                if offer:
                    offers[offer.url] = offer

        if not offers:
            raise RuntimeError("RocketJobs returned no offer cards; the page structure may have changed.")
        return list(offers.values())

    @staticmethod
    def _parse_card(link) -> JobOffer | None:
        card = link.find_parent("li")
        if card is None:
            return None

        title_element = card.select_one("a.offer_list_offer_title_link")
        if title_element is None:
            return None
        title = title_element.get_text(" ", strip=True)
        if not title:
            return None

        logo = card.select_one("object img[alt]")
        company = logo.get("alt", "") if logo else "Nie podano"
        paragraphs = [item.get_text(" ", strip=True) for item in card.select("p")]
        location = next(
            (
                paragraph
                for paragraph in paragraphs
                if paragraph and paragraph != company and not re.search(r"praca|zdalnie|hybrydowo|stacjonarnie", paragraph, re.I)
            ),
            "Nie podano",
        )
        card_text = " ".join(card.stripped_strings)

        return JobOffer(
            company=company,
            title=title,
            location=location,
            work_mode=normalize_work_mode(card_text),
            contract_types=normalize_contracts(card_text),
            salary=extract_salary(card_text),
            url=link["href"],
            source="RocketJobs",
            skills=extract_skills(card_text),
            expires_in="Nowa" if "nowa" in card_text.casefold() else "",
        )
