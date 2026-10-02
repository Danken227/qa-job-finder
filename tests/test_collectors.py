"""Collectory bez sieci: rozpoznawanie ATS, Pracuj.pl, RocketJobs, strony błędu."""

import pytest
from bs4 import BeautifulSoup

from collectors.ats import board_from_url, find_boards_in_html, in_target_country
from collectors.careers import _soft_404
from collectors.pracuj import _salary, _to_offer
from collectors.rocketjobs import RocketJobsCollector
from sheets import _column_letter


@pytest.mark.parametrize(
    ("url", "kind", "key"),
    [
        ("https://job-boards.greenhouse.io/xebiacee", "greenhouse", "xebiacee"),
        ("https://jobs.lever.co/text", "lever", "text"),
        ("https://careers.smartrecruiters.com/BoschGroup/poland", "smartrecruiters", "BoschGroup"),
        ("https://apply.workable.com/netguru/", "workable", "netguru"),
        ("https://erstebp.wd502.myworkdayjobs.com/pl-PL/Kariera", "workday", "erstebp.wd502.myworkdayjobs.com/Kariera"),
        ("https://jobs.ashbyhq.com/brainly", "ashby", "brainly"),
        ("https://sente.traffit.com/public/", "traffit", "sente"),
        ("https://skk.erecruiter.pl/Offer.aspx?oid=1&cfg=697E3176B32B4E9EB323BA63AC01E236", "erecruiter",
         "697e3176b32b4e9eb323ba63ac01e236"),
    ],
)
def test_board_from_url(url, kind, key):
    board = board_from_url(url)
    assert (board.type, board.key) == (kind, key)


def test_board_from_url_ignores_login_and_assets():
    assert board_from_url("https://dxctechnology.wd1.myworkdayjobs.com/wday/cxs/x") is None


def test_find_boards_in_html_detects_escaped_and_hosted_platforms():
    html = ('<a href="https:\\/\\/apply.workable.com\\/monterail\\/j\\/1">x</a>'
            '<link href="https://assets.teamtailor-cdn.com/x.css"> powered by teamtailor')
    found = {board.label for board in find_boards_in_html(html, "https://jobs.firma.com/jobs")}
    assert found == {"workable:monterail", "teamtailor:jobs.firma.com"}


@pytest.mark.parametrize(
    ("location", "expected"),
    [("Kraków, Poland", True), ("Wrocław", True), ("Warszawa, Polska", True), ("", True), ("Gdynia", True),
     ("Bangalore, India", False), ("Remote - EMEA", True), ("Remote, USA", False)],
)
def test_in_target_country(location, expected):
    assert in_target_country(location) is expected


class FakeResponse:
    def __init__(self, url, text="<html><title>Kariera</title></html>"):
        self.url, self.text = url, text


@pytest.mark.parametrize(
    ("requested", "final", "problem"),
    [
        ("https://www.gov.pl/web/finanse/praca", "https://www.gov.pl/", True),
        ("https://www.dpd.com/pl/pl/kariera/", "https://www.dpd.com/pl/pl/strona-nie-znaleziona/", True),
        # Przekierowanie na osobną domenę kariery jest w porządku.
        ("https://www.pekao.com.pl/kariera.html", "https://karieranabank.pl/", False),
        ("https://firma.pl/kariera", "https://firma.pl/kariera/", False),
    ],
)
def test_soft_404(requested, final, problem):
    assert bool(_soft_404(requested, FakeResponse(final))) is problem


def test_pracuj_salary_keeps_hourly_unit():
    # Regresja ryzyka: "130–160 zł netto (+ VAT) / godz." nie może być widełkami miesięcznymi.
    assert _salary("130–160 zł netto (+ VAT) / godz.") == "130 - 160 PLN netto /h"
    assert _salary("12 000–15 000 zł brutto / mies.") == "12 000 - 15 000 PLN brutto /month"
    assert _salary("") == ""


