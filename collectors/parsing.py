"""Niewielkie funkcje wspólne dla parserów publicznych list ofert."""

from __future__ import annotations

import json
import re
import unicodedata
from html import unescape
from urllib.parse import urlsplit, urlunsplit


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
    "API testing",
    "Manual Testing",
    "Manual tests",
    "TestRail",
    "Xray",
    "Zephyr",
    "SoapUI",
)


def extract_skills(text: str) -> tuple[str, ...]:
    """Zwraca istotne dla profilu QA technologie znalezione w tekście."""

    return tuple(
        skill
        for skill in KNOWN_SKILLS
        if re.search(rf"\b{re.escape(skill)}\b", text, flags=re.IGNORECASE)
    )


FULLY_REMOTE = ("100% remote", "fully remote", "full remote", "full-remote", "remote-first", "remote only",
                "100% zdaln", "w pełni zdaln", "całkowicie zdaln", "wyłącznie zdaln", "tylko zdaln")


def normalize_work_mode(text: str) -> str:
    normalized = text.casefold()
    # Kolejność ma znaczenie: "model hybrydowy (3 dni stacjonarnie, 2 dni
    # zdalnie)" to praca hybrydowa, choć pada w nim słowo "zdalnie".
    if any(marker in normalized for marker in FULLY_REMOTE):
        return "Remote"
    if "hybrid" in normalized or "hybryd" in normalized:
        return "Hybrid"
    if "remote" in normalized or "zdaln" in normalized:
        return "Remote"
    if any(marker in normalized for marker in ("office", "stacjonar", "on-site", "onsite", "on site", "w biurze")):
        return "Office"
    # "Mobile" tylko jako tryb pracy - "aplikacje mobilne" to przedmiot testów.
    if "praca mobiln" in normalized or "mobile work" in normalized:
        return "Mobile"
    return "Nie podano"


def normalize_contracts(text: str) -> tuple[str, ...]:
    normalized = text.casefold()
    contracts: list[str] = []
    if "b2b" in normalized:
        contracts.append("B2B")
    if any(value in normalized for value in ("permanent", "uop", "umowa o pracę", "umowa o prace",
                                              "employment contract", "contract of employment")):
        contracts.append("Permanent")
    if any(value in normalized for value in ("mandate", "umowa zlecenie", " zlecenie")):
        contracts.append("Mandate contract")
    # Samo "contract" to zwykle "contract testing" albo "contracts with brands",
    # a nie rodzaj umowy - uznajemy tylko jednoznaczne nazwy.
    if any(value in normalized for value in ("umowa o dzieło", "umowa o dzielo", "contract for specific work")):
        contracts.append("Contract")
    return tuple(contracts)


def extract_salary(text: str) -> str:
    """Odczytuje widełki i normalizuje powszechne oznaczenia jednostek."""

    compact = " ".join(text.replace("\u00a0", " ").split())
    match = re.search(
        r"(?:\d[\d\s,.]*\s*(?:-|–|do)\s*)?\d[\d\s,.]*\s*"
        r"(?:PLN|EUR|USD|CHF|zł|złotych)(?!\w)(?:\s*(?:\+\s*VAT|netto|net|brutto))?"
        # Granica słowa po jednostce: "PLN hybrid" to nie stawka godzinowa.
        r"(?:\s*(?:/|na\s*)?(?:h|godz\.?|godzinę|godzinowo|hour|mies\.?|miesięcznie|month|rocznie|rok|year)(?!\w))?",
        compact,
        flags=re.IGNORECASE,
    )
    if not match:
        return _salary_without_currency(compact)

    # Ogłoszenia publiczne podają "zł" - ujednolicamy do PLN dla oceny widełek.
    salary = re.sub(r"złotych|zł(?!\w)", "PLN", match.group(0), flags=re.IGNORECASE)
    unit_match = re.search(
        r"\s*(?:/|na\s*)?(?:h|godz\.?|godzinę|godzinowo|hour|mies\.?|miesięcznie|month|rocznie|rok|year)$",
        salary,
        flags=re.IGNORECASE,
    )
    if not unit_match:
        return salary
    amount, unit = salary[: unit_match.start()].rstrip(), unit_match.group(0).casefold()
    if any(marker in unit for marker in ("godz", "hour")) or unit.strip(" /na") == "h":
        return f"{amount} /h"
    if any(marker in unit for marker in ("mies", "month")):
        return f"{amount} /month"
    return f"{amount} /year"


