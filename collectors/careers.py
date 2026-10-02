"""Collector ofert QA ze stron kariery firm z bazy.

Dla każdej firmy kolejno:

1. pobiera oferty z ATS wskazanego w bazie (``ats``) albo wykrytego w kodzie
   strony kariery (Workday, SmartRecruiters, Greenhouse, Teamtailor...);
2. czyta ustrukturyzowane oferty schema.org/JobPosting (JSON-LD);
3. szuka na stronie linków do ofert z tytułem QA;
4. jeśli na stronie są linki typu "Oferty pracy" / "Open positions",
   przechodzi na te podstrony (najwyżej ``MAX_LISTING_PAGES``);
5. opcjonalnie (``render=True``) renderuje w przeglądarce strony, z których
   statyczny HTML nic nie dał - wiele stron karier ładuje listę JavaScriptem.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.companies_loader import COMPANIES_PATH, Company, load_companies
from filter import TITLE_KEYWORDS, is_preferred_city
from .ats import AtsBoard, board_from_spec, fetch_board, find_boards_in_html, in_target_country
from .base import BaseCollector, JobOffer
from .parsing import (
    contains_keyword,
    extract_salary,
    extract_skills,
    fold_text,
    json_ld_contracts,
    json_ld_location,
    json_ld_salary,
    json_ld_title,
    json_ld_work_mode,
    normalize_contracts,
    normalize_work_mode,
    parse_json_ld_jobs,
)


REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/138.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}

CAREER_SOURCE = "Strona kariery"
MAX_LISTING_PAGES = 3
RENDER_TIMEOUT_MS = 30_000

JOB_URL_MARKERS = (
    "/job/",
    "/jobs/",
    "/job-",
    "/career/",
    "/careers/",
    "/kariera/",
    "/praca/",
    "/oferta",
    "/oferty",
    "/ogloszenia",
    "/vacancy",
    "/vacancies",
    "/position",
    "/opening",
    "/requisition",
    "/rekrutacj",
    "/o/",
    "/an/",
    "jobid=",
    "job_id=",
    "gh_jid=",
    "oid=",
)

ATS_HOSTS = (
    "greenhouse.io",
    "lever.co",
    "myworkdayjobs.com",
    "smartrecruiters.com",
    "teamtailor.com",
    "workable.com",
    "bamboohr.com",
    "ashbyhq.com",
    "recruitee.com",
    "jobvite.com",
    "traffit.com",
    "erecruiter.pl",
    "successfactors.com",
    "successfactors.eu",
    "personio.de",
    "personio.com",
    "softgarden.io",
    "join.com",
    "breezy.hr",
    "hrlink.pl",
    "elevato.net",
    "taleo.net",
    "icims.com",
    "oraclecloud.com",
    "eightfold.ai",
    "avature.net",
)

SKIP_LINK_TEXT = (
    "cookie",
    "privacy",
    "polityka",
    "regulamin",
    "linkedin",
    "facebook",
    "instagram",
    "newsletter",
    "kontakt",
    "contact",
    "blog",
    "strona główna",
    "see all",
    "zobacz wszystkie",
    "apply now",
    "aplikuj",
    "artykuł",
    "case study",
    "webinar",
    "podcast",
)

GENERIC_LINK_TEXT = ("zobacz więcej", "więcej", "szczegóły", "sprawdź", "read more", "see more",
                     "learn more", "more", "details", "view job", "zobacz ofertę")

# Teksty linków prowadzących z landing page do właściwej listy ofert.
LISTING_LINK_TEXT = (
    "oferty pracy",
    "aktualne oferty",
    "aktualne rekrutacje",
    "otwarte rekrutacje",
    "prowadzone rekrutacje",
    "zobacz oferty",
    "wszystkie oferty",
    "ogłoszenia o pracę",
    "ogloszenia o prace",
    "open positions",
    "job openings",
    "current openings",
    "open roles",
    "all jobs",
    "see jobs",
    "see all jobs",
    "view jobs",
    "view all jobs",
    "browse jobs",
    "search jobs",
    "find jobs",
    "job offers",
    "job search",
    "vacancies",
    "join us",
    "dołącz do nas",
)

CAREER_HOST_WORDS = ("kariera", "karier", "career", "careers", "jobs", "praca", "rekrutacja", "work")
SOFT_404_MARKERS = ("404", "not-found", "notfound", "nie-znalez", "page-not-found", "strona-nie-istnieje")
SOFT_404_TITLES = ("404", "page not found", "nie znaleziono", "strona nie istnieje", "nie została znaleziona")


class PageProblem(Exception):
    """Strona kariery nie istnieje albo przekierowuje w ślepy zaułek."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(slots=True)
