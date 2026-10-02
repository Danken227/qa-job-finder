"""Eksport ofert do Arkuszy Google / Excela (trwała lista ze statusami) i HTML.

Gdy skonfigurowane są Arkusze Google (``config/sheets.json``), to one są
źródłem statusów: program czyta zakładkę tuż przed zapisem, a lokalny Excel
jest kopią zapasową. Bez konfiguracji źródłem jest lokalny Excel.

Plik Excel jest jednocześnie "trackerem": przy każdym uruchomieniu program
wczytuje poprzednią wersję i przenosi to, co ustawiłeś ręcznie - kolumnę
**Status** - oraz datę pierwszego wykrycia. Tytuł w kolumnie "Stanowisko" jest
linkiem do oferty; kolumna "Link" jest ukryta (służy do rozpoznawania ofert). Oferty, których nie
ma w bieżącym wyszukiwaniu, nie znikają - dostają "Nie" w kolumnie
"W ostatnim wyszukiwaniu" (zamknięte, zmienione albo odfiltrowane).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from html import escape
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from collectors.base import JobOffer
from collectors.parsing import normalize_title

STATUS_NEW = "Nowa"
STATUSES = (STATUS_NEW, "Obejrzana", "CV wysłane", "Rozmowa", "Odrzucona", "Nie interesuje mnie")
# Statusy "załatwione" - wyszarzone w Excelu, zwinięte w HTML.
DONE_STATUSES = ("CV wysłane", "Rozmowa", "Odrzucona", "Nie interesuje mnie")
STATUS_ORDER = {status: index for index, status in enumerate(STATUSES)}

USER_COLUMNS = ("Status",)
# Kolumna "Link" musi zostać (po niej rozpoznajemy oferty między uruchomieniami),
# ale jest ukryta - link jest na tytule w kolumnie "Stanowisko".
HIDDEN_COLUMNS = ("Link",)
COLUMNS = (
    "Status",
    "Priorytet",
    "Firma",
    "Stanowisko",
    "Lokalizacja",
    "Model pracy",
    "Umowa",
    "Wynagrodzenie",
    "Ocena",
    "Dlaczego pasuje",
    "Ocena wynagrodzenia",
    "Źródło",
    "Pierwsze wykrycie",
    "Ostatnio widziana",
    "W ostatnim wyszukiwaniu",
    "Link",
)
WIDTHS = {
    "Status": 16, "Priorytet": 18, "Firma": 24, "Stanowisko": 40, "Lokalizacja": 22,
    "Model pracy": 13, "Umowa": 18, "Wynagrodzenie": 24, "Ocena": 8, "Dlaczego pasuje": 36,
    "Ocena wynagrodzenia": 30, "Źródło": 18, "Pierwsze wykrycie": 13, "Ostatnio widziana": 13,
    "W ostatnim wyszukiwaniu": 12, "Link": 60,
}


@dataclass(slots=True)
class ExportResult:
    excel_path: Path
    html_path: Path
    new_rows: list[dict[str, str]] = field(default_factory=list)
    active_rows: int = 0
    warnings: list[str] = field(default_factory=list)
    sheet_url: str = ""


def export(
    offers: list[JobOffer],
    reports_dir: Path | str = "reports",
    basename: str = "report",
    title: str = "Raport ofert QA",
    sheet_tab: str = "",
    scope: set[str] | None = None,
) -> ExportResult:
    """Scala bieżące oferty z poprzednią listą i zapisuje arkusz, Excel i HTML.

    ``scope`` - nazwy firm sprawdzonych w tym przebiegu (None = wszystkie).
    Oferty firm spoza zakresu (np. przy ``--company Sii``) zachowują
    poprzednie "W ostatnim wyszukiwaniu", zamiast dostać "Nie".
    """

    output_dir = Path(reports_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    excel_path = output_dir / f"{basename}.xlsx"
    html_path = output_dir / f"{basename}.html"
    today = date.today().isoformat()
    warnings: list[str] = []

    store, previous = None, None
    if sheet_tab:
        store, error = _sheet_store()
        if error:
            warnings.append(error)
        if store is not None:
            try:
                previous = store.read_rows(sheet_tab)
            except Exception as error:  # noqa: BLE001 - awaria Google nie może zatrzymać raportu
                # Bez odczytu nie zapisujemy - nadpisalibyśmy statusy ustawione w arkuszu.
                warnings.append(f"Arkusze Google: nie udało się odczytać zakładki {sheet_tab} ({error}); "
                                "arkusz nie został zaktualizowany, zapisano tylko lokalny Excel.")
                store = None
    if previous is None:
        previous = _read_previous(excel_path)
    rows, new_rows = _merge(previous, [_to_row(offer) for offer in offers], today, scope)

    try:
        _write_excel(rows, excel_path)
    except PermissionError:
        # Plik jest otwarty w Excelu - nie tracimy wyników, zapisujemy kopię.
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        fallback = output_dir / f"{basename} (kopia {stamp}).xlsx"
        _write_excel(rows, fallback)
        if store is None:
            warnings.append(
                f"{excel_path} jest otwarty w Excelu - zapisano kopię {fallback.name}. "
                "Zamknij plik przed kolejnym uruchomieniem; statusy wpisane w kopii nie zostaną przeniesione."
            )
        excel_path = fallback

    sheet_url = ""
    if store is not None:
        try:
            store.write_rows(sheet_tab, COLUMNS, rows, STATUSES, DONE_STATUSES, STATUS_NEW,
                             user_columns=USER_COLUMNS, hidden_columns=HIDDEN_COLUMNS)
            sheet_url = store.settings.url
        except Exception as error:  # noqa: BLE001 - lokalny Excel jest już zapisany
            warnings.append(f"Arkusze Google: nie udało się zapisać zakładki {sheet_tab} ({error}).")
    _write_html(rows, html_path, title, today, sheet_url)
    active = sum(1 for row in rows if row["W ostatnim wyszukiwaniu"] == "Tak")
    return ExportResult(excel_path, html_path, new_rows, active, warnings, sheet_url)


_STORE_CACHE: dict[str, object] = {}


def _sheet_store():
    """(SheetStore albo None, komunikat błędu). Połączenie jest współdzielone między raportami."""

    if "store" in _STORE_CACHE:
        return _STORE_CACHE["store"], ""
    import sheets

    settings = sheets.load_settings()
    if settings is None:
        return None, ""
    try:
        store = sheets.SheetStore(settings)
    except Exception as error:  # noqa: BLE001
        return None, (f"Arkusze Google niedostępne ({type(error).__name__}: {error}); "
                      "statusy odczytano i zapisano tylko w lokalnym Excelu.")
    _STORE_CACHE["store"] = store
    return store, ""


def _to_row(offer: JobOffer) -> dict[str, str]:
    priority = "🟢 Aplikuj" if offer.match_score >= 12 else "🟡 Warto rozważyć"
    reasons = ", ".join(offer.match_reasons) or "Dopasowane stanowisko QA"
    score_on_ten = max(1, min(10, round(offer.match_score / 2)))
    return {
        "Priorytet": priority,
        "Firma": offer.company,
        "Stanowisko": offer.title,
        "Lokalizacja": offer.location,
        "Model pracy": offer.work_mode,
        "Umowa": ", ".join(offer.contract_types) or "Nie podano",
        "Wynagrodzenie": offer.salary or "Nie podano",
        "Ocena": f"{score_on_ten}/10",
        "Dlaczego pasuje": reasons,
        "Ocena wynagrodzenia": offer.salary_assessment,
        "Źródło": offer.source,
        "Link": offer.url,
    }


# --- Scalanie z poprzednim raportem ------------------------------------------

def _key(row: dict[str, str]) -> tuple[str, str]:
    return (str(row.get("Firma", "")).casefold().strip(), normalize_title(str(row.get("Stanowisko", ""))))


def _read_previous(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        sheet = load_workbook(path, read_only=True).active
    except Exception:  # noqa: BLE001 - uszkodzony plik nie może zablokować raportu
        return []
    rows = sheet.iter_rows(values_only=True)
    header = [str(value or "") for value in next(rows, ())]
    if "Link" not in header:
        return []
    previous = []
    for values in rows:
        row = {column: ("" if value is None else str(value)) for column, value in zip(header, values)}
        if row.get("Link"):
            previous.append(row)
    return previous


def _merge(
    previous: list[dict[str, str]],
    current: list[dict[str, str]],
    today: str,
    scope: set[str] | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Zwraca (wszystkie wiersze, oferty nowe w tym przebiegu)."""

    by_url = {row["Link"]: row for row in previous}
    by_key = {_key(row): row for row in previous}
    matched: set[int] = set()
    rows: list[dict[str, str]] = []
    new_rows: list[dict[str, str]] = []

    for row in current:
        # Link bywa zmieniany przez portal; firma + tytuł to klucz zapasowy.
        old = by_url.get(row["Link"]) or by_key.get(_key(row))
        if old is not None and id(old) not in matched:
            matched.add(id(old))
            row["Status"] = old.get("Status") or STATUS_NEW
            row["Pierwsze wykrycie"] = old.get("Pierwsze wykrycie") or today
        else:
            row["Status"] = STATUS_NEW
            row["Pierwsze wykrycie"] = today
            new_rows.append(row)
        row["Ostatnio widziana"] = today
        row["W ostatnim wyszukiwaniu"] = "Tak"
        rows.append(row)

    for old in previous:
        if id(old) in matched:
            continue
        old = {column: old.get(column, "") for column in COLUMNS}
        in_scope = scope is None or old.get("Firma", "").casefold() in {name.casefold() for name in scope}
        if in_scope or not old["W ostatnim wyszukiwaniu"]:
            old["W ostatnim wyszukiwaniu"] = "Nie"
        rows.append(old)

    # Najpierw najnowsze wykrycia, potem (sortowanie stabilne) aktywne i
    # niezałatwione na górze.
    rows.sort(key=lambda row: row.get("Pierwsze wykrycie", ""), reverse=True)
    rows.sort(
        key=lambda row: (
            row["W ostatnim wyszukiwaniu"] != "Tak",
            row.get("Status") in DONE_STATUSES,
            STATUS_ORDER.get(row.get("Status", ""), len(STATUSES)),
        )
    )
    return rows, new_rows