# "Wynagrodzenie: od 8000 do 9500 brutto/miesiąc" - kwoty bez waluty, ale
# z jednoznacznym kontekstem (słowo "wynagrodzenie" i brutto/netto).
_SALARY_NO_CURRENCY = re.compile(
    r"(?:wynagrodzeni\w*|salary|pensja|stawka)\W{0,5}[^\d]{0,25}?"
    r"(?:od\s*)?(\d[\d\s.,]*\d)\s*(?:k\b)?\s*(?:-|–|do|to)\s*(\d[\d\s.,]*\d)\s*(?:k\b)?\s*"
    r"(brutto|netto|gross|net)\b\s*(?:/|na|per|a)?\s*(miesi\w*|mies\.?|month|godz\w*|h\b|hour|rok\w*|year)?",
    re.IGNORECASE,
)


def _salary_without_currency(text: str) -> str:
    match = _SALARY_NO_CURRENCY.search(text)
    if not match:
        return ""
    low, high, kind, unit = match.groups()
    unit = (unit or "").casefold()
    suffix = " /h" if unit.startswith(("godz", "h", "hour")) else " /year" if unit.startswith(("rok", "year")) else " /month"
    return f"{' '.join(low.split())} - {' '.join(high.split())} PLN {kind.casefold()}{suffix}"


def normalize_title(title: str) -> str:
    """Ujednolica tytuł do porównań (deduplikacja, fuzzy match w weryfikacji)."""

    normalized = title.casefold()
    normalized = re.sub(r"\([^)]*\)", "", normalized)
    normalized = re.sub(r"\[[^\]]*\]", "", normalized)
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    return " ".join(normalized.split())


def direct_url(url: str) -> str:
    """Usuwa parametry śledzące, zostawiając stabilny adres konkretnej oferty."""

    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def fold_text(text: str) -> str:
    """Małe litery bez polskich znaków: "Wrocław" == "wroclaw" == "WROCLAW"."""

    normalized = unicodedata.normalize("NFKD", text.replace("ł", "l").replace("Ł", "L"))
    return "".join(char for char in normalized if not unicodedata.combining(char)).casefold()


def contains_keyword(text: str, keywords: tuple[str, ...] | list[str]) -> bool:
    """Sprawdza słowa kluczowe od początku wyrazu; krótkie (np. "qa") - całe słowo.

    Dzięki temu "qa" nie pasuje do "aquarium", "tester" nie pasuje do
    "Pentester", a nadal pasuje do "Software Tester" i "testerka".
    """

    folded = " " + re.sub(r"[^\w]+", " ", fold_text(text)) + " "
    for keyword in keywords:
        folded_keyword = " ".join(re.sub(r"[^\w]+", " ", fold_text(keyword)).split())
        if not folded_keyword:
            continue
        if len(folded_keyword) <= 3:
            if f" {folded_keyword} " in folded:
                return True
        elif " " + folded_keyword in folded:
            return True
    return False


# Większe polskie miasta (nazwa w raporcie, warianty pisowni). Pozwala zapisać
# faktyczne miasto oferty zamiast "Nie podano", gdy nie jest to miasto z profilu.
POLISH_CITIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Warszawa", ("warszawa", "warsaw")), ("Kraków", ("krakow", "cracow")), ("Łódź", ("lodz",)),
    ("Wrocław", ("wroclaw",)), ("Poznań", ("poznan",)), ("Gdańsk", ("gdansk",)), ("Gdynia", ("gdynia",)),
    ("Sopot", ("sopot",)), ("Szczecin", ("szczecin",)), ("Bydgoszcz", ("bydgoszcz",)), ("Lublin", ("lublin",)),
    ("Białystok", ("bialystok",)), ("Katowice", ("katowice",)), ("Gliwice", ("gliwice",)),
    ("Częstochowa", ("czestochowa",)), ("Radom", ("radom",)), ("Toruń", ("torun",)), ("Rzeszów", ("rzeszow",)),
    ("Kielce", ("kielce",)), ("Olsztyn", ("olsztyn",)), ("Opole", ("opole",)), ("Bielsko-Biała", ("bielsko",)),
    ("Zielona Góra", ("zielona gora",)), ("Legnica", ("legnica",)), ("Wałbrzych", ("walbrzych",)),
    ("Tychy", ("tychy",)), ("Sosnowiec", ("sosnowiec",)), ("Płock", ("plock",)), ("Elbląg", ("elblag",)),
    ("Koszalin", ("koszalin",)), ("Słupsk", ("slupsk",)), ("Tarnów", ("tarnow",)), ("Kalisz", ("kalisz",)),
    ("Lubin", ("lubin",)), ("Jelenia Góra", ("jelenia gora",)), ("Gorzów Wielkopolski", ("gorzow",)),
)