class CompanyScanSummary:
    selected_companies: int = 0
    scanned_companies: int = 0
    failed_companies: int = 0
    blocked_companies: int = 0
    outdated_companies: int = 0
    discovered_offers: int = 0


@dataclass(slots=True)
class CompanyScan:
    company: Company
    offers: list[JobOffer] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    error_kind: str = ""
    boards: list[AtsBoard] = field(default_factory=list)
    final_url: str = ""

    def add(self, method: str, offers: list[JobOffer]) -> None:
        known = {offer.url for offer in self.offers}
        new = [offer for offer in offers if offer.url not in known]
        if new and method not in self.methods:
            self.methods.append(method)
        self.offers.extend(new)


class CareerPagesCollector(BaseCollector):
    """Przeszukuje oficjalne strony kariery z bazy (domyślnie config/companies.json).

    Ta sama klasa obsługuje bazę instytucji publicznych - wystarczy podać
    inny plik (``companies_path``) i polskie, urzędowe słowa kluczowe tytułów.
    """

    def __init__(
        self,
        tiers: tuple[str, ...] = ("S",),
        session: requests.Session | None = None,
        company_names: tuple[str, ...] = (),
        render: bool = False,
        companies_path: Path = COMPANIES_PATH,
        categories: tuple[str, ...] = (),
        title_keywords: tuple[str, ...] = (),
        source: str = CAREER_SOURCE,
    ) -> None:
        self.session = session or _build_session()
        self.companies_path = companies_path
        self.categories = {category.casefold() for category in categories}
        self.title_keywords = tuple(dict.fromkeys((*TITLE_KEYWORDS, *title_keywords)))
        self.source = source
        self.tiers = {tier.upper() for tier in tiers}
        self.company_names = tuple(fold_text(name) for name in company_names)
        self.render = render
        self.summary = CompanyScanSummary()
        self.scans: list[CompanyScan] = []
        self.failures: list[str] = []
        self.blocked: list[str] = []
        self.outdated: list[str] = []
        self.warnings: list[str] = []

    def collect(self) -> list[JobOffer]:
        companies = [company for company in load_companies(self.companies_path) if self._is_selected(company)]
        self.summary = CompanyScanSummary(selected_companies=len(companies))
        self.failures, self.blocked, self.outdated, self.warnings = [], [], [], []

        with ThreadPoolExecutor(max_workers=6) as executor:
            self.scans = list(executor.map(self._scan_company, companies))

        if self.render:
            self._render_empty_scans()

        offers: list[JobOffer] = []
        for scan in self.scans:
            name = scan.company.name
            self.warnings.extend(f"{name}: {warning}" for warning in scan.warnings)
            if scan.error:
                self.summary.failed_companies += 1
                message = f"{name}: {scan.error}"
                if scan.error_kind == "blocked":
                    self.summary.blocked_companies += 1
                    self.blocked.append(message)
                elif scan.error_kind == "outdated":
                    self.summary.outdated_companies += 1
                    self.outdated.append(message)
                else:
                    self.failures.append(message)
                continue
            self.summary.scanned_companies += 1
            offers.extend(scan.offers)

        unique_offers = list({offer.url: offer for offer in offers}.values())
        # Oferty z list HTML mają zwykle tylko tytuł. Strona konkretnej oferty
        # podaje faktyczną lokalizację, umowę, wynagrodzenie i wymagania.
        with ThreadPoolExecutor(max_workers=6) as executor:
            unique_offers = list(executor.map(self._enrich_offer, unique_offers))
        unique_offers = [offer for offer in unique_offers if in_target_country(offer.location)]
        self.summary.discovered_offers = len(unique_offers)
        return unique_offers

    def _is_selected(self, company: Company) -> bool:
        if not company.enabled:
            return False
        if self.company_names:
            return any(name in fold_text(company.name) for name in self.company_names)
        if self.categories and not self.categories & {category.casefold() for category in company.categories}:
            return False
        return company.priority in self.tiers

    # --- Skanowanie jednej firmy ------------------------------------------

    def _scan_company(self, company: Company) -> CompanyScan:
        scan = CompanyScan(company)
        boards: dict[str, AtsBoard] = {}
        for spec in company.ats:
            board = board_from_spec(spec)
            if board is None:
                scan.warnings.append(f"nieobsługiwany wpis ATS: {spec.url}")
            else:
                boards[board.label] = board

        start_urls = list(dict.fromkeys(url for url in (company.jobs_url, company.careers_url) if url))
        last_error: Exception | None = None
        for url in start_urls:
            try:
                response = self._get_page(url)
            except (requests.RequestException, PageProblem) as error:
                last_error = error
                continue
            scan.final_url = scan.final_url or response.url
            self._scan_html(scan, response.text, response.url, boards, follow_listings=True)

        if last_error is not None:
            if not scan.final_url and not boards:
                scan.error = _describe_error(last_error)
                scan.error_kind = last_error.kind if isinstance(last_error, PageProblem) else _classify_error(last_error)
                return scan
            # Strona kariery bywa nieaktualna, a ATS z bazy nadal działa.
            scan.warnings.append(f"strona kariery: {_describe_error(last_error)}")

        scan.boards = list(boards.values())
        for board in scan.boards:
            try:
                scan.add(board.type, fetch_board(self.session, board, company, self.title_keywords))
            except (requests.RequestException, ValueError, KeyError) as error:
                scan.warnings.append(f"ATS {board.label} niedostępny ({_describe_error(error)})")
        return scan

    def _scan_html(
        self,
        scan: CompanyScan,
        html: str,
        page_url: str,
        boards: dict[str, AtsBoard],
        follow_listings: bool,
        method_suffix: str = "",
    ) -> None:
        company = scan.company
        if not company.ats:
            for board in find_boards_in_html(html, page_url):
                boards.setdefault(board.label, board)

        scan.add("json-ld" + method_suffix, _offers_from_json_ld(html, page_url, company, self.title_keywords, self.source))
        soup = BeautifulSoup(html, "lxml")
        scan.add("html" + method_suffix, _offers_from_links(soup, page_url, company, self.title_keywords, self.source))

        if not follow_listings:
            return
        visited = {page_url}
        for listing_url in _listing_links(soup, page_url)[:MAX_LISTING_PAGES]:
            if listing_url in visited:
                continue
            visited.add(listing_url)
            try:
                response = self._get_page(listing_url)
            except (requests.RequestException, PageProblem):
                continue
            self._scan_html(scan, response.text, response.url, boards, follow_listings=False)

    def _get_page(self, url: str) -> requests.Response:
        response = self.session.get(url, headers=REQUEST_HEADERS, timeout=30)
        response.raise_for_status()
        problem = _soft_404(url, response)
        if problem:
            raise PageProblem("outdated", problem)
        return response

    # --- Renderowanie JS ------------------------------------------------------

    def _render_empty_scans(self) -> None:
        targets = [scan for scan in self.scans if not scan.error and not scan.offers and not scan.boards]
        if not targets:
            return
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.warnings.append("Playwright niedostępny - pomijam renderowanie stron (pip install playwright).")
            return

        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch()
            except PlaywrightError as error:
                self.warnings.append(f"Nie udało się uruchomić Chromium ({error}). Uruchom: python -m playwright install chromium")
                return
            page = browser.new_page(user_agent=REQUEST_HEADERS["User-Agent"], locale="pl-PL")
            for scan in targets:
                url = scan.company.jobs_url or scan.final_url or scan.company.careers_url
                try:
                    page.goto(url, wait_until="load", timeout=RENDER_TIMEOUT_MS)
                    try:
                        # Strony z analityką nigdy nie są "bezczynne" - czekamy
                        # chwilę na doładowanie listy i bierzemy to, co jest.
                        page.wait_for_load_state("networkidle", timeout=8_000)
                    except PlaywrightError:
                        pass
                    html = page.content()
                except PlaywrightError as error:
                    scan.warnings.append(f"renderowanie nieudane ({str(error).splitlines()[0]})")
                    continue
                boards: dict[str, AtsBoard] = {}
                self._scan_html(scan, html, page.url, boards, follow_listings=False, method_suffix=" (render)")
                for board in boards.values():
                    try:
                        scan.add(board.type, fetch_board(self.session, board, scan.company, self.title_keywords))
                    except (requests.RequestException, ValueError, KeyError) as error:
                        scan.warnings.append(f"ATS {board.label} niedostępny ({_describe_error(error)})")
                scan.boards = list(boards.values())
            browser.close()

    # --- Szczegóły oferty -----------------------------------------------------

    def _enrich_offer(self, offer: JobOffer) -> JobOffer:
        if offer.api_confirmed and (offer.skills or offer.location != "Nie podano"):
            return offer
        try:
            response = self.session.get(offer.url, headers=REQUEST_HEADERS, timeout=20)
            response.raise_for_status()
        except requests.RequestException:
            # Link zostanie jeszcze zweryfikowany przed dodaniem do raportu.
            return offer

        postings = parse_json_ld_jobs(response.text)
        if postings:
            posting = postings[0]
            description = BeautifulSoup(str(posting.get("description", "")), "lxml").get_text(" ", strip=True)
            title = json_ld_title(posting)
            location = json_ld_location(posting)
            work_mode = json_ld_work_mode(posting)
            if work_mode == "Nie podano":
                work_mode = normalize_work_mode(description)
            return replace(
                offer,
                title=title if contains_keyword(title, self.title_keywords) else offer.title,
                location=location or offer.location,
                work_mode=work_mode if work_mode != "Nie podano" else offer.work_mode,
                contract_types=json_ld_contracts(posting) or normalize_contracts(description) or offer.contract_types,
                salary=json_ld_salary(posting) or extract_salary(description) or offer.salary,
                skills=tuple(dict.fromkeys((*offer.skills, *extract_skills(description)))),
            )

        soup = BeautifulSoup(response.text, "lxml")
        heading = soup.find("h1")
        heading_text = _clean_title(heading.get_text(" ", strip=True)) if heading else ""
        page_text = _main_text(soup)
        location = _extract_location(page_text)
        work_mode = normalize_work_mode(page_text)
        return replace(
            offer,
            # Nagłówek bywa ogólny ("Kariera") - podmieniamy tylko na tytuł QA.
            title=heading_text if contains_keyword(heading_text, self.title_keywords) else offer.title,
            location=location if location != "Nie podano" else offer.location,
            work_mode=work_mode if work_mode != "Nie podano" else offer.work_mode,
            contract_types=normalize_contracts(page_text) or offer.contract_types,
            salary=extract_salary(page_text) or offer.salary,
            skills=tuple(dict.fromkeys((*offer.skills, *extract_skills(page_text)))),
        )


