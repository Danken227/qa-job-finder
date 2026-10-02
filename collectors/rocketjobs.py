"""Collector publicznych ofert z RocketJobs.

RocketJobs nie ma już kategorii w adresie, a lista miasta zawiera wszystkie
branże (np. farmację), więc oferty QA ginęłyby w pierwszych 50 kartach.
Szukamy więc po frazach z profilu (``?keyword=QA``) - osobno dla miasta
i pracy zdalnej. Klasy CSS na stronie są generowane (MUI), dlatego pola karty
rozpoznajemy po ikonach: budynek = firma, pinezka = lokalizacja.
"""

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
BASE_URL = "https://rocketjobs.pl/oferty-pracy"


class RocketJobsCollector(BaseCollector):
    """Pobiera karty ofert z wyszukiwania RocketJobs dla miasta i pracy zdalnej."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()

    def collect(self) -> list[JobOffer]:
        locations = [PROFILE.preferred_city_slug]
        if PROFILE.allow_remote:
            locations.append("praca-zdalna")

        offers: dict[str, JobOffer] = {}
        for location in locations:
            for keyword in PROFILE.career_search_keywords:
                response = self.session.get(
                    f"{BASE_URL}/{location}",
                    params={"keyword": keyword},
                    headers=REQUEST_HEADERS,
                    timeout=30,
                )
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "lxml")
                for link in soup.select("a.offer-card[href*='/oferta-pracy/']"):
                    offer = self._parse_card(link)
                    if offer:
                        offers.setdefault(offer.url, offer)

        if not offers:
            raise RuntimeError("RocketJobs returned no offer cards; the page structure may have changed.")
        return list(offers.values())

    @staticmethod
    def _parse_card(link) -> JobOffer | None:
        # Link to przezroczysta warstwa nad kartą - treść jest w rodzeństwie.
        card = link.parent
        if card is None:
            return None

        heading = card.find(["h2", "h3", "h4"])
        title = heading.get_text(" ", strip=True) if heading else ""
        if not title:
            title = re.sub(r"^Zobacz ofertę\s*", "", link.get("title", "")).strip()
        if not title:
            return None

        logo = card.select_one("object img[alt]")
        company = _field_by_icon(card, "lucide-building") or (logo.get("alt", "") if logo else "") or "Nie podano"
        location = _field_by_icon(card, "lucide-map-pin") or "Nie podano"
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


def _field_by_icon(card, icon_class: str) -> str:
    """Tekst akapitu stojącego obok ikony o danej klasie (np. pinezki)."""

    for icon in card.select(f"svg.{icon_class}"):
        container = icon.find_parent("div")
        row = container.parent if container is not None else None
        paragraph = row.find("p") if row is not None else None
        if paragraph is not None:
            text = paragraph.get_text(" ", strip=True)
            if text:
                return text
    return ""
