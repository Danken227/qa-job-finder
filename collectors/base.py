"""Wspólny model oferty oraz interfejs źródeł danych."""

from dataclasses import dataclass, field


@dataclass(slots=True)
class JobOffer:
    """Ujednolicona oferta pracy, niezależnie od portalu źródłowego."""

    company: str
    title: str
    location: str
    work_mode: str
    contract_types: tuple[str, ...]
    salary: str
    url: str
    source: str
    skills: tuple[str, ...] = ()
    company_categories: tuple[str, ...] = ()
    expires_in: str = ""
    match_score: int = 0
    match_reasons: tuple[str, ...] = field(default_factory=tuple)
    salary_assessment: str = ""
    verified: bool = False
    # Oferta pochodzi z publicznego API systemu rekrutacyjnego (ATS), więc jej
    # tytuł i aktywność potwierdza samo API - strona oferty bywa renderowana JS.
    api_confirmed: bool = False
    # Pełny opis oferty (pobierany przy weryfikacji) - do analizy języków
    # i charakteru pracy; nie trafia do raportu.
    description: str = ""
    # Udział testów manualnych 0-100 (None = za mało informacji w opisie).
    manual_share: int | None = None
    work_summary: str = ""


class BaseCollector:
    """Każde źródło zwraca listę obiektów JobOffer."""

    def collect(self) -> list[JobOffer]:
        raise NotImplementedError