# --- Funkcje pomocnicze -------------------------------------------------------

def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=2, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=("GET", "POST"))
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _offers_from_json_ld(
    html: str, page_url: str, company: Company, keywords: tuple[str, ...], source: str
) -> list[JobOffer]:
    offers = []
    for posting in parse_json_ld_jobs(html):
        title = json_ld_title(posting)
        url = posting.get("url") or posting.get("@id") or ""
        if not contains_keyword(title, keywords) or not str(url).startswith("http"):
            continue
        description = BeautifulSoup(str(posting.get("description", "")), "lxml").get_text(" ", strip=True)
        offers.append(
            JobOffer(
                company=company.name,
                title=title,
                location=json_ld_location(posting) or "Nie podano",
                work_mode=json_ld_work_mode(posting) if json_ld_work_mode(posting) != "Nie podano"
                else _extract_work_mode(description, company),
                contract_types=json_ld_contracts(posting) or normalize_contracts(description),
                salary=json_ld_salary(posting) or extract_salary(description),
                url=urljoin(page_url, str(url)),
                source=source,
                skills=extract_skills(description),
                company_categories=company.categories,
            )
        )
    return offers


def _offers_from_links(
    soup: BeautifulSoup, page_url: str, company: Company, keywords: tuple[str, ...], source: str
) -> list[JobOffer]:
    seen_urls: set[str] = set()
    offers: list[JobOffer] = []
    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        title = _anchor_title(anchor)
        if not contains_keyword(title, keywords):
            continue
        if _should_skip_link(title):
            continue

        url = urljoin(page_url, href)
        if url in seen_urls or url.rstrip("/") == page_url.rstrip("/") or not _looks_like_job_url(url):
            continue
        if not _is_allowed_career_url(url, page_url, company.careers_url):
            continue

        seen_urls.add(url)
        context = _link_context(anchor)
        offers.append(
            JobOffer(
                company=company.name,
                title=_clean_title(title),
                location=_extract_location(context),
                work_mode=_extract_work_mode(context, company),
                contract_types=normalize_contracts(context),
                salary=extract_salary(context),
                url=url,
                source=source,
                skills=extract_skills(context),
                company_categories=company.categories,
            )
        )
    return offers


