"""Skrypt 1: oferty QA z portali (JustJoinIT, No Fluff Jobs, RocketJobs, LinkedIn)."""

from __future__ import annotations

from collectors.justjoinit import JustJoinItCollector
from collectors.linkedin import LinkedInCollector
from collectors.nofluffjobs import NoFluffJobsCollector
from collectors.rocketjobs import RocketJobsCollector
from pipeline import ReportResult, build_report, configure_console

REPORTS_DIR = "reports/portals"
BASENAME = "portals_report"


def run() -> ReportResult:
    collected = []
    collectors = (
        JustJoinItCollector(),
        NoFluffJobsCollector(),
        RocketJobsCollector(),
        LinkedInCollector(),
    )
    for collector in collectors:
        source_name = collector.__class__.__name__.replace("Collector", "")
        try:
            offers = collector.collect()
        except Exception as error:
            print(f"{source_name}: pominięto źródło ({error}).")
            continue
        collected.extend(offers)
        print(f"{source_name}: pobrano {len(offers)} ofert.")

    if not collected:
        raise RuntimeError("Żadne źródło nie zwróciło ofert.")

    return build_report(
        collected,
        name="Portale",
        reports_dir=REPORTS_DIR,
        basename=BASENAME,
        title="Raport ofert QA – portale",
    )


def main() -> None:
    configure_console()
    run()


if __name__ == "__main__":
    main()