# --- Excel -------------------------------------------------------------------

def _write_excel(rows: list[dict[str, str]], path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Oferty"
    sheet.append(list(COLUMNS))
    for row in rows:
        sheet.append([row.get(column, "") for column in COLUMNS])

    sheet.freeze_panes = "B2"
    sheet.auto_filter.ref = sheet.dimensions
    header_fill = PatternFill("solid", fgColor="1F4E78")
    user_fill = PatternFill("solid", fgColor="C55A11")
    for index, cell in enumerate(sheet[1], start=1):
        cell.fill = user_fill if COLUMNS[index - 1] in USER_COLUMNS else header_fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    for index, column in enumerate(COLUMNS, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = WIDTHS[column]

    link_column = COLUMNS.index("Link") + 1
    title_column = COLUMNS.index("Stanowisko") + 1
    for row_index in range(2, sheet.max_row + 1):
        url = sheet.cell(row=row_index, column=link_column).value
        title = sheet.cell(row=row_index, column=title_column)
        if url:
            title.hyperlink = url
            title.style = "Hyperlink"
        for cell in sheet[row_index]:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    for column in HIDDEN_COLUMNS:
        sheet.column_dimensions[get_column_letter(COLUMNS.index(column) + 1)].hidden = True

    # Lista rozwijana statusów - również dla kilkuset pustych wierszy poniżej.
    status_letter = get_column_letter(COLUMNS.index("Status") + 1)
    last_row = sheet.max_row + 500
    validation = DataValidation(type="list", formula1=f'"{",".join(STATUSES)}"', allow_blank=True)
    validation.error = "Wybierz status z listy."
    validation.prompt = "Zmień status - zostanie zachowany przy kolejnym uruchomieniu."
    sheet.add_data_validation(validation)
    validation.add(f"{status_letter}2:{status_letter}{last_row}")

    # Formatowanie warunkowe działa na bieżąco - po zmianie statusu wiersz od razu szarzeje.
    full_range = f"A2:{get_column_letter(len(COLUMNS))}{last_row}"
    active_letter = get_column_letter(COLUMNS.index("W ostatnim wyszukiwaniu") + 1)
    done_formula = " , ".join(f'${status_letter}2="{status}"' for status in DONE_STATUSES)
    sheet.conditional_formatting.add(
        full_range,
        FormulaRule(formula=[f'${active_letter}2="Nie"'], font=Font(color="A6A6A6", strike=True), stopIfTrue=True),
    )
    sheet.conditional_formatting.add(
        full_range,
        FormulaRule(formula=[f"OR({done_formula})"], font=Font(color="808080"),
                    fill=PatternFill("solid", fgColor="EDEDED"), stopIfTrue=True),
    )
    sheet.conditional_formatting.add(
        full_range,
        FormulaRule(formula=[f'${status_letter}2="{STATUS_NEW}"'], fill=PatternFill("solid", fgColor="E2EFDA")),
    )
    workbook.save(path)


# --- HTML --------------------------------------------------------------------

HTML_COLUMNS = ("Status", "Priorytet", "Firma", "Stanowisko", "Lokalizacja", "Model pracy", "Umowa",
                "Wynagrodzenie", "Ocena", "Dlaczego pasuje", "Pierwsze wykrycie")


def _write_html(rows: list[dict[str, str]], html_path: Path, title: str, today: str, sheet_url: str = "") -> None:
    active = [row for row in rows if row["W ostatnim wyszukiwaniu"] == "Tak" and row["Status"] not in DONE_STATUSES]
    done = [row for row in rows if row["W ostatnim wyszukiwaniu"] == "Tak" and row["Status"] in DONE_STATUSES]
    gone = [row for row in rows if row["W ostatnim wyszukiwaniu"] != "Tak"]
    new_count = sum(1 for row in active if row["Pierwsze wykrycie"] == today)
    status_hint = (
        f'Statusy zmieniasz w <a href="{escape(sheet_url, quote=True)}">Arkuszu Google</a>'
        if sheet_url else "Statusy zmieniasz w pliku Excel obok"
    ) + " - ten widok odświeży się przy kolejnym uruchomieniu."

    sections = [_html_table(active, today, "Brak nowych ani obejrzanych ofert spełniających kryteria.")]
    if done:
        sections.append(f"<details><summary>Załatwione ({len(done)})</summary>{_html_table(done, today)}</details>")
    if gone:
        sections.append(
            f"<details><summary>Nie ma ich w ostatnim wyszukiwaniu ({len(gone)})</summary>{_html_table(gone, today)}</details>"
        )

    html_path.write_text(
        f"""<!doctype html>
<html lang="pl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 2rem; color: #172033; }}
    h1 {{ margin-bottom: .25rem; }}
    table {{ border-collapse: collapse; width: 100%; font-size: .9rem; margin-bottom: 1.5rem; }}
    th {{ background: #1f4e78; color: white; text-align: left; position: sticky; top: 0; }}
    th, td {{ border: 1px solid #d7dee9; padding: .6rem; vertical-align: top; }}
    tr:nth-child(even) {{ background: #f7f9fc; }}
    tr.new td:first-child {{ background: #e2efda; font-weight: 600; }}
    details {{ margin-top: 1rem; }} summary {{ cursor: pointer; font-weight: 600; margin-bottom: .5rem; }}
    details td {{ color: #707070; }}
    a {{ color: #0b63ce; font-weight: 600; }}
  </style>
</head>
<body>
  <h1>{escape(title)}</h1>
  <p>Do przejrzenia: {len(active)} (nowe dziś: {new_count}). Każdy link został sprawdzony przed dodaniem do raportu.
  {status_hint}</p>
  {"".join(sections)}
</body>
</html>
""",
        encoding="utf-8",
    )


def _html_table(rows: list[dict[str, str]], today: str, empty: str = "") -> str:
    header = "".join(f"<th>{escape(column)}</th>" for column in HTML_COLUMNS)
    if not rows:
        return f'<table><thead><tr>{header}</tr></thead><tbody><tr><td colspan="{len(HTML_COLUMNS)}">{escape(empty)}</td></tr></tbody></table>'
    body = []
    for row in rows:
        cells = []
        for column in HTML_COLUMNS:
            value = str(row.get(column, ""))
            if column == "Stanowisko" and row.get("Link"):
                link = escape(str(row["Link"]), quote=True)
                cells.append(f'<td><a href="{link}" target="_blank" rel="noopener">{escape(value)}</a></td>')
            else:
                cells.append(f"<td>{escape(value)}</td>")
        css = ' class="new"' if row.get("Pierwsze wykrycie") == today and row.get("Status") == STATUS_NEW else ""
        body.append(f"<tr{css}>{''.join(cells)}</tr>")
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(body)}</tbody></table>"