def _anchor_title(anchor) -> str:
    """Tytuł oferty z linku; karty ofert często mają w linku też miasto i opis."""

    heading = anchor.find(["h1", "h2", "h3", "h4", "h5", "h6"]) or anchor.find(class_=re.compile("title", re.I))
    if heading is not None:
        text = heading.get_text(" ", strip=True)
    else:
        text = anchor.get_text(" ", strip=True)
    if not text:
        text = anchor.get("aria-label") or anchor.get("title") or ""
    if contains_keyword(text, GENERIC_LINK_TEXT) and len(text) < 30:
        # "Zobacz więcej" - tytuł oferty jest w nagłówku karty obok linku.
        node = anchor
        for _ in range(4):
            node = node.find_parent(["article", "li", "div", "section", "tr"])
            if node is None:
                break
            card_heading = node.find(["h2", "h3", "h4", "h5"])
            if card_heading is not None:
                return card_heading.get_text(" ", strip=True)
    return text


def _listing_links(soup: BeautifulSoup, page_url: str) -> list[str]:
    links: list[str] = []
    for anchor in soup.select("a[href]"):
        text = anchor.get_text(" ", strip=True)
        if not text or len(text) > 60 or not contains_keyword(text, LISTING_LINK_TEXT):
            continue
        url = urljoin(page_url, anchor.get("href", "").strip())
        if not url.startswith("http") or url.rstrip("/") == page_url.rstrip("/"):
            continue
        if _site_key(urlsplit(url).netloc) != _site_key(urlsplit(page_url).netloc) and not _is_ats_host(url):
            continue
        links.append(url)
    return list(dict.fromkeys(links))


