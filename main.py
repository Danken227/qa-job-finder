"""Punkt wejścia programu."""

from collectors.justjoinit import JustJoinItCollector
from collectors.linkedin import LinkedInCollector
from collectors.nofluffjobs import NoFluffJobsCollector
from collectors.rocketjobs import RocketJobsCollector
from filter import filter_offers
from report import export
from verification import verify_offers


def main() -> None:
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

    candidates = filter_offers(collected)
    print(f"Po filtrach: {len(candidates)} ofert do sprawdzenia.")

    verified = verify_offers(candidates)
    excel_path, html_path = export(verified)

    print(f"Zweryfikowano i zapisano: {len(verified)} ofert.")
    print(f"Excel: {excel_path}")
    print(f"HTML:  {html_path}")


if __name__ == "__main__":
    main()