def extract_cities(text: str) -> list[str]:
    """Polskie miasta wymienione w tekście (bez polskich znaków, całe słowa)."""

    folded = " " + re.sub(r"[^a-z]+", " ", fold_text(text)) + " "
    return [name for name, variants in POLISH_CITIES if any(f" {variant} " in folded for variant in variants)]


def work_mode_from_flags(remote: bool = False, hybrid: bool = False) -> str:
    if remote:
        return "Remote"
    if hybrid:
        return "Hybrid"
    return "Nie podano"


def parse_json_ld_jobs(html: str) -> list[dict]:
    """Zwraca obiekty schema.org/JobPosting osadzone w stronie (JSON-LD).

    Wiele stron karier (oraz ATS) publikuje je dla Google for Jobs - to
    najbardziej wiarygodne źródło tytułu, lokalizacji i trybu pracy.
    """

    postings: list[dict] = []
    for raw in re.findall(
        r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        try:
            payload = json.loads(raw.strip())
        except ValueError:
            continue
        stack = [payload]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                item_type = item.get("@type")
                types = item_type if isinstance(item_type, list) else [item_type]
                if "JobPosting" in types:
                    postings.append(item)
                stack.extend(value for key, value in item.items() if key in ("@graph", "itemListElement", "item"))
    return postings


def json_ld_title(posting: dict) -> str:
    return " ".join(unescape(str(posting.get("title") or "")).split())


def json_ld_location(posting: dict) -> str:
    """Miasta z jobLocation; puste, jeśli oferta ich nie podaje."""

    locations = posting.get("jobLocation") or []
    if isinstance(locations, dict):
        locations = [locations]
    cities: list[str] = []
    for location in locations:
        if not isinstance(location, dict):
            continue
        address = location.get("address") or {}
        if isinstance(address, str):
            cities.append(address)
            continue
        if isinstance(address, dict):
            city = address.get("addressLocality") or address.get("addressRegion") or ""
            country = address.get("addressCountry") or ""
            if isinstance(country, dict):
                country = country.get("name", "")
            parts = [part for part in (str(city), str(country)) if part]
            if parts:
                cities.append(", ".join(parts))
    return "; ".join(dict.fromkeys(cities))


def json_ld_work_mode(posting: dict) -> str:
    location_type = str(posting.get("jobLocationType") or "").casefold()
    if "telecommute" in location_type:
        return "Remote"
    return "Nie podano"


def json_ld_contracts(posting: dict) -> tuple[str, ...]:
    employment = posting.get("employmentType") or ""
    if isinstance(employment, list):
        employment = " ".join(str(item) for item in employment)
    employment = str(employment).casefold()
    contracts: list[str] = []
    if "full_time" in employment or "part_time" in employment:
        contracts.append("Permanent")
    if "contractor" in employment:
        contracts.append("B2B")
    return tuple(contracts)


def json_ld_salary(posting: dict) -> str:
    salary = posting.get("baseSalary")
    if not isinstance(salary, dict):
        return ""
    currency = salary.get("currency", "")
    value = salary.get("value") or {}
    if not isinstance(value, dict):
        return f"{value} {currency}".strip()
    low, high = value.get("minValue"), value.get("maxValue")
    amount = value.get("value")
    unit = str(value.get("unitText") or "").casefold()
    suffix = {"hour": " /h", "month": " /month", "year": " /year"}.get(unit, "")
    if low and high:
        return f"{low} - {high} {currency}{suffix}".strip()
    if amount or high or low:
        return f"{amount or high or low} {currency}{suffix}".strip()
    return ""
