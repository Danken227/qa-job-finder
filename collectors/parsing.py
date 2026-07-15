"""Niewielkie funkcje wspólne dla parserów publicznych list ofert."""

from __future__ import annotations

import re
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


def normalize_work_mode(text: str) -> str:
    normalized = text.casefold()
    if "remote" in normalized or "zdaln" in normalized:
        return "Remote"
    if "hybrid" in normalized or "hybryd" in normalized:
        return "Hybrid"
    if "office" in normalized or "stacjonar" in normalized:
        return "Office"
    if "mobile" in normalized or "mobiln" in normalized:
        return "Mobile"
    return "Nie podano"


def normalize_contracts(text: str) -> tuple[str, ...]:
    normalized = text.casefold()
    contracts: list[str] = []
    if "b2b" in normalized:
        contracts.append("B2B")
    if any(value in normalized for value in ("permanent", "uop", "umowa o pracę", "umowa o prace")):
        contracts.append("Permanent")
    if any(value in normalized for value in ("mandate", "umowa zlecenie", " zlecenie")):
        contracts.append("Mandate contract")
    if any(value in normalized for value in ("contract", "umowa o dzieło", "umowa o dzielo")):
        contracts.append("Contract")
    return tuple(contracts)


def extract_salary(text: str) -> str:
    """Odczytuje widełki i normalizuje powszechne oznaczenia jednostek."""

    compact = " ".join(text.replace("\u00a0", " ").split())
    match = re.search(
        r"(?:\d[\d\s,.]*\s*(?:-|–)\s*)?\d[\d\s,.]*\s*"
        r"(?:PLN|EUR|USD|CHF)(?:\s*(?:\+\s*VAT|net|brutto))?"
        r"(?:\s*(?:/|na\s*)?(?:h|godz\.?|godzinę|godzinowo|hour|mies\.?|miesięcznie|month|rok|year))?",
        compact,
        flags=re.IGNORECASE,
    )
    if not match:
        return ""

    salary = match.group(0)
    normalized = salary.casefold()
    if any(unit in normalized for unit in ("godz", "hour", "/h")):
        return f"{salary} /h"
    if any(unit in normalized for unit in ("mies", "month")):
        return f"{salary} /month"
    if any(unit in normalized for unit in ("rok", "year")):
        return f"{salary} /year"
    return salary


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
