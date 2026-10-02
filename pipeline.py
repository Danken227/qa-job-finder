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
from dataclasses import dataclass, field, replace
from pathlib import Path

from analysis import required_foreign_languages, work_profile

from collectors.base import JobOffer
from collectors.careers import CareerPagesCollector
from collectors.pracuj import fetch_descriptions
from config.companies_loader import CATEGORY_LABELS
from filter import deduplicate_offers, filter_offers_with_diagnostics
from config.settings import MAX_REPORT_OFFERS
from report import export
from verification import verify_offers


@dataclass(slots=True)
class ReportResult:
    name: str
    found: int
    saved: int
    excel_path: Path
    html_path: Path
    # Oferty, których nie było w poprzednich raportach (wiersze listy).
    new_rows: list[dict[str, str]] = field(default_factory=list)
    active: int = 0
    # Problemy ze źródłami i zapisem - trafiają do maila, żeby awaria
    # (np. zmiana strony portalu) nie przeszła niezauważona.
    problems: list[str] = field(default_factory=list)
    sheet_url: str = ""


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
    sheet_tab: str = "",
    problems: list[str] | None = None,
    scope: set[str] | None = None,
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
            f"tytuł {filtering.rejected_title}, język obcy {filtering.rejected_language}, "
            f"automatyzacja {filtering.rejected_automation}, "
            f"poziom stanowiska {filtering.rejected_seniority}, lokalizacja {filtering.rejected_location}, "
            f"wynagrodzenie {filtering.rejected_salary}, dopasowanie {filtering.rejected_score}."
        )

    result = verify_offers(filtering.offers)
    print(f"Zweryfikowano linki: {result.passed}, odrzucono: {result.rejected}.")
    analysed = analyse_descriptions(result.offers)
    final = analysed.offers[:MAX_REPORT_OFFERS]
    print(
        f"Analiza opisów: odrzucono {analysed.rejected_language} (inny język obcy niż angielski) "
        f"i {analysed.rejected_automation} (głównie automatyzacja); "
        f"obcięto limitem: {max(0, len(analysed.offers) - MAX_REPORT_OFFERS)}."
    )
    exported = export(final, reports_dir=reports_dir, basename=basename, title=title, sheet_tab=sheet_tab, scope=scope)
    print(f"W tym wyszukiwaniu: {len(final)} ofert, nowych: {len(exported.new_rows)}.")
    print(f"Excel: {exported.excel_path}")
    print(f"HTML:  {exported.html_path}")
    if exported.sheet_url:
        print(f"Arkusz Google (zakładka {sheet_tab}): {exported.sheet_url}")
    for warning in exported.warnings:
        print(f"UWAGA: {warning}")
    return ReportResult(
        name,
        len(offers),
        len(final),
        exported.excel_path,
        exported.html_path,
        exported.new_rows,
        exported.active_rows,
        [*(problems or []), *exported.warnings],
        exported.sheet_url,
    )


@dataclass(slots=True)
class AnalysisResult:
    offers: list[JobOffer]
    rejected_language: int = 0
    rejected_automation: int = 0


def analyse_descriptions(offers: list[JobOffer]) -> AnalysisResult:
    """Na pełnych opisach: odrzuca wymagane języki obce i oferty głównie
    automatyzujące, liczy udział testów manualnych i koryguje ocenę."""

    # Strony Pracuj.pl są za Cloudflare - weryfikacja nie pobrała ich opisu.
    missing = [offer.url for offer in offers if offer.source == "Pracuj.pl" and len(offer.description.split()) < 120]
    if missing:
        try:
            descriptions = fetch_descriptions(missing)
        except Exception as error:  # noqa: BLE001 - analiza zadziała na skróconym opisie
            print(f"Pracuj.pl: nie udało się pobrać pełnych opisów ({error}).")
            descriptions = {}
        offers = [replace(offer, description=descriptions.get(offer.url, offer.description)) for offer in offers]

    result = AnalysisResult([])
    for offer in offers:
        if required_foreign_languages(offer.title, offer.description):
            result.rejected_language += 1
            continue
        profile = work_profile(offer.title, offer.description)
        if profile.is_automation_first:
            result.rejected_automation += 1
            continue
        score = offer.match_score
        if profile.manual_share is not None:
            # 100% manual: +5, 50/50: 0, 0% manual: -5.
            score += round((profile.manual_share - 50) / 10)
        result.offers.append(replace(
            offer, match_score=score, manual_share=profile.manual_share, work_summary=profile.summary
        ))
    result.offers.sort(key=lambda item: (item.match_score, item.work_mode.casefold() == "remote"), reverse=True)
    return result


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


def career_problems(collector: CareerPagesCollector) -> list[str]:
    """Problemy ze stronami karier do sekcji "problemy" w mailu."""

    problems = [f"zablokowane: {item}" for item in collector.blocked]
    problems += [f"nieaktualny adres: {item}" for item in collector.outdated]
    problems += [f"błąd: {item}" for item in collector.failures]
    # Ostrzeżenia o niedostępnym ATS oznaczają realnie niesprawdzoną firmę.
    problems += [f"ostrzeżenie: {item}" for item in collector.warnings if "niedostępny" in item]
    return problems


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
