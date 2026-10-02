"""Skrypt 1: oferty QA z portali (JustJoinIT, No Fluff Jobs, RocketJobs, Pracuj.pl, LinkedIn)."""

from __future__ import annotations

from collectors.justjoinit import JustJoinItCollector
from collectors.linkedin import LinkedInCollector
from collectors.nofluffjobs import NoFluffJobsCollector
from collectors.pracuj import PracujCollector
from collectors.rocketjobs import RocketJobsCollector
from config.profile import PROFILE
from pipeline import ReportResult, build_report, configure_console

REPORTS_DIR = "reports/portals"
BASENAME = "portals_report"
SHEET_TAB = "Portale"


def run() -> ReportResult:
    collected = []
    problems: list[str] = []
    collectors = (
        JustJoinItCollector(),
        NoFluffJobsCollector(),
        RocketJobsCollector(),
        PracujCollector(),
        LinkedInCollector(),
    )
    for collector in collectors:
        source_name = collector.__class__.__name__.replace("Collector", "")
        try:
            offers = collector.collect()
        except Exception as error:
            print(f"{source_name}: pominięto źródło ({error}).")
            problems.append(f"{source_name}: źródło nie działa ({error})")
            continue
        collected.extend(offers)
        print(f"{source_name}: pobrano {len(offers)} ofert.")
        if not offers:
            problems.append(f"{source_name}: 0 ofert - możliwa zmiana strony portalu")

    if not collected:
        raise RuntimeError("Żadne źródło nie zwróciło ofert.")

    return build_report(
        collected,
        name="Portale",
        reports_dir=REPORTS_DIR,
        basename=BASENAME,
        title="Raport ofert QA – portale",
        # Polskie tytuły ("Specjalista ds. Testów") obok angielskich słów z profilu.
        title_keywords=PROFILE.public_title_keywords,
        seniority_exclude=PROFILE.public_seniority_exclude,
        sheet_tab=SHEET_TAB,
        problems=problems,
    )


def main() -> None:
    configure_console()
    run()


if __name__ == "__main__":
    main()
