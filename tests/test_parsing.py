"""Wspólne parsery: słowa kluczowe, wynagrodzenia, JSON-LD."""

import pytest

from collectors.parsing import (
    contains_keyword,
    extract_salary,
    fold_text,
    json_ld_location,
    json_ld_salary,
    json_ld_work_mode,
    normalize_title,
    parse_json_ld_jobs,
)


@pytest.mark.parametrize(
    ("text", "keyword", "expected"),
    [
        ("Software Tester", "tester", True),
        ("Testerka oprogramowania", "tester", True),
        ("Senior Pentester", "tester", False),  # słowo kluczowe od początku wyrazu
        ("QA Engineer", "qa", True),
        ("QA/Test Coordinator", "qa", True),
        ("Aquarium manager", "qa", False),  # krótkie słowa tylko jako całe słowo
        ("Q&A session", "qa", False),
        ("Chapter Leader Testów Manualnych", "manual", True),
        ("Specjalista ds. testów", "testów", True),
        ("Specjalista ds. testow", "testów", True),  # bez polskich znaków
    ],
)
def test_contains_keyword(text, keyword, expected):
    assert contains_keyword(text, (keyword,)) is expected


def test_fold_text_removes_polish_characters():
    assert fold_text("Wrocław ŁÓDŹ") == "wroclaw lodz"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Regresja: "PLN hybrid" było czytane jako stawka godzinowa.
        ("15 000 - 20 000 PLN hybrid", "15 000 - 20 000 PLN"),
        ("120-150 PLN/h netto", "120-150 PLN /h"),
        ("Wynagrodzenie: 6 500,00 zł brutto", "6 500,00 PLN brutto"),
        ("od 7000 do 9000 zł miesięcznie", "7000 do 9000 PLN /month"),
        ("25 000 - 30 000 PLN/month", "25 000 - 30 000 PLN /month"),
        ("100 000 PLN rocznie", "100 000 PLN /year"),
        ("brak widełek", ""),
    ],
)
def test_extract_salary(text, expected):
    assert extract_salary(text) == expected


def test_normalize_title_drops_brackets_and_punctuation():
    assert normalize_title("Manual Tester (f/m/x) [Remote]") == "manual tester"


JSON_LD_PAGE = """
<html><head><script type="application/ld+json">
{"@context": "https://schema.org", "@graph": [
  {"@type": "Organization", "name": "Firma"},
  {"@type": "JobPosting", "title": "Manual Tester",
   "jobLocation": {"@type": "Place", "address": {"addressLocality": "Wrocław", "addressCountry": "PL"}},
   "jobLocationType": "TELECOMMUTE",
   "baseSalary": {"currency": "PLN", "value": {"minValue": 8000, "maxValue": 11000, "unitText": "MONTH"}}}
]}
</script></head></html>
"""


def test_json_ld_job_posting():
    postings = parse_json_ld_jobs(JSON_LD_PAGE)
    assert len(postings) == 1
    posting = postings[0]
    assert json_ld_location(posting) == "Wrocław, PL"
    assert json_ld_work_mode(posting) == "Remote"
    assert json_ld_salary(posting) == "8000 - 11000 PLN /month"


def test_mobile_apps_are_not_mobile_work_mode():
    from collectors.parsing import normalize_work_mode

    assert normalize_work_mode("Młodszy Tester Automatyzujący – aplikacje mobilne") == "Nie podano"
    assert normalize_work_mode("Praca mobilna, Wrocław") == "Mobile"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Regresja (Asseco): hybryda z dniami zdalnymi to nie praca zdalna.
        ("Praca w modelu hybrydowym (3 dni stacjonarnie, 2 dni zdalnie) w biurze w Gdyni", "Hybrid"),
        ("Hybrid work, 2 days remote per week", "Hybrid"),
        ("100% remote, hybrid optional in Warsaw", "Remote"),
        ("Praca zdalna", "Remote"),
        ("Praca stacjonarna w biurze", "Office"),
    ],
)
def test_normalize_work_mode(text, expected):
    from collectors.parsing import normalize_work_mode

    assert normalize_work_mode(text) == expected
