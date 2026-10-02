"""Analiza opisu: języki obce i udział testów manualnych."""

import pytest

from analysis import required_foreign_languages, work_profile
from pipeline import analyse_descriptions


@pytest.mark.parametrize(
    ("title", "description", "expected"),
    [
        ("Intern Manual Tester (with German)", "", ["niemiecki"]),
        ("Manual Tester", "Wymagana bardzo dobra znajomość języka niemieckiego w mowie i piśmie.", ["niemiecki"]),
        ("QA", "Requirements: German language at B2 level, English C1", ["niemiecki"]),
        ("Tester", "Fluent Czech and English required", ["czeski"]),
        ("QA Engineer", "Znajomość języka niemieckiego mile widziana. English B2.", []),
        # Nazwa kraju bez kontekstu językowego w tym samym zdaniu nie wyklucza.
        ("QA Engineer", "You will test software for the German market. Fluent English required.", []),
        ("QA", "Our clients: German and Swiss banks. Language: English", []),
        ("Tester oprogramowania", "Język angielski B2", []),
        # Ogłoszenie napisane po niemiecku - bez słowa "German".
        ("Tester, remote und Hannover oder Münster", "", ["niemiecki"]),
        ("Softwaretester (m/w/d)", "Wir suchen einen Tester mit Erfahrung in der Qualitätssicherung. "
                                   "Du arbeitest im Team und bist für die Testfälle zuständig. " * 4, ["niemiecki"]),
        # Zwykły angielski i polski opis nie są ogłoszeniem w obcym języku.
        ("QA Engineer", "We are looking for a QA engineer to test our web and mobile apps. "
                        "You will design test cases and report bugs in Jira. " * 4, []),
        ("Tester oprogramowania", "Szukamy testera do zespołu. Będziesz tworzyć przypadki testowe "
                                  "i zgłaszać błędy w Jira. " * 4, []),
        # Przełącznik języka strony z nagłówka (fałszywy alarm na stronie Eviden).
        ("Tester with Tosca", "Skip to main content Language English (United States) Français (France) "
                              "Sign in. Requirements: Tosca, English B2.", []),
    ],
)
def test_required_foreign_languages(title, description, expected):
    assert required_foreign_languages(title, description) == expected


def test_work_profile_manual_offer():
    profile = work_profile(
        "Manual QA Tester",
        "Tworzenie przypadków testowych, testy eksploracyjne, raportowanie błędów w Jira, TestRail.",
    )
    assert profile.manual_share == 100
    assert not profile.is_automation_first
    assert profile.summary.startswith("100% manual")


def test_work_profile_automation_offer():
    profile = work_profile(
        "QA Engineer",
        "Test automation in Java with Selenium and TestNG, CI/CD with Jenkins, REST Assured, Cypress.",
    )
    assert profile.manual_share is not None and profile.manual_share < 25
    assert profile.is_automation_first


def test_work_profile_without_signals():
    profile = work_profile("Specjalista", "")
    assert profile.manual_share is None
    assert profile.summary == "brak danych w opisie"


def test_analyse_descriptions_filters_and_scores(make_offer):
    offers = [
        make_offer(title="Manual Tester", url="https://x/1", match_score=10,
                   description="Przypadki testowe, testy eksploracyjne, Jira."),
        make_offer(title="QA Engineer", url="https://x/2", match_score=10,
                   description="Required: fluent German language skills."),
        make_offer(title="QA Engineer", url="https://x/3", match_score=10,
                   description="Automation framework in Java, Selenium, Cypress, TestNG, Jenkins CI/CD."),
    ]
    result = analyse_descriptions(offers)
    assert [offer.url for offer in result.offers] == ["https://x/1"]
    assert (result.rejected_language, result.rejected_automation) == (1, 1)
    kept = result.offers[0]
    assert kept.manual_share == 100 and kept.match_score == 15  # +5 za 100% manual
    assert kept.work_summary.startswith("100% manual")


def test_nice_to_have_tools_do_not_make_offer_automation_first():
    # Przypadek GFT: obowiązki głównie manualne, narzędzia automatyzacji tylko w "Nice to have".
    description = (
        "Your tasks: Create and execute test cases and test scenarios. Plan and perform functional, "
        "integration, API, UI and mobile testing. Develop and maintain automated test scripts. "
        "Analyze test results and report defects. Prepare test documentation and test reports. "
        "Requirements: 3 years in QA, fluent English and Polish. Nice to have: Experience with API test "
        "automation using REST Assured, Postman/Newman or Playwright API. Experience with mobile test "
        "automation using Appium. Experience with UI automation frameworks such as Selenium, Playwright or "
        "Cypress. We offer: hybrid work."
    )
    profile = work_profile("QA Engineer", description)
    assert not profile.is_automation_first
    assert profile.manual_share is not None and profile.manual_share >= 40
