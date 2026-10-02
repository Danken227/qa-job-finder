"""Centralne wyszukiwarki ogłoszeń sektora publicznego.

- ``NaboryKprmCollector`` - nabory.kprm.gov.pl: wszystkie ogłoszenia służby
  cywilnej (ministerstwa, urzędy wojewódzkie, KAS, Policja - pracownicy
  cywilni, inspekcje). Wyszukiwanie jest pełnotekstowe, a tytuł na liście to
  tylko stanowisko urzędnicze ("specjalista"), więc dla każdego trafienia
  pobieramy szczegóły ("Do spraw: testowania oprogramowania", komórka) i dopiero
  na nich sprawdzamy słowa kluczowe.
- ``GovPlJobOfferCollector`` - API ogłoszeń z portalu gov.pl (ok. 300
  instytucji spoza służby cywilnej: instytuty, Lasy Państwowe, Wody Polskie...).
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config.profile import PROFILE
from filter import is_preferred_city
from .base import BaseCollector, JobOffer
from .parsing import contains_keyword, extract_salary, extract_skills, normalize_contracts, normalize_work_mode

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/138.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pl-PL,pl;q=0.9",
}
TIMEOUT = 30
NABORY_URL = "https://nabory.kprm.gov.pl/"
GOVPL_API = "https://aplikacje.gov.pl/app/bip-back/api/job-offer"
# Pełnotekstowe "testów" zwraca też ogłoszenia nie-IT; limit szczegółów na frazę.
MAX_DETAILS_PER_PHRASE = 60


class NaboryKprmCollector(BaseCollector):
    """Aktywne ogłoszenia z nabory.kprm.gov.pl pasujące do słów kluczowych."""

    source = "Budżetówka (nabory.kprm.gov.pl)"

    def __init__(self, keywords: tuple[str, ...], session: requests.Session | None = None) -> None:
        self.keywords = keywords
        self.session = session or requests.Session()

    def collect(self) -> list[JobOffer]:
        candidates: dict[str, dict[str, str]] = {}
        for phrase in self.keywords:
            found = self._search(phrase)
            for url, row in list(found.items())[:MAX_DETAILS_PER_PHRASE]:
                candidates.setdefault(url, row)

        with ThreadPoolExecutor(max_workers=6) as executor:
            offers = list(executor.map(lambda item: self._details(*item), candidates.items()))
        return [offer for offer in offers if offer is not None]

    def _search(self, phrase: str) -> dict[str, dict[str, str]]:
        params = {
            "Ad[phrase]": phrase,
            "Ad[process_state]": 1,  # tylko aktywne nabory
            "Ad[pagesCnt]": 500,
            "Ad[sort]": 1,
        }
        response = self.session.get(NABORY_URL, params=params, headers=REQUEST_HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        results: dict[str, dict[str, str]] = {}
        for item in soup.select("ul.lis li.row"):
            link = item.select_one("a.single[href]")
            if link is None:
                continue
            fields = {}
            for row in item.select("div.r"):
                label, value = row.find("span"), row.find("b")
                if label and value:
                    fields[label.get_text(strip=True).rstrip(":").casefold()] = value.get_text(" ", strip=True)
            title = item.select_one("strong.title")
            fields["title"] = title.get_text(" ", strip=True) if title else ""
            results[urljoin(NABORY_URL, link["href"])] = fields
        return results

    def _details(self, url: str, row: dict[str, str]) -> JobOffer | None:
        try:
            response = self.session.get(url, headers=REQUEST_HEADERS, timeout=TIMEOUT)
            response.raise_for_status()
        except requests.RequestException:
            return None
        soup = BeautifulSoup(response.text, "lxml")

        def text(selector: str) -> str:
            node = soup.select_one(selector)
            return " ".join(node.get_text(" ", strip=True).split()) if node else ""

        rank = text("h1[class*=job-title__institution-title]") or row.get("title", "")
        matters = re.sub(r"^do spraw:?\s*", "", text("[class*=job-title__position-matters]"), flags=re.I)
        unit = text("[class*=job-title__institution-unit]") or row.get("dział", "")
        title = " – ".join(part for part in (rank, matters) if part)
        if unit:
            title = f"{title} ({unit})"
        # Słowa kluczowe sprawdzamy na stanowisku, zakresie i komórce - nie na
        # całej treści, bo "testów" występuje też np. w testach sprawności.
        if not contains_keyword(title, self.keywords):
            return None

        body = " ".join(
            text(selector)
            for selector in (".job-post__main-content__responsibilities", ".job-post__main-content__requirements")
        )
        place = text(".info-circle__content--address") or row.get("miejscowość", "")
        location = PROFILE.preferred_city if is_preferred_city(place) else place
        return JobOffer(
            company=text("[class*=office-data__office-name]") or row.get("urząd", ""),
            title=title,
            location=location or "Nie podano",
            work_mode=_work_mode(body),
            # Służba cywilna to zawsze umowa o pracę.
            contract_types=("Permanent",),
            salary=extract_salary(text(".info-circle__content--salary")),
            url=url,
            source=self.source,
            skills=extract_skills(body),
            company_categories=("public",),
            expires_in=row.get("ważne do", ""),
            api_confirmed=True,
            description=body,
        )


class GovPlJobOfferCollector(BaseCollector):
    """Ogłoszenia z API portalu gov.pl, aktywne i z tytułem pasującym do fraz."""

    source = "Budżetówka (gov.pl)"

    def __init__(self, keywords: tuple[str, ...], session: requests.Session | None = None) -> None:
        self.keywords = keywords
        self.session = session or requests.Session()

    def collect(self) -> list[JobOffer]:
        today = date.today().isoformat()
        items: dict[str, dict] = {}
        for phrase in self.keywords:
            response = self.session.get(
                GOVPL_API,
                params={"isaInstanceIdentifier": "GOV.PL", "page": 1, "size": 100, "jobPositionPhrase": phrase},
                headers=REQUEST_HEADERS,
                timeout=TIMEOUT,
            )
            response.raise_for_status()
            for item in response.json().get("content", []):
                # API zwraca też zakończone nabory - termin sprawdzamy sami.
                if str(item.get("submissionDeadline") or "9999") >= today and item.get("fullPagePath"):
                    items.setdefault(item["fullPagePath"], item)

        offers = []
        for url, item in items.items():
            title = " ".join(str(item.get("jobPosition", "")).split())
            if not contains_keyword(title, self.keywords):
                continue
            intro = str(item.get("intro") or "")
            location = PROFILE.preferred_city if is_preferred_city(intro) else str(item.get("voivodeship") or "")
            offers.append(
                JobOffer(
                    company=str(item.get("subjectName", "")),
                    title=title,
                    location=f"{location}, Polska" if location else "Nie podano",
                    work_mode=_work_mode(intro),
                    contract_types=normalize_contracts(str(item.get("employmentForm", ""))),
                    salary=extract_salary(intro),
                    url=url,
                    source=self.source,
                    skills=extract_skills(intro),
                    company_categories=("public",),
                    expires_in=str(item.get("submissionDeadline", "")),
                    api_confirmed=True,
                    description=intro,
                )
            )
        return offers


def _work_mode(text: str) -> str:
    mode = normalize_work_mode(text)
    return mode if mode != "Nie podano" else "Office"