def _should_skip_link(text: str) -> bool:
    normalized = text.casefold().strip()
    if len(normalized) < 4 or len(normalized) > 150:
        return True
    return any(marker in normalized for marker in SKIP_LINK_TEXT)


def _looks_like_job_url(url: str) -> bool:
    lowered = url.casefold()
    if _is_ats_host(url):
        return True
    return any(marker in lowered for marker in JOB_URL_MARKERS)


def _is_ats_host(url: str) -> bool:
    host = urlsplit(url).netloc.casefold()
    return any(host == ats or host.endswith("." + ats) for ats in ATS_HOSTS)


def _site_key(host: str) -> str:
    """Domena rejestrowana w uproszczeniu: kariera.comarch.pl -> comarch.pl."""

    labels = host.casefold().split(":")[0].split(".")
    if len(labels) >= 3 and labels[-2] in ("com", "gov", "org", "net", "co", "edu"):
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _is_allowed_career_url(url: str, page_url: str, careers_url: str) -> bool:
    site = _site_key(urlsplit(url).netloc)
    if site in (_site_key(urlsplit(page_url).netloc), _site_key(urlsplit(careers_url).netloc)):
        return True
    return _is_ats_host(url)


def _link_context(anchor) -> str:
    """Tekst najbliższej "karty" oferty - bez całej listy z innymi ofertami."""

    context = anchor.get_text(" ", strip=True)
    node = anchor
    for _ in range(4):
        parent = node.find_parent(["article", "li", "div", "section", "tr"])
        if parent is None:
            break
        text = " ".join(parent.stripped_strings)
        if len(text) > 400 or len(parent.select("a[href]")) > 3:
            break
        context, node = text, parent
    return context


