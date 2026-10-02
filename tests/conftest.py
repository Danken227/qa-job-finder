"""Wspólna konfiguracja testów.

Profil testowy (tests/fixtures/search_profile.json) zamiast prywatnego
config/search_profile.json - ustawiany przed importem modułów programu,
bo profil jest wczytywany przy imporcie config.profile.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["QA_JOB_FINDER_PROFILE"] = str(ROOT / "tests" / "fixtures" / "search_profile.json")
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from collectors.base import JobOffer  # noqa: E402


@pytest.fixture
def make_offer():
    def factory(**fields) -> JobOffer:
        defaults = dict(
            company="Firma", title="Manual Tester", location="Wrocław", work_mode="Hybrid",
            contract_types=(), salary="", url="https://example.com/oferta/1", source="test",
        )
        defaults.update(fields)
        return JobOffer(**defaults)

    return factory
