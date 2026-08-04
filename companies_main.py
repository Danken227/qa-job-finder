"""Raport ofert QA z oficjalnych stron karier firm."""

from __future__ import annotations

import argparse

from collectors.careers import CareerPagesCollector
from filter import deduplicate_offers, filter_offers
from report import export
from verification import verify_offers


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor oficjalnych stron karier firm.")
    parser.add_argument(
        "--tiers",
        nargs="+",
        choices=("S", "A", "B"),
        default=("S",),
        help="Priorytety firm do sprawdzenia; domyślnie tylko S.",
    )
    parser.add_argument("--all", action="store_true", help="Sprawdź firmy z każdego priorytetu.")
    args = parser.parse_args()
    tiers = ("S", "A", "B") if args.all else tuple(args.tiers)

    collector = CareerPagesCollector(tiers=tiers)
    offers = collector.collect()
    summary = collector.summary
    print(
        f"Firmy: wybrano {summary.selected_companies}, sprawdzono {summary.scanned_companies}, "
        f"niepobrane {summary.failed_companies} "
        f"(blokady: {summary.blocked_companies}, nieaktualne adresy: {summary.outdated_companies})."
    )
    print(f"Oferty wykryte na stronach karier: {summary.discovered_offers}.")

    candidates = filter_offers(deduplicate_offers(offers))
    print(f"Po filtrach: {len(candidates)} ofert do sprawdzenia.")
    result = verify_offers(candidates)
    excel_path, html_path = export(result.offers, reports_dir="reports/companies", basename="company_report")

    print(f"Zweryfikowano: {result.passed}, odrzucono: {result.rejected}, obcięto limitem: {result.trimmed}.")
    print(f"Zapisano: {len(result.offers)} ofert.")
    print(f"Excel: {excel_path}")
    print(f"HTML:  {html_path}")
    if collector.blocked:
        print("Zablokowane przez stronę (403):")
        for failure in collector.blocked:
            print(f"- {failure}")
    if collector.outdated:
        print("Nieaktualne adresy (404):")
        for failure in collector.outdated:
            print(f"- {failure}")
    if collector.failures:
        print("Błędy techniczne:")
        for failure in collector.failures:
            print(f"- {failure}")


if __name__ == "__main__":
    main()
