"""Skrypt 4: uruchamia po kolei portale, strony firm i budżetówkę.

Każde źródło tworzy własny raport (reports/portals, reports/companies,
reports/public). Błąd jednego źródła nie przerywa pozostałych.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from pathlib import Path

import companies_main
import notify
import portals_main
import public_main
from pipeline import ReportResult, configure_console


def main() -> None:
    # Harmonogram zadań startuje w innym katalogu - raporty mają trafić do projektu.
    os.chdir(Path(__file__).resolve().parent)
    configure_console()
    parser = argparse.ArgumentParser(description="Uruchamia wszystkie wyszukiwania ofert QA.")
    parser.add_argument(
        "--tiers",
        nargs="+",
        choices=("S", "A", "B"),
        default=("S", "A", "B"),
        help="Priorytety firm i instytucji; domyślnie wszystkie.",
    )
    parser.add_argument("--render", action="store_true", help="Renderuj strony JS w Chromium (wolniejsze).")
    parser.add_argument(
        "--email",
        action="store_true",
        help="Wyślij mail (config/notify.json) - tylko gdy są nowe oferty albo problemy ze źródłami.",
    )
    parser.add_argument("--email-always", action="store_true", help="Wyślij mail nawet bez nowości.")
    parser.add_argument(
        "--skip",
        nargs="+",
        choices=("portals", "companies", "public"),
        default=(),
        help="Pomiń wybrane źródła.",
    )
    parser.add_argument(
        "--log",
        metavar="PLIK",
        help="Zapisz cały wynik do pliku (dla Harmonogramu zadań, który uruchamia skrypt bez okna).",
    )
    args = parser.parse_args()
    if args.log:
        # pythonw.exe nie ma konsoli - wynik i błędy idą do pliku logu.
        log_path = Path(args.log)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(log_path, "w", encoding="utf-8", buffering=1)  # noqa: SIM115
        print(f"Start: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    tiers = tuple(args.tiers)

    steps = (
        ("portals", "1/3 Portale z ogłoszeniami", portals_main.run, {}),
        ("companies", "2/3 Strony karier firm", companies_main.run, {"tiers": tiers, "render": args.render}),
        ("public", "3/3 Budżetówka", public_main.run, {"tiers": tiers, "render": args.render}),
    )
    results: list[ReportResult] = []
    errors: list[str] = []
    for key, header, run, kwargs in steps:
        if key in args.skip:
            continue
        print(f"\n{'=' * 70}\n{header}\n{'=' * 70}")
        started = time.monotonic()
        try:
            results.append(run(**kwargs))
        except Exception as error:  # noqa: BLE001 - pozostałe źródła mają się wykonać
            traceback.print_exc()
            errors.append(f"{header}: {error}")
        print(f"Czas: {time.monotonic() - started:.0f} s")

    print(f"\n{'=' * 70}\nPodsumowanie\n{'=' * 70}")
    for result in results:
        print(
            f"- {result.name}: znaleziono {result.found}, po filtrach {result.saved}, "
            f"nowych {len(result.new_rows)} → {result.excel_path}"
        )
    for error in errors:
        print(f"- BŁĄD {error}")

    if args.email or args.email_always:
        new_total = sum(len(result.new_rows) for result in results)
        problems = errors or any(result.problems for result in results)
        if not (new_total or problems or args.email_always):
            # Bez nowości mail nic nie wnosi - nie zaśmiecamy skrzynki.
            print("Brak nowych ofert i problemów - mail nie został wysłany.")
            return
        try:
            notify.send_reports(results, errors)
        except Exception as error:  # noqa: BLE001 - raporty i tak są zapisane na dysku
            print(f"Nie udało się wysłać maila: {error}")
            raise SystemExit(1) from error


if __name__ == "__main__":
    main()
