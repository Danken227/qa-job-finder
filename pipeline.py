"""Wspólny przebieg raportu dla wszystkich skryptów.

deduplikacja -> filtry profilu -> weryfikacja linków -> eksport (Excel + HTML)
"""

from __future__ import annotations

try:
    # Magazyn certyfikatów systemu zamiast pakietu certifi. Część serwerów
    # (BIP Wrocławia, BIP Policji) wysyła niepełny łańcuch certyfikatów -
    # Windows go uzupełnia, czysty certifi zgłasza błąd SSL.
    import truststore

    truststore.inject_into_ssl()
except ImportError:  # pragma: no cover - działa też bez truststore, tylko z błędami SSL na tych stronach
    pass

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from collectors.base import JobOffer
from collectors.careers import CareerPagesCollector
from config.companies_loader import CATEGORY_LABELS
from filter import deduplicate_offers, filter_offers_with_diagnostics
from report import export
from verification import verify_offers


@dataclass(slots=True)
class ReportResult:
    name: str
    found: int
    saved: int
    excel_path: Path
    html_path: Path
    # Oferty, których nie było w poprzednich raportach (wiersze Excela).
    new_rows: list[dict[str, str]] = field(default_factory=list)
    active: int = 0


def configure_console() -> None:
    # Polskie znaki w konsoli Windows (cp1250/cp852) zamiast "krzaczków".
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def build_report(
    offers: list[JobOffer],
    *,
    name: str,
    reports_dir: str,
    basename: str,
    title: str,
    title_keywords: tuple[str, ...] = (),
    seniority_exclude: tuple[str, ...] = (),
) -> ReportResult:
    """Filtruje i weryfikuje oferty, zapisuje raport i wypisuje podsumowanie."""

    unique = deduplicate_offers(offers)
    if len(unique) != len(offers):
        print(f"Deduplikacja: {len(offers)} → {len(unique)} unikalnych ofert.")

    filtering = filter_offers_with_diagnostics(unique, title_keywords, seniority_exclude)
    print(f"Po filtrach: {len(filtering.offers)} ofert do sprawdzenia.")
    if unique:
        print(
            "Odrzucono przez filtry: "
            f"tytuł {filtering.rejected_title}, automatyzacja {filtering.rejected_automation}, "
            f"poziom stanowiska {filtering.rejected_seniority}, lokalizacja {filtering.rejected_location}, "
            f"wynagrodzenie {filtering.rejected_salary}, dopasowanie {filtering.rejected_score}."
        )

    result = verify_offers(filtering.offers)
    exported = export(result.offers, reports_dir=reports_dir, basename=basename, title=title)
    print(f"Zweryfikowano: {result.passed}, odrzucono: {result.rejected}, obcięto limitem: {result.trimmed}.")
    print(f"W tym wyszukiwaniu: {len(result.offers)} ofert, nowych: {len(exported.new_rows)}.")
    print(f"Excel: {exported.excel_path}")
    print(f"HTML:  {exported.html_path}")
    if exported.warning:
        print(f"UWAGA: {exported.warning}")
    return ReportResult(
        name,
        len(offers),
        len(result.offers),
        exported.excel_path,
        exported.html_path,
        exported.new_rows,
        exported.active_rows,
    )


# --- Wspólne elementy skryptów stron karier (firmy i budżetówka) -------------

def add_career_arguments(parser: argparse.ArgumentParser, default_tiers: tuple[str, ...] = ("S",)) -> None:
    parser.add_argument(
        "--tiers",
        nargs="+",
        choices=("S", "A", "B"),
        default=default_tiers,
        help=f"Priorytety do sprawdzenia; domyślnie {' '.join(default_tiers)}.",
    )
    parser.add_argument("--all", action="store_true", help="Sprawdź wpisy z każdego priorytetu.")
    parser.add_argument(
        "--company",
        nargs="+",
        default=(),
        metavar="NAZWA",
        help="Sprawdź tylko wskazane wpisy (fragment nazwy, bez względu na priorytet).",
    )
    parser.add_argument(
        "--render",
        action="store_true",
        help="Renderuj w Chromium (Playwright) strony, z których statyczny HTML nie dał ofert.",
    )
    parser.add_argument(
        "--category",
        nargs="+",
        default=(),
        choices=tuple(CATEGORY_LABELS),
        help="Sprawdź tylko wpisy z podanych kategorii (np. erp_wms logistics).",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Pokaż wynik i metodę dla każdego wpisu.")


def selected_tiers(args: argparse.Namespace) -> tuple[str, ...]:
    return ("S", "A", "B") if args.all else tuple(args.tiers)


def print_career_scan(collector: CareerPagesCollector, verbose: bool, label: str = "Firmy") -> None:
    summary = collector.summary
    print(
        f"{label}: wybrano {summary.selected_companies}, sprawdzono {summary.scanned_companies}, "
        f"niepobrane {summary.failed_companies} "
        f"(blokady: {summary.blocked_companies}, nieaktualne adresy: {summary.outdated_companies})."
    )
    print(f"Wykryte oferty: {summary.discovered_offers}.")
    if verbose:
        print("\nWyniki per wpis:")
        for scan in collector.scans:
            if scan.error:
                status = f"BŁĄD - {scan.error}"
            elif scan.offers:
                status = f"{len(scan.offers)} ofert ({', '.join(scan.methods)})"
            else:
                boards = ", ".join(board.label for board in scan.boards)
                status = f"brak ofert (sprawdzono ATS: {boards})" if boards else "brak ofert"
            print(f"- [{scan.company.priority}] {scan.company.name}: {status}")
        print()


def print_career_problems(collector: CareerPagesCollector) -> None:
    print_list("Zablokowane przez stronę (401/403/429):", collector.blocked)
    print_list("Nieaktualne adresy (404, strona błędu, przekierowanie na stronę główną):", collector.outdated)
    print_list("Błędy techniczne:", collector.failures)
    print_list("Ostrzeżenia:", collector.warnings)


def print_list(header: str, items: list[str]) -> None:
    if not items:
        return
    print(header)
    for item in items:
        print(f"- {item}")
