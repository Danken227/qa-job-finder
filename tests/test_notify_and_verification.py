"""Treść maila i dopasowanie tytułów przy weryfikacji linków."""

from pathlib import Path

import notify
from pipeline import ReportResult
from verification import _titles_match, page_description


def settings(attach=True):
    return notify.NotifySettings(sender="a@example.com", recipients=("b@example.com",), attach_reports=attach)


def test_message_has_sheet_link_new_offers_and_problems(tmp_path):
    excel = tmp_path / "portals_report.xlsx"
    excel.write_bytes(b"xlsx")
    result = ReportResult(
        "Portale", 100, 20, excel, Path("x.html"),
        new_rows=[{"Firma": "Sii", "Stanowisko": "Manual Tester", "Lokalizacja": "Wrocław",
                   "Model pracy": "Hybrid", "Link": "https://sii.pl/1"}],
        active=20, problems=["RocketJobs: 0 ofert - możliwa zmiana strony portalu"],
        sheet_url="https://docs.google.com/spreadsheets/d/X",
    )
    message = notify.build_message(settings(), [result], errors=[])
    text = message.get_body(("plain",)).get_content()
    assert "1 nowych ofert" in message["Subject"]
    assert "https://docs.google.com/spreadsheets/d/X" in text
    assert "Sii – Manual Tester" in text and "https://sii.pl/1" in text
    assert "Problemy ze źródłami" in text and "RocketJobs" in text
    assert [part.get_filename() for part in message.iter_attachments()] == ["portals_report.xlsx"]
    assert list(notify.build_message(settings(attach=False), [result], []).iter_attachments()) == []


def test_titles_match():
    assert _titles_match("Manual Tester (f/m/x)", "Manual Tester – Sii Polska")
    assert _titles_match("QA Engineer Wrocław", "QA Engineer")
    assert not _titles_match("Manual Tester", "Java Developer")


def test_page_description_prefers_json_ld():
    words = " ".join(["testy manualne"] * 60)
    html = ('<html><body><nav>menu remote</nav><script type="application/ld+json">'
            '{"@type": "JobPosting", "title": "Tester", "description": "<p>' + words + '</p>"}'
            "</script><main>inna treść</main></body></html>")
    assert page_description(html).startswith("testy manualne")


def test_page_description_ignores_js_shell_without_offer_title():
    # Regresja (Asseco): pusta ramka strony tylko-JS z filtrem "Praca zdalna" w menu.
    shell = "<html><body><main>Oferty pracy Filtry: Praca zdalna Praca hybrydowa Lokalizacja</main></body></html>"
    assert page_description(shell, "Specjalista ds. Testów") == ""
    offer_page = "<html><body><main>Specjalista ds. Testów Gdańsk, praca hybrydowa. Wymagania: SQL</main></body></html>"
    assert "Gdańsk" in page_description(offer_page, "Specjalista ds. Testów")
