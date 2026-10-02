"""Skrypt 2: oferty QA bezpośrednio ze stron karier firm (config/companies.json)."""

from __future__ import annotations

import argparse

from collectors.careers import CareerPagesCollector
from config.profile import PROFILE
from pipeline import (
    ReportResult,
    add_career_arguments,
    build_report,
    career_problems,
    configure_console,
    print_career_problems,
    print_career_scan,
    selected_tiers,
)

REPORTS_DIR = "reports/companies"
BASENAME = "company_report"
SHEET_TAB = "Firmy"


def run(
    tiers: tuple[str, ...] = ("S",),
    company_names: tuple[str, ...] = (),
    render: bool = False,
    verbose: bool = False,
    categories: tuple[str, ...] = (),
) -> ReportResult:
    # Polskie tytuły ("Specjalista ds. Testów") obok angielskich słów z profilu.
    collector = CareerPagesCollector(
        tiers=tiers, company_names=company_names, render=render, categories=categories,
        title_keywords=PROFILE.public_title_keywords,
    )
    offers = collector.collect()
    print_career_scan(collector, verbose, label="Firmy")
    result = build_report(
        offers,
        name="Strony firm",
        reports_dir=REPORTS_DIR,
        basename=BASENAME,
        title="Raport ofert QA – strony karier firm",
        title_keywords=PROFILE.public_title_keywords,
        seniority_exclude=PROFILE.public_seniority_exclude,
        sheet_tab=SHEET_TAB,
        problems=career_problems(collector),
        # Przy --company / --tiers S oferty niesprawdzanych firm nie są oznaczane jako zniknięte.
        scope={scan.company.name for scan in collector.scans},
    )
    print_career_problems(collector)
    return result


def main() -> None:
    configure_console()
    parser = argparse.ArgumentParser(description="Monitor oficjalnych stron karier firm.")
    add_career_arguments(parser)
    args = parser.parse_args()
    run(selected_tiers(args), tuple(args.company), args.render, args.verbose, tuple(args.category))


if __name__ == "__main__":
    main()
