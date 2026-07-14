"""Eksport zweryfikowanych ofert do czytelnego HTML i Excela."""

from __future__ import annotations

from html import escape
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

from collectors.base import JobOffer


REPORTS_DIR = Path("reports")
EXCEL_PATH = REPORTS_DIR / "report.xlsx"
HTML_PATH = REPORTS_DIR / "report.html"


def export(offers: list[JobOffer]) -> tuple[Path, Path]:
    """Tworzy dwa raporty z działającymi, bezpośrednimi linkami."""

    REPORTS_DIR.mkdir(exist_ok=True)
    rows = [_to_row(offer) for offer in offers]
    columns = [
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
        "Link",
    ]
    dataframe = pd.DataFrame(rows, columns=columns)
    dataframe.to_excel(EXCEL_PATH, index=False)
    _format_excel(EXCEL_PATH)
    _write_html(rows, columns)
    return EXCEL_PATH, HTML_PATH


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


def _format_excel(path: Path) -> None:
    workbook = load_workbook(path)
    sheet = workbook.active
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions

    header_fill = PatternFill("solid", fgColor="1F4E78")
    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(wrap_text=True, vertical="top")

    widths = (18, 24, 34, 24, 16, 20, 28, 12, 42, 34, 16, 65)
    for column, width in enumerate(widths, start=1):
        sheet.column_dimensions[chr(64 + column)].width = width

    link_column = 12
    for row in range(2, sheet.max_row + 1):
        sheet.cell(row=row, column=link_column).hyperlink = sheet.cell(row=row, column=link_column).value
        sheet.cell(row=row, column=link_column).style = "Hyperlink"
        for cell in sheet[row]:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    workbook.save(path)


def _write_html(rows: list[dict[str, str]], columns: list[str]) -> None:
    header = "".join(f"<th>{escape(column)}</th>" for column in columns)
    if rows:
        table_rows = []
        for row in rows:
            cells = []
            for column in columns:
                value = row[column]
                if column == "Link":
                    cells.append(f'<td><a href="{escape(value, quote=True)}" target="_blank" rel="noopener">Otwórz ofertę</a></td>')
                else:
                    cells.append(f"<td>{escape(value)}</td>")
            table_rows.append("<tr>" + "".join(cells) + "</tr>")
        body = "\n".join(table_rows)
        summary = f"Zweryfikowane oferty: {len(rows)}"
    else:
        body = '<tr><td colspan="12">Brak ofert spełniających ustawione kryteria.</td></tr>'
        summary = "Brak zweryfikowanych ofert"

    HTML_PATH.write_text(
        f"""<!doctype html>
<html lang="pl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Raport ofert QA</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 2rem; color: #172033; }}
    h1 {{ margin-bottom: .25rem; }}
    table {{ border-collapse: collapse; width: 100%; font-size: .9rem; }}
    th {{ background: #1f4e78; color: white; text-align: left; position: sticky; top: 0; }}
    th, td {{ border: 1px solid #d7dee9; padding: .65rem; vertical-align: top; }}
    tr:nth-child(even) {{ background: #f7f9fc; }}
    a {{ color: #0b63ce; font-weight: 600; }}
  </style>
</head>
<body>
  <h1>Raport ofert QA</h1>
  <p>{escape(summary)}. Każdy link został sprawdzony przed dodaniem do raportu.</p>
  <table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>
</body>
</html>
""",
        encoding="utf-8",
    )
