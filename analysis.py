"""Analiza treści oferty: wymagane języki obce i charakter pracy (manual / automat).

Działa na tytule i opisie oferty (``JobOffer.description``), który program
pobiera ze strony oferty podczas weryfikacji linku.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from collectors.parsing import fold_text

# --- Języki obce ---------------------------------------------------------------

# Język -> rdzenie nazw (po polsku, angielsku i w danym języku), porównywane
# bez polskich znaków. Angielski i polski są akceptowane, więc ich tu nie ma.
FOREIGN_LANGUAGES: dict[str, tuple[str, ...]] = {
    "niemiecki": ("niemieck", "german", "deutsch"),
    "francuski": ("francusk", "french", "francais"),
    "włoski": ("wlosk", "italian", "italiano"),
    "hiszpański": ("hiszpansk", "spanish", "espanol"),
    "portugalski": ("portugalsk", "portuguese"),
    "niderlandzki": ("niderlandzk", "holendersk", "dutch", "nederlands", "flemish"),
    "szwedzki": ("szwedzk", "swedish", "svenska"),
    "norweski": ("norwesk", "norwegian"),
    "duński": ("dunsk", "danish"),
    "fiński": ("finsk", "finnish"),
    "czeski": ("czesk", "czech"),
    "słowacki": ("slowack", "slovak"),
    "węgierski": ("wegiersk", "hungarian"),
    "rumuński": ("rumunsk", "romanian"),
    "rosyjski": ("rosyjsk", "russian"),
    "ukraiński": ("ukrainsk", "ukrainian"),
    "japoński": ("japonsk", "japanese"),
    "chiński": ("chinsk", "chinese", "mandarin"),
    "koreański": ("koreansk", "korean"),
    "turecki": ("tureck", "turkish"),
    "grecki": ("greck", "greek"),
    "arabski": ("arabsk", "arabic"),
    "hebrajski": ("hebrajsk", "hebrew"),
}
# Kontekst językowy - żeby "German market" czy "Czech branch" nie wykluczały oferty.
LANGUAGE_CONTEXT = (
    "jezyk", "language", "speaking", "speaker", "fluent", "plynn", "komunikatyw", "native",
    "biegl", "znajomosc", "knowledge", "proficien", "b1", "b2", "c1", "c2", "with ",
    "z jezykiem", "spoken", "written", "verbal", "pisemn", "ustn",
)
# Język tylko "mile widziany" nie wyklucza oferty.
OPTIONAL_MARKERS = (
    "mile widzian", "nice to have", "nice-to-have", "a plus", "is a plus", "will be a plus",
    "advantage", "atut", "dodatkow", "preferred but", "optional", "opcjonaln", "bonus",
)
CONTEXT_WINDOW = 80
# Przełącznik języka strony ("Language: English (United States), Français
# (France)") to nie wymaganie oferty.
LANGUAGE_PICKER = re.compile(
    r"\b[a-z]+ \((?:united states|united kingdom|france|deutschland|germany|espana|spain|"
    r"italia|italy|polska|poland|portugal|brasil|nederland)\)"
)


# Słowa funkcyjne typowe dla języka, w którym napisano ogłoszenie (po fold_text).
# Ogłoszenie po niemiecku wymaga niemieckiego, nawet jeśli tego nie pisze wprost.
WRITTEN_IN_MARKERS: dict[str, frozenset[str]] = {
    "niemiecki": frozenset({"und", "oder", "mit", "fur", "wir", "sie", "ihre", "der", "das", "ist", "sind",
                            "nicht", "auf", "eine", "einen", "bei", "werden", "zur", "zum", "deine", "kenntnisse"}),
    "francuski": frozenset({"et", "avec", "pour", "nous", "vous", "les", "une", "est", "sont", "dans",
                            "votre", "notre", "aux"}),
    "niderlandzki": frozenset({"het", "een", "voor", "wij", "jij", "ervaring", "kennis", "naar", "werken"}),
    "hiszpański": frozenset({"para", "los", "las", "del", "nuestro", "experiencia", "conocimientos", "trabajo"}),
    "włoski": frozenset({"della", "delle", "sono", "nostro", "esperienza", "competenze", "gli", "lavoro"}),
}
TITLE_MARKER_HITS = 2
DESCRIPTION_MARKER_SHARE = 0.06
DESCRIPTION_MARKER_MIN_HITS = 12


def required_foreign_languages(title: str, description: str = "") -> list[str]:
    """Języki obce (poza angielskim) wymagane przez ofertę.

    W tytule każda wzmianka o języku wyklucza ofertę ("Tester with German").
    W opisie - tylko z kontekstem językowym i bez dopisku "mile widziany".
    Wyklucza też ogłoszenia napisane w innym języku ("Tester, remote und Hannover").
    """

    found: list[str] = []
    folded_title = fold_text(title)
    folded_description = fold_text(description)
    for language, stems in FOREIGN_LANGUAGES.items():
        if any(_has_stem(folded_title, stem) for stem in stems):
            found.append(language)
            continue
        for stem in stems:
            if _required_in_text(folded_description, stem):
                found.append(language)
                break
    for language in written_in(folded_title, folded_description):
        if language not in found:
            found.append(language)
    return found


def written_in(folded_title: str, folded_description: str) -> list[str]:
    """Języki, w których (poza angielskim i polskim) napisano tytuł albo opis."""

    title_words = re.findall(r"[a-z]+", folded_title)
    description_words = re.findall(r"[a-z]+", folded_description)
    languages = []
    for language, markers in WRITTEN_IN_MARKERS.items():
        title_hits = len({word for word in title_words if word in markers})
        description_hits = sum(1 for word in description_words if word in markers)
        in_description = (
            description_hits >= DESCRIPTION_MARKER_MIN_HITS
            and description_hits / max(len(description_words), 1) >= DESCRIPTION_MARKER_SHARE
        )
        if title_hits >= TITLE_MARKER_HITS or in_description:
            languages.append(language)
    return languages


def _has_stem(text: str, stem: str) -> bool:
    return re.search(rf"(?<![a-z]){re.escape(stem)}", text) is not None


def _required_in_text(text: str, stem: str) -> bool:
    # Kontekst sprawdzamy w obrębie zdania z nazwą języka - "for the German
    # market. Fluent English required" nie jest wymogiem niemieckiego.
    text = LANGUAGE_PICKER.sub(" ", text)
    for sentence in re.split(r"[.;!?\n•|]+", text):
        for match in re.finditer(rf"(?<![a-z]){re.escape(stem)}", sentence):
            window = sentence[max(0, match.start() - CONTEXT_WINDOW): match.end() + CONTEXT_WINDOW]
            if not any(marker in window for marker in LANGUAGE_CONTEXT):
                continue
            if any(marker in window for marker in OPTIONAL_MARKERS):
                continue
            return True
    return False


# --- Manual vs automatyzacja ------------------------------------------------------

# (wzorzec po fold_text, waga, etykieta do podsumowania)
MANUAL_SIGNALS: tuple[tuple[str, int, str], ...] = (
    (r"manual", 3, "testy manualne"),
    (r"przypadk\w* testow|test cases?|scenariusz\w* testow|test scenario", 2, "przypadki testowe"),
    (r"eksploracyjn|exploratory", 2, "eksploracyjne"),
    (r"\buat\b|akceptacyjn|acceptance test", 1, "UAT"),
    (r"funkcjonaln|(?<!cross-)(?<!cross )functional|integration testing|testy integracyjn|"
     r"ui testing|mobile testing|testy mobiln", 1, "funkcjonalne / UI / mobile"),
    (r"regresj|regression", 1, "regresja"),
    (r"zglaszan\w* bled|bug report|raportowan\w* bled|defect report|report(ing)? (defects|bugs)|"
     r"defect tracking|zglaszan\w* defekt", 1, "raportowanie błędów"),
    (r"testrail|xray|zephyr|qtest", 1, "TestRail/Xray"),
    (r"dokumentac\w* testow|test plan|plan testow|test documentation|test reports?|raport\w* z test", 1,
     "dokumentacja testów"),
    (r"postman|swagger|soapui", 1, "API ręcznie (Postman)"),
)
AUTOMATION_SIGNALS: tuple[tuple[str, int, str], ...] = (
    (r"automat|automation", 3, "automatyzacja"),
    (r"\bsdet\b", 3, "SDET"),
    (r"selenium|webdriver", 2, "Selenium"),
    (r"playwright", 2, "Playwright"),
    (r"cypress", 2, "Cypress"),
    (r"appium", 2, "Appium"),
    (r"robot framework", 2, "Robot Framework"),
    (r"rest.?assured|karate", 2, "REST Assured"),
    (r"pytest|junit|testng|nunit|xunit|mocha|jest\b", 2, "framework testów"),
    (r"cucumber|gherkin|specflow", 1, "BDD"),
    (r"\bjava\b|\bpython\b|typescript|javascript|\bc#|\.net\b|kotlin|\bgo\b", 1, "programowanie"),
    (r"ci/cd|jenkins|gitlab ci|github actions|azure devops pipeline", 1, "CI/CD"),
    (r"jmeter|gatling|\bk6\b|locust", 1, "testy wydajności"),
)
# Oferta z udziałem manualnym poniżej progu i wyraźnymi sygnałami automatyzacji
# W WYMAGANIACH/OBOWIĄZKACH (nie w "mile widziane") jest traktowana jak
# stanowisko automatyzującego (filtr "automatyzacja").
AUTOMATION_EXCLUDE_SHARE = 25
AUTOMATION_EXCLUDE_MIN_SIGNALS = 3
# Sekcja "mile widziane" - narzędzia z niej ważą 1/3 (nie są wymaganiem).
OPTIONAL_SECTION_START = re.compile(
    r"nice to have|nice-to-have|mile widzian\w*|dodatkow\w* atut\w*|will be a plus|would be a plus|"
    r"is a plus|good to have|bonus points|optional skills|preferred qualifications"
)
OPTIONAL_SECTION_END = re.compile(
    r"we offer|what we offer|oferujemy|co oferujemy|benefit|about us|o nas|our offer|why join|"
    r"what you get|your tasks|your responsibilities|requirements|wymagania|obowiazki"
)
OPTIONAL_SECTION_MAX = 700
OPTIONAL_WEIGHT = 1 / 3


@dataclass(frozen=True, slots=True)
class WorkProfile:
    manual_share: int | None  # 0-100, None = za mało informacji
    manual_signals: tuple[str, ...]
    automation_signals: tuple[str, ...]
    # Sygnały automatyzacji z wymagań/obowiązków (bez sekcji "mile widziane").
    required_automation_signals: tuple[str, ...] = ()

    @property
    def summary(self) -> str:
        if self.manual_share is None:
            return "brak danych w opisie"
        parts = [f"{self.manual_share}% manual / {100 - self.manual_share}% automat"]
        if self.manual_signals:
            parts.append("manual: " + ", ".join(self.manual_signals[:3]))
        if self.automation_signals:
            parts.append("automat: " + ", ".join(self.automation_signals[:3]))
        return " · ".join(parts)

    @property
    def is_automation_first(self) -> bool:
        return (
            self.manual_share is not None
            and self.manual_share < AUTOMATION_EXCLUDE_SHARE
            and len(self.required_automation_signals) >= AUTOMATION_EXCLUDE_MIN_SIGNALS
        )


def work_profile(title: str, description: str = "") -> WorkProfile:
    """Szacuje udział testów manualnych na podstawie tytułu i opisu.

    Tytuł waży podwójnie - "Manual Tester" mówi więcej niż jedna wzmianka
    o Javie. Narzędzia z sekcji "Nice to have" / "mile widziane" ważą 1/3.
    """

    folded_title = fold_text(title)
    required_text, optional_text = split_optional(fold_text(description))
    manual_score, manual_labels = _score(MANUAL_SIGNALS, folded_title, required_text, optional_text)
    auto_score, auto_labels = _score(AUTOMATION_SIGNALS, folded_title, required_text, optional_text)
    _, required_auto = _score(AUTOMATION_SIGNALS, folded_title, required_text, "")
    total = manual_score + auto_score
    if total < 2:
        return WorkProfile(None, tuple(manual_labels), tuple(auto_labels), tuple(required_auto))
    share = round(manual_score / total * 10) * 10
    return WorkProfile(share, tuple(manual_labels), tuple(auto_labels), tuple(required_auto))


def split_optional(folded_text: str) -> tuple[str, str]:
    """Dzieli opis na (wymagania i obowiązki, sekcje "mile widziane")."""

    required, optional, position = [], [], 0
    for match in OPTIONAL_SECTION_START.finditer(folded_text):
        if match.start() < position:
            continue
        end_match = OPTIONAL_SECTION_END.search(folded_text, match.end(), match.end() + OPTIONAL_SECTION_MAX)
        end = end_match.start() if end_match else min(len(folded_text), match.end() + OPTIONAL_SECTION_MAX)
        required.append(folded_text[position:match.start()])
        optional.append(folded_text[match.start():end])
        position = end
    required.append(folded_text[position:])
    return " ".join(required), " ".join(optional)


def _score(signals, folded_title: str, required_text: str, optional_text: str) -> tuple[float, list[str]]:
    score, labels = 0.0, []
    for pattern, weight, label in signals:
        if re.search(pattern, folded_title):
            score += weight * 2
        elif re.search(pattern, required_text):
            score += weight
        elif optional_text and re.search(pattern, optional_text):
            score += weight * OPTIONAL_WEIGHT
        else:
            continue
        labels.append(label)
    return score, labels
