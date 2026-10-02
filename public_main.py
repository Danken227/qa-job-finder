"""Skrypt 3: oferty QA w budżetówce.

Trzy źródła:

- nabory.kprm.gov.pl - centralna wyszukiwarka ogłoszeń służby cywilnej
  (ministerstwa, urzędy wojewódzkie, KAS, Policja - pracownicy cywilni...);
- API ogłoszeń portalu gov.pl - instytucje spoza służby cywilnej
  (instytuty badawcze, Lasy Państwowe IT, Wody Polskie...);
- config/public_institutions.json - instytucje z własnymi stronami ofert
  (COI/mObywatel, Centrum e-Zdrowia, Policja, NASK, ZUS, NFZ...).

Tytuły w ogłoszeniach publicznych są urzędowe ("Specjalista ds. testów"),
dlatego obok słów kluczowych z profilu używamy listy
``job_titles.public_sector_include``.
"""

from __future__ import annotations

import argparse

from collectors.careers import CareerPagesCollector
from collectors.nabory import GovPlJobOfferCollector, NaboryKprmCollector
from config.companies_loader import PUBLIC_INSTITUTIONS_PATH
from config.profile import PROFILE
from pipeline import (
    ReportResult,
    add_career_arguments,
    build_report,
    configure_console,
    print_career_problems,
    print_career_scan,
    selected_tiers,
)

REPORTS_DIR = "reports/public"
BASENAME = "public_report"
SOURCE = "Budżetówka"


def run(
    tiers: tuple[str, ...] = ("S", "A", "B"),
    company_names: tuple[str, ...] = (),
    render: bool = False,
    verbose: bool = False,
    skip_nabory: bool = False,
) -> ReportResult:
    offers = []
    if not skip_nabory and not company_names:
        for label, central in (
            ("nabory.kprm.gov.pl", NaboryKprmCollector(keywords=PROFILE.public_title_keywords)),
            ("gov.pl (ogłoszenia instytucji)", GovPlJobOfferCollector(keywords=PROFILE.public_title_keywords)),
        ):
            try:
                found = central.collect()
            except Exception as error:  # noqa: BLE001 - pozostałe źródła nadal mają się wykonać
                print(f"{label}: pominięto źródło ({error}).")
            else:
                offers.extend(found)
                print(f"{label}: {len(found)} aktywnych ogłoszeń pasujących do słów kluczowych.")

    collector = CareerPagesCollector(
        tiers=tiers,
        company_names=company_names,
        render=render,
        companies_path=PUBLIC_INSTITUTIONS_PATH,
        title_keywords=PROFILE.public_title_keywords,
        source=SOURCE,
    )
    offers.extend(collector.collect())
    print_career_scan(collector, verbose, label="Instytucje")

    result = build_report(
        offers,
        name="Budżetówka",
        reports_dir=REPORTS_DIR,
        basename=BASENAME,
        title="Raport ofert QA – sektor publiczny",
        title_keywords=PROFILE.public_title_keywords,
        seniority_exclude=PROFILE.public_seniority_exclude,
    )
    print_career_problems(collector)
    return result


def main() -> None:
    configure_console()
    parser = argparse.ArgumentParser(description="Monitor ofert QA w sektorze publicznym.")
    add_career_arguments(parser, default_tiers=("S", "A", "B"))
    parser.add_argument(
        "--skip-nabory",
        action="store_true",
        help="Pomiń centralne wyszukiwarki (nabory.kprm.gov.pl i gov.pl).",
    )
    args = parser.parse_args()
    run(selected_tiers(args), tuple(args.company), args.render, args.verbose, args.skip_nabory)


if __name__ == "__main__":
    main()
