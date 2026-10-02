"""Filtry profilu (profil testowy: Wrocław, remote, UoP >= 9000, B2B >= 80 zł/h)."""

from filter import (
    _assess_salary,
    deduplicate_offers,
    filter_offers_with_diagnostics,
    is_preferred_city,
)


def test_preferred_city_ignores_polish_characters_and_uses_aliases():
    assert is_preferred_city("Wroclaw, Poland")
    assert is_preferred_city("POL - DS - WROCLAW")
    assert is_preferred_city("Breslau")  # alias z profilu testowego
    assert not is_preferred_city("Warszawa")


def test_location_filter(make_offer):
    offers = [
        make_offer(title="Manual Tester", location="Wrocław", work_mode="Office", url="https://x/1"),
        make_offer(title="QA Tester", location="Gdańsk", work_mode="Remote", url="https://x/2"),
        make_offer(title="Tester", location="Warszawa", work_mode="Hybrid", url="https://x/3"),
    ]
    result = filter_offers_with_diagnostics(offers)
    assert {offer.url for offer in result.offers} == {"https://x/1", "https://x/2"}
    assert result.rejected_location == 1


def test_title_seniority_and_automation_filters(make_offer):
    offers = [
        make_offer(title="QA Automation Engineer", url="https://x/1"),
        make_offer(title="QA Lead", url="https://x/2"),
        make_offer(title="Senior Pentester", url="https://x/3"),
        make_offer(title="Manual Tester", url="https://x/4"),
    ]
    result = filter_offers_with_diagnostics(offers)
    assert [offer.url for offer in result.offers] == ["https://x/4"]
    assert (result.rejected_automation, result.rejected_seniority, result.rejected_title) == (1, 1, 1)


def test_foreign_language_in_title_is_rejected(make_offer):
    result = filter_offers_with_diagnostics([make_offer(title="Manual Tester with German")])
    assert result.offers == []
    assert result.rejected_language == 1


def test_public_sector_keywords_extend_profile(make_offer):
    offer = make_offer(title="Główny specjalista – testowania oprogramowania")
    assert filter_offers_with_diagnostics([offer]).offers == []
    assert len(filter_offers_with_diagnostics([offer], title_keywords=("testowania",)).offers) == 1


def test_salary_assessment(make_offer):
    ok, _ = _assess_salary(make_offer(salary="120 PLN /h", contract_types=("B2B",)))
    too_low, _ = _assess_salary(make_offer(salary="60 PLN /h", contract_types=("B2B",)))
    uop_low, _ = _assess_salary(make_offer(salary="5000 - 7000 PLN", contract_types=("Permanent",)))
    unknown, note = _assess_salary(make_offer(salary=""))
    assert ok and not too_low and not uop_low and unknown
    assert "Brak widełek" in note


def test_deduplicate_prefers_allowed_location(make_offer):
    szczecin = make_offer(title="Manual Tester", location="Szczecin", work_mode="Office", url="https://x/1")
    wroclaw = make_offer(title="Manual Tester", location="Wrocław", work_mode="Office", url="https://x/2")
    assert [offer.url for offer in deduplicate_offers([szczecin, wroclaw])] == ["https://x/2"]
