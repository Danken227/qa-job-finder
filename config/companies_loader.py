"""Wczytywanie bazy firm ze stronami kariery.

Każdy wpis w ``companies.json`` wymaga ``name`` i ``careers_url``. Pola
opcjonalne:

- ``jobs_url`` - strona z listą ofert, jeśli inna niż strona kariery;
- ``ats`` - system rekrutacyjny z publicznym API: adres tablicy ofert
  (np. ``"https://apply.workable.com/firma/"``), obiekt
  ``{"type": "teamtailor", "url": "https://jobs.firma.com"}`` albo lista
  takich wpisów. Typy: greenhouse, lever, smartrecruiters, workable, workday,
  teamtailor, recruitee, ashby, successfactors, phenom;
- ``category`` - jeden z kluczy ``CATEGORY_LABELS`` (np. ``erp_wms``);
- ``enabled`` - ``false`` wyłącza firmę bez usuwania jej z bazy;
- ``notes`` - komentarz dla człowieka, ignorowany przez program.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


COMPANIES_PATH = Path(__file__).with_name("companies.json")
PUBLIC_INSTITUTIONS_PATH = Path(__file__).with_name("public_institutions.json")

CATEGORY_LABELS = {
    "erp_wms": "ERP/WMS",
    "software_house": "Software house",
    "product": "Produkt",
    "enterprise": "Korporacja IT / consulting",
    "finance": "Bankowość / finanse",
    "logistics": "Logistyka / e-commerce",
    "automotive_industrial": "Automotive / przemysł",
    "public": "Sektor publiczny",
}


@dataclass(slots=True, frozen=True)
class AtsSpec:
    url: str
    type: str = ""


@dataclass(slots=True, frozen=True)
class Company:
    name: str
    careers_url: str
    categories: tuple[str, ...]
    priority: str = "B"
    location_hint: str = ""
    work_mode_hint: str = ""
    jobs_url: str = ""
    ats: tuple[AtsSpec, ...] = ()
    enabled: bool = True


def load_companies(path: Path = COMPANIES_PATH) -> list[Company]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    companies: list[Company] = []
    entries = payload["companies"] if isinstance(payload, dict) else payload
    for entry in entries:
        categories = entry.get("categories") or [entry.get("category", "Other")]
        companies.append(
            Company(
                name=entry["name"],
                careers_url=entry["careers_url"],
                categories=tuple(categories),
                priority=entry.get("priority", "B").upper(),
                location_hint=entry.get("location_hint", ""),
                work_mode_hint=entry.get("work_mode_hint", ""),
                jobs_url=entry.get("jobs_url", ""),
                ats=_parse_ats(entry.get("ats")),
                enabled=bool(entry.get("enabled", True)),
            )
        )
    return companies


def _parse_ats(raw: object) -> tuple[AtsSpec, ...]:
    if not raw:
        return ()
    items = raw if isinstance(raw, list) else [raw]
    specs: list[AtsSpec] = []
    for item in items:
        if isinstance(item, str):
            specs.append(AtsSpec(url=item))
        elif isinstance(item, dict) and item.get("url"):
            specs.append(AtsSpec(url=str(item["url"]), type=str(item.get("type", "")).casefold()))
        else:
            raise ValueError(f"Nieprawidłowy wpis 'ats' w companies.json: {item!r}")
    return tuple(specs)


def format_categories(categories: tuple[str, ...]) -> str:
    return ", ".join(CATEGORY_LABELS.get(category, category) for category in categories)
