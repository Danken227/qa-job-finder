"""Punkt wejścia programu."""

from collectors.justjoinit import JustJoinItCollector
from filter import filter_offers
from report import export
from verification import verify_offers


def main() -> None:
    print("Pobieram oferty z JustJoinIT...")
    collected = JustJoinItCollector().collect()
    print(f"Pobrano: {len(collected)} ofert.")

    candidates = filter_offers(collected)
    print(f"Po filtrach: {len(candidates)} ofert do sprawdzenia.")

    verified = verify_offers(candidates)
    excel_path, html_path = export(verified)

    print(f"Zweryfikowano i zapisano: {len(verified)} ofert.")
    print(f"Excel: {excel_path}")
    print(f"HTML:  {html_path}")


if __name__ == "__main__":
    main()