def _main_text(soup: BeautifulSoup) -> str:
    """Treść oferty bez nawigacji, stopki i banerów cookies.

    Słowo "remote" w menu lub lista biur w stopce dawały wcześniej fałszywe
    "Remote" i fałszywą lokalizację.
    """

    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "form", "svg"]):
        tag.decompose()
    for tag in soup.find_all(attrs={"class": re.compile("cookie|consent|gdpr", re.I)}):
        tag.decompose()
    for tag in soup.find_all(attrs={"id": re.compile("cookie|consent|gdpr", re.I)}):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    return " ".join(main.stripped_strings)


def _extract_location(context: str) -> str:
    from config.profile import PROFILE

    if is_preferred_city(context):
        return PROFILE.preferred_city
    return "Nie podano"


def _extract_work_mode(context: str, company: Company) -> str:
    detected = normalize_work_mode(context)
    if detected != "Nie podano":
        return detected
    if company.work_mode_hint:
        return company.work_mode_hint
    return "Nie podano"


def _clean_title(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip(" -|•")


def _soft_404(requested_url: str, response: requests.Response) -> str | None:
    """Wykrywa stronę błędu zwróconą z kodem 200 oraz przekierowanie na stronę główną."""

    final = urlsplit(response.url)
    requested = urlsplit(requested_url)
    final_path = final.path.casefold()
    if any(marker in final_path for marker in SOFT_404_MARKERS):
        return f"przekierowanie na stronę błędu ({response.url})"

    def is_home(path: str) -> bool:
        return re.fullmatch(r"/?(?:[a-z]{2}(?:[-_][a-z]{2})?/?)?", path.casefold()) is not None

    # Przekierowanie na osobną domenę kariery (np. karieranabank.pl) jest w porządku.
    career_host = contains_keyword(final.netloc.replace(".", " "), CAREER_HOST_WORDS)
    if not is_home(requested.path) and is_home(final.path) and not final.query and not career_host:
        return f"przekierowanie na stronę główną ({response.url})"

    title_match = re.search(r"<title[^>]*>(.*?)</title>", response.text[:20000], re.IGNORECASE | re.DOTALL)
    title = fold_text(title_match.group(1)) if title_match else ""
    if any(fold_text(marker) in title for marker in SOFT_404_TITLES):
        return f"strona błędu: {' '.join(title.split())[:80]}"
    return None


def _classify_error(error: Exception) -> str:
    """Rozróżnia adres nieaktualny od blokady i błędu technicznego."""

    response = getattr(error, "response", None)
    status = response.status_code if response is not None else None
    if status in (401, 403, 429):
        return "blocked"
    if status in (404, 410):
        return "outdated"
    if isinstance(error, requests.exceptions.SSLError) and "hostname mismatch" in str(error).casefold():
        return "outdated"
    return "technical"


def _describe_error(error: Exception) -> str:
    if isinstance(error, PageProblem):
        return str(error)
    response = getattr(error, "response", None)
    if response is not None and response.status_code:
        return f"HTTP {response.status_code} ({response.url})"
    if isinstance(error, requests.exceptions.SSLError):
        text = str(error)
        if "hostname mismatch" in text.casefold():
            return "certyfikat SSL nie pasuje do domeny - adres prawdopodobnie nieaktualny"
        return "błąd certyfikatu SSL"
    if isinstance(error, requests.exceptions.Timeout):
        return "przekroczony czas odpowiedzi"
    if isinstance(error, requests.exceptions.ConnectionError):
        return "brak połączenia z serwerem"
    return str(error)[:160]
