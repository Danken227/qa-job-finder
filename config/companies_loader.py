"""Wczytywanie bazy firm ze stronami kariery."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


COMPANIES_PATH = Path(__file__).with_name("companies.json")

CATEGORY_LABELS = {
    "wroclaw": "Wrocław",
    "remote": "Zdalna",
    "erp_wms": "ERP/WMS",
    "logistics": "Logistyka",
    "fintech": "Fintech",
    "software_house": "Software house",
}


@dataclass(slots=True, frozen=True)
class Company:
    name: str
    careers_url: str
    categories: tuple[str, ...]
    priority: str = "B"
    location_hint: str = ""
    work_mode_hint: str = ""


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
                location_hint=entry.get("location_hint", entry.get("city", "")),
                work_mode_hint=entry.get("work_mode_hint", ""),
            )
        )
    return companies


def format_categories(categories: tuple[str, ...]) -> str:
    return ", ".join(CATEGORY_LABELS.get(category, category) for category in categories)
