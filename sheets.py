"""Przechowywanie listy ofert w Arkuszach Google.

Arkusz ma zakładki "Portale", "Firmy" i "Budżetówka" - ten sam układ kolumn
co lokalny Excel. Program loguje się kontem usługi Google (plik klucza JSON
w ``config/``, ignorowany przez Git), któremu udostępniasz arkusz jako
edytorowi. Konfiguracja: ``config/sheets.json`` i ``python setup_sheets.py``.

Formatowanie (lista statusów, kolory, zamrożony nagłówek) jest zakładane tylko
przy tworzeniu zakładki - później program zmienia wyłącznie wartości, więc
Twoje zmiany szerokości kolumn czy filtry zostają.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

CONFIG_DIR = Path(__file__).parent / "config"
SHEETS_CONFIG_PATH = CONFIG_DIR / "sheets.json"
DEFAULT_KEY_FILE = CONFIG_DIR / "google_service_account.json"
INITIAL_ROWS = 1000


@dataclass(frozen=True, slots=True)
class SheetsSettings:
    spreadsheet_id: str
    key_file: Path

    @property
    def url(self) -> str:
        return f"https://docs.google.com/spreadsheets/d/{self.spreadsheet_id}"


def load_settings(path: Path = SHEETS_CONFIG_PATH) -> SheetsSettings | None:
    """Ustawienia arkusza albo None, gdy Arkusze Google nie są skonfigurowane."""

    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    spreadsheet_id = str(raw.get("spreadsheet_id", "")).strip()
    if not spreadsheet_id:
        return None
    key_file = Path(raw.get("service_account_file") or DEFAULT_KEY_FILE)
    if not key_file.is_absolute():
        key_file = Path(__file__).parent / key_file
    return SheetsSettings(spreadsheet_id, key_file)


class SheetStore:
    """Odczyt i zapis wierszy ofert w zakładkach jednego arkusza."""

    def __init__(self, settings: SheetsSettings) -> None:
        import gspread

        self.settings = settings
        self._gspread = gspread
        client = gspread.service_account(filename=str(settings.key_file))
        self.spreadsheet = client.open_by_key(settings.spreadsheet_id)

    def read_rows(self, tab: str) -> list[dict[str, str]]:
        """Wiersze zakładki jako słowniki (pusta lista, gdy zakładki jeszcze nie ma)."""

        try:
            worksheet = self.spreadsheet.worksheet(tab)
        except self._gspread.WorksheetNotFound:
            return []
        values = worksheet.get_all_values()
        if not values:
            return []
        header = values[0]
        return [
            {column: value for column, value in zip(header, row)}
            for row in values[1:]
            if any(cell.strip() for cell in row)
        ]

    def write_rows(self, tab: str, columns: tuple[str, ...], rows: list[dict[str, str]],
                   statuses: tuple[str, ...], done_statuses: tuple[str, ...], new_status: str,
                   user_columns: tuple[str, ...] = ("Status",), hidden_columns: tuple[str, ...] = ()) -> None:
        layout = _Layout(columns, statuses, done_statuses, new_status, user_columns, hidden_columns)
        worksheet = self._worksheet(tab, layout)
        values = [list(columns)] + [[str(row.get(column, "") or "") for column in columns] for row in rows]
        if worksheet.row_count < len(values) + 100:
            worksheet.resize(rows=len(values) + 500)
        # Czyścimy całą szerokość - po zmianie układu stare kolumny też mają zniknąć.
        worksheet.batch_clear([f"A2:{_column_letter(max(worksheet.col_count, len(columns)))}{worksheet.row_count}"])
        # RAW: tytuł zaczynający się od "=" czy "+" nie zostanie potraktowany jak formuła.
        worksheet.update(values=values, range_name="A1", value_input_option="RAW")
        self._link_titles(worksheet, columns, rows)

    def _link_titles(self, worksheet, columns: tuple[str, ...], rows: list[dict[str, str]]) -> None:
        """Tytuł w kolumnie "Stanowisko" jako klikalny link do oferty."""

        if "Stanowisko" not in columns or "Link" not in columns or not rows:
            return
        title_index = columns.index("Stanowisko")
        cells = []
        for row in rows:
            title, url = str(row.get("Stanowisko") or ""), str(row.get("Link") or "")
            cell: dict = {"userEnteredValue": {"stringValue": title}}
            if title and url.startswith("http"):
                # Link na całym tekście; każdy zapis ustawia go od nowa dla
                # każdego wiersza, więc po przesunięciu wierszy nie zostaje stary.
                cell["textFormatRuns"] = [{"startIndex": 0, "format": {"link": {"uri": url}}}]
            cells.append({"values": [cell]})
        self.spreadsheet.batch_update({"requests": [{"updateCells": {
            "range": {"sheetId": worksheet.id, "startRowIndex": 1, "endRowIndex": 1 + len(rows),
                      "startColumnIndex": title_index, "endColumnIndex": title_index + 1},
            "rows": cells,
            "fields": "userEnteredValue,textFormatRuns",
        }}]})

    def _worksheet(self, tab: str, layout: "_Layout"):
        try:
            worksheet = self.spreadsheet.worksheet(tab)
        except self._gspread.WorksheetNotFound:
            worksheet = self.spreadsheet.add_worksheet(title=tab, rows=INITIAL_ROWS, cols=len(layout.columns))
            self._format(worksheet, layout)
            # Domyślna, pusta zakładka "Arkusz1" / "Sheet1" tylko przeszkadza.
            for sheet in self.spreadsheet.worksheets():
                if sheet.title in ("Arkusz1", "Sheet1") and not any(sheet.get_all_values()):
                    self.spreadsheet.del_worksheet(sheet)
            return worksheet

        if worksheet.row_values(1) != list(layout.columns):
            # Zmienił się układ kolumn (np. usunięta "Notatka") - reguły kolorów
            # odwołują się do liter kolumn, więc formatowanie trzeba założyć od nowa.
            self._reset_format(worksheet, len(layout.columns))
            self._format(worksheet, layout)
        return worksheet

    def _reset_format(self, worksheet, column_count: int) -> None:
        meta = self.spreadsheet.fetch_sheet_metadata({"fields": "sheets(properties(sheetId),conditionalFormats)"})
        rules = next((len(sheet.get("conditionalFormats", [])) for sheet in meta["sheets"]
                      if sheet["properties"]["sheetId"] == worksheet.id), 0)
        requests = [{"deleteConditionalFormatRule": {"sheetId": worksheet.id, "index": 0}} for _ in range(rules)]
        requests.append({"clearBasicFilter": {"sheetId": worksheet.id}})
        self.spreadsheet.batch_update({"requests": requests})
        worksheet.batch_clear([f"A1:{_column_letter(max(worksheet.col_count, column_count))}1"])
        if worksheet.col_count > column_count:
            worksheet.resize(cols=column_count)

    def _format(self, worksheet, layout: "_Layout") -> None:
        columns = layout.columns
        sheet_id = worksheet.id
        status_index = columns.index("Status")
        active_letter = _column_letter(columns.index("W ostatnim wyszukiwaniu") + 1)
        status_letter = _column_letter(status_index + 1)
        user_columns = {columns.index(name) for name in layout.user_columns if name in columns}
        data_range = {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": INITIAL_ROWS,
                      "startColumnIndex": 0, "endColumnIndex": len(columns)}

        def rule(formula: str, fmt: dict) -> dict:
            # Każdy warunek osobno, bez OR(): separator argumentów zależy od
            # ustawień regionalnych arkusza (przecinek / średnik).
            return {"addConditionalFormatRule": {"index": 0, "rule": {
                "ranges": [data_range],
                "booleanRule": {"condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": formula}]},
                                "format": fmt}}}}

        requests = [
            {"updateSheetProperties": {
                "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 1}},
                "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"}},
            {"setDataValidation": {
                "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": INITIAL_ROWS,
                          "startColumnIndex": status_index, "endColumnIndex": status_index + 1},
                "rule": {"condition": {"type": "ONE_OF_LIST",
                                       "values": [{"userEnteredValue": status} for status in layout.statuses]},
                         "showCustomUi": True, "strict": False}}},
            {"setBasicFilter": {"filter": {"range": {"sheetId": sheet_id, "startRowIndex": 0,
                                                     "startColumnIndex": 0, "endColumnIndex": len(columns)}}}},
            rule(f'=${status_letter}2="{layout.new_status}"', {"backgroundColor": _rgb("E2EFDA")}),
            *(rule(f'=${status_letter}2="{status}"',
                   {"backgroundColor": _rgb("EDEDED"), "textFormat": {"foregroundColor": _rgb("808080")}})
              for status in layout.done_statuses),
            # Dodawana jako ostatnia z index=0, więc ma najwyższy priorytet.
            rule(f'=${active_letter}2="Nie"',
                 {"textFormat": {"foregroundColor": _rgb("A6A6A6"), "strikethrough": True}}),
        ]
        for index, column in enumerate(columns):
            requests.append({"repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1,
                          "startColumnIndex": index, "endColumnIndex": index + 1},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": _rgb("C55A11" if index in user_columns else "1F4E78"),
                    "textFormat": {"bold": True, "foregroundColor": _rgb("FFFFFF")},
                    "wrapStrategy": "WRAP", "verticalAlignment": "TOP"}},
                "fields": "userEnteredFormat(backgroundColor,textFormat,wrapStrategy,verticalAlignment)"}})
            requests.append({"updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": index, "endIndex": index + 1},
                "properties": {"pixelSize": COLUMN_PIXELS.get(column, 120),
                               "hiddenByUser": column in layout.hidden_columns},
                "fields": "pixelSize,hiddenByUser"}})
        self.spreadsheet.batch_update({"requests": requests})


@dataclass(frozen=True, slots=True)
class _Layout:
    columns: tuple[str, ...]
    statuses: tuple[str, ...]
    done_statuses: tuple[str, ...]
    new_status: str
    user_columns: tuple[str, ...]
    hidden_columns: tuple[str, ...]


COLUMN_PIXELS = {
    "Status": 130, "Firma": 170, "Stanowisko": 300, "Lokalizacja": 160,
    "Manual / automat": 320, "Ocena wynagrodzenia": 200, "Wynagrodzenie": 170, "Link": 320,
}


def _rgb(hex_color: str) -> dict:
    return {key: int(hex_color[index:index + 2], 16) / 255 for key, index in (("red", 0), ("green", 2), ("blue", 4))}


def _column_letter(number: int) -> str:
    letters = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters
