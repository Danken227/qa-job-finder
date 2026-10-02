"""Collector ofert z Pracuj.pl.

Pracuj.pl blokuje zwykłe zapytania HTTP (Cloudflare, "Just a moment..."),
dlatego strona wyników jest otwierana w Chromium (Playwright, bez okna).
Wyniki są w osadzonym JSON (``__NEXT_DATA__`` -> ``groupedOffers``):
tytuł, firma, miasta, tryb pracy, umowy i widełki - bez parsowania HTML.

Szukamy po frazach z profilu, osobno dla miasta (z promieniem 30 km)
i dla pracy zdalnej.
"""

from __future__ import annotations

import json
import re
from urllib.parse import quote

from playwright.sync_api import TimeoutError as PlaywrightTimeout

from config.profile import PROFILE
from filter import is_preferred_city
from .base import BaseCollector, JobOffer
from .parsing import extract_skills, normalize_contracts

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)
BASE_URL = "https://www.pracuj.pl/praca"
PAGES_PER_SEARCH = 2  # 50 ofert na stronę
CHALLENGE_WAIT_SECONDS = 20

WORK_MODES = {
    "praca zdalna": "Remote",
    "praca hybrydowa": "Hybrid",
    "praca stacjonarna": "Office",
    "praca mobilna": "Mobile",
}


class PracujCollector(BaseCollector):
    """Oferty z wyszukiwarki Pracuj.pl (miasto z profilu + praca zdalna)."""

    def collect(self) -> list[JobOffer]:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright

        offers: dict[str, JobOffer] = {}
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(
                    headless=True, args=["--disable-blink-features=AutomationControlled"]
                )
            except PlaywrightError as error:
                raise RuntimeError(
                    f"nie udało się uruchomić Chromium ({error}); uruchom: python -m playwright install chromium"
                ) from error
            try:
                for url in self._search_urls():
                    for grouped in self._grouped_offers(browser, url):
                        offer = _to_offer(grouped)
                        if offer:
                            offers.setdefault(offer.url, offer)
            finally:
                browser.close()

        if not offers:
            raise RuntimeError("Pracuj.pl nie zwrócił ofert - możliwa blokada albo zmiana strony.")
        return list(offers.values())

    @staticmethod
    def _search_urls() -> list[str]:
        urls = []
        for keyword in PROFILE.career_search_keywords:
            slug = quote(keyword.casefold(), safe="")
            urls.append(f"{BASE_URL}/{slug};kw/{PROFILE.preferred_city_slug};wp?rd=30")
            if PROFILE.allow_remote:
                urls.append(f"{BASE_URL}/{slug};kw?wm=home-office")
        return urls

    @staticmethod
    def _grouped_offers(browser, url: str) -> list[dict]:
        found: list[dict] = []
        for page_number in range(1, PAGES_PER_SEARCH + 1):
            separator = "&" if "?" in url else "?"
            # Cloudflare przepuszcza pierwszą stronę w sesji, a kolejne zatrzymuje
            # na sprawdzaniu ("Cierpliwości..."), więc każda strona ma nową sesję.
            context = browser.new_context(locale="pl-PL", user_agent=USER_AGENT,
                                          viewport={"width": 1366, "height": 900})
            try:
                page = context.new_page()
                page.goto(f"{url}{separator}pn={page_number}" if page_number > 1 else url,
                          wait_until="domcontentloaded", timeout=45_000)
                try:
                    page.wait_for_selector("script#__NEXT_DATA__", state="attached",
                                           timeout=CHALLENGE_WAIT_SECONDS * 1000)
                except PlaywrightTimeout:
                    pass
                html, title = page.content(), page.title()
            finally:
                context.close()
            match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if not match:
                raise RuntimeError(f"Pracuj.pl: brak danych ofert na stronie ({title[:60]})")
            batch = _find_key(json.loads(match.group(1)), "groupedOffers") or []
            found.extend(batch)
            if len(batch) < 50:
                break
        return found


def _to_offer(grouped: dict) -> JobOffer | None:
    title = " ".join(str(grouped.get("jobTitle") or "").split())
    variants = grouped.get("offers") or []
    if not title or not variants:
        return None
    # Ta sama oferta bywa publikowana dla kilku miast - bierzemy wariant z miasta z profilu.
    chosen = next((item for item in variants if is_preferred_city(str(item.get("displayWorkplace", "")))), variants[0])
    url = str(chosen.get("offerAbsoluteUri") or "")
    if not url:
        return None

    places = list(dict.fromkeys(str(item.get("displayWorkplace", "")) for item in variants if item.get("displayWorkplace")))
    if any(item.get("isWholePoland") for item in variants):
        places.append("cała Polska")
    modes = [WORK_MODES.get(str(mode).casefold(), "") for mode in grouped.get("workModes") or []]
    # Kilka trybów naraz (np. zdalna i hybrydowa) - najkorzystniejszy dla filtra lokalizacji.
    work_mode = next((mode for mode in ("Remote", "Hybrid", "Office", "Mobile") if mode in modes), "Nie podano")

    return JobOffer(
        company=str(grouped.get("companyName") or "Nie podano"),
        title=title,
        location="; ".join(places) or "Nie podano",
        work_mode=work_mode,
        contract_types=normalize_contracts(" ".join(grouped.get("typesOfContract") or [])),
        salary=_salary(str(grouped.get("salaryDisplayText") or "")),
        url=url,
        source="Pracuj.pl",
        skills=extract_skills(str(grouped.get("jobDescription") or "")),
        expires_in=str(grouped.get("expirationDate") or "")[:10],
        # Oferta pochodzi z aktualnej listy wyników; strona oferty jest za
        # Cloudflare, więc weryfikacja zwykłym zapytaniem dostaje 403.
        api_confirmed=True,
    )


def _salary(text: str) -> str:
    """'130–160 zł netto (+ VAT) / godz.' -> '130 - 160 PLN /h' (jednostka jest za dopiskami)."""

    if not text:
        return ""
    amounts = re.findall(r"\d[\d\s ]*(?:,\d+)?", text.split("zł")[0])
    amounts = [" ".join(amount.split()) for amount in amounts if amount.strip()]
    if not amounts:
        return ""
    lowered = text.casefold()
    if "godz" in lowered:
        unit = " /h"
    elif "mies" in lowered:
        unit = " /month"
    elif "rok" in lowered:
        unit = " /year"
    else:
        unit = ""
    kind = " netto" if "netto" in lowered else " brutto" if "brutto" in lowered else ""
    return f"{' - '.join(amounts[:2])} PLN{kind}{unit}"


def _find_key(data, key: str):
    if isinstance(data, dict):
        if key in data:
            return data[key]
        values = data.values()
    elif isinstance(data, list):
        values = data
    else:
        return None
    for value in values:
        found = _find_key(value, key)
        if found is not None:
            return found
    return None
