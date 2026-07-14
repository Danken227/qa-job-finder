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
    expires_in: str = ""
    match_score: int = 0
    match_reasons: tuple[str, ...] = field(default_factory=tuple)
    salary_assessment: str = ""
    verified: bool = False


class BaseCollector:
    """Każde źródło zwraca listę obiektów JobOffer."""

    def collect(self) -> list[JobOffer]:
        raise NotImplementedError
