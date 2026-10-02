"""Jednorazowa konfiguracja Arkuszy Google.

Sprawdza dostęp do arkusza, zakłada zakładki Portale / Firmy / Budżetówka
i przenosi do nich dotychczasową listę ofert ze statusami z lokalnych plików
Excel (tylko do pustych zakładek - niczego w arkuszu nie nadpisuje).
"""

from __future__ import annotations

import json

import companies_main
import portals_main
import public_main
import sheets
from pipeline import configure_console
from report import COLUMNS, DONE_STATUSES, STATUS_NEW, STATUSES, _read_previous

REPORTS = (
    (portals_main.SHEET_TAB, portals_main.REPORTS_DIR, portals_main.BASENAME),
    (companies_main.SHEET_TAB, companies_main.REPORTS_DIR, companies_main.BASENAME),
    (public_main.SHEET_TAB, public_main.REPORTS_DIR, public_main.BASENAME),
)


def main() -> None:
    configure_console()
    settings = sheets.load_settings()
    if settings is None:
        print("Brakuje config/sheets.json z polem spreadsheet_id (szablon: config/sheets.example.json).")
        return
    if not settings.key_file.exists():
        print(f"Brakuje pliku klucza konta usługi: {settings.key_file}")
        return

    robot = json.loads(settings.key_file.read_text(encoding="utf-8")).get("client_email", "?")
    print(f"Konto usługi (udostępnij mu arkusz jako Edytor): {robot}")
    try:
        store = sheets.SheetStore(settings)
    except Exception as error:  # noqa: BLE001 - pokazujemy przyczynę i wskazówkę
        print(f"Brak dostępu do arkusza: {type(error).__name__}: {error}")
        print("Sprawdź: 1) czy arkusz jest udostępniony powyższemu adresowi jako Edytor, "
              "2) czy w projekcie Google Cloud włączono Google Sheets API, 3) spreadsheet_id.")
        return
    print(f"Połączono z arkuszem: {store.spreadsheet.title}")

    from pathlib import Path

    for tab, reports_dir, basename in REPORTS:
        existing = store.read_rows(tab)
        if existing:
            print(f"- {tab}: zakładka ma już {len(existing)} wierszy - bez zmian.")
            continue
        local = _read_previous(Path(reports_dir) / f"{basename}.xlsx")
        rows = [{column: row.get(column, "") for column in COLUMNS} for row in local]
        store.write_rows(tab, COLUMNS, rows, STATUSES, DONE_STATUSES, STATUS_NEW)
        print(f"- {tab}: utworzono, przeniesiono {len(rows)} ofert z lokalnego Excela.")
    print(f"Gotowe: {settings.url}")


if __name__ == "__main__":
    main()