def test_pracuj_offer_prefers_preferred_city_variant():
    offer = _to_offer({
        "jobTitle": "Tester Manualny",
        "companyName": "Firma",
        "offers": [
            {"displayWorkplace": "Warszawa", "offerAbsoluteUri": "https://www.pracuj.pl/praca/a,oferta,1"},
            {"displayWorkplace": "Wrocław", "offerAbsoluteUri": "https://www.pracuj.pl/praca/b,oferta,2"},
        ],
        "workModes": ["Praca hybrydowa", "Praca zdalna"],
        "typesOfContract": ["Umowa o pracę"],
        "salaryDisplayText": "8 000–10 000 zł brutto / mies.",
    })
    assert offer.url.endswith(",oferta,2")
    assert offer.work_mode == "Remote" and offer.contract_types == ("Permanent",)
    assert offer.location == "Warszawa; Wrocław"


ROCKET_CARD = """
<div><a class="offer-card" href="https://rocketjobs.pl/oferta-pracy/firma-qa" title="Zobacz ofertę QA Engineer"></a>
<div><object><img alt="CGI"></object>
  <div><div><svg class="lucide lucide-building"></svg></div><p>CGI</p></div>
  <div><div><svg class="lucide lucide-map-pin"></svg></div><p>Wrocław</p></div>
  <div><div><svg class="lucide lucide-building-2"></svg></div><p>Hybrydowo</p></div>
  <h3>Quality Assurance Engineer</h3>
</div></div>
"""


def test_rocketjobs_card_fields_by_icon():
    link = BeautifulSoup(ROCKET_CARD, "lxml").select_one("a.offer-card")
    offer = RocketJobsCollector._parse_card(link)
    assert (offer.company, offer.title, offer.location, offer.work_mode) == (
        "CGI", "Quality Assurance Engineer", "Wrocław", "Hybrid")


def test_column_letter():
    assert [_column_letter(n) for n in (1, 16, 26, 27)] == ["A", "P", "Z", "AA"]


def test_new_platforms_are_recognised():
    oracle = board_from_url("https://fa-evmr-saasfaprod1.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1")
    assert (oracle.type, oracle.params) == ("oracle_hcm", {"host": "fa-evmr-saasfaprod1.fa.ocs.oraclecloud.com",
                                                           "site": "CX_1"})
    assert board_from_url("https://careers.epam.com", "epam").type == "epam"
    assert board_from_url("https://www.capgemini.com/pl-pl/kariera/", "capgemini").type == "capgemini"


ASSECO_CARD = """
<a class="glowny-aplikuj" href="/Oferta/2a96a60c">
  <style>.Lokalizacja-element { min-width: 0; }</style>
  <div class="Branza-element"><span>Analiza</span> | <span>Testowanie</span></div>
  <div class="RekrutacjaNazwa-element">Tester Systemowy/Analityk</div>
  <div class="Lokalizacja-element"><span>Wrocław</span></div>
  <div class="box-aplikuj">Aplikuj</div>
</a>
"""


def test_card_title_from_title_class_without_css_and_apply_button():
    from collectors.careers import _anchor_title

    anchor = BeautifulSoup(ASSECO_CARD, "lxml").select_one("a")
    assert _anchor_title(anchor) == "Tester Systemowy/Analityk"


def test_extract_cities_and_location_from_card():
    from collectors.careers import _extract_location
    from collectors.parsing import extract_cities

    assert extract_cities("Praca: Gdańsk, Gdynia, Sopot") == ["Gdańsk", "Gdynia", "Sopot"]
    assert extract_cities("Lublin") == ["Lublin"]  # nie Lubin
    # Regresja (Asseco): miasto spoza profilu było zamieniane na "Nie podano".
    assert _extract_location("Testowanie Specjalista ds. Testów (m./k./os.) Gdynia Aplikuj teraz") == "Gdynia"
    assert _extract_location("Gdańsk, Wroclaw") == "Wrocław; Gdańsk"
    assert _extract_location("Praca zdalna") == "Nie podano"
