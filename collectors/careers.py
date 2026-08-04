"""Collector ofert QA ze stron kariery firm z bazy."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from config.companies_loader import Company, load_companies
from filter import TITLE_KEYWORDS
from .base import BaseCollector, JobOffer
from .parsing import extract_skills, extract_salary, normalize_contracts, normalize_work_mode


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

JOB_URL_MARKERS = (
    "/job/",
    "/jobs/",
    "/career/",
    "/careers/",
    "/oferta",
    "/oferty",
    "/vacancy",
    "/position",
    "/opening",
    "/requisition",
    "/o/",
    "jobid=",
    "gh_jid=",
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
    "home",
    "strona główna",
    "see all",
    "zobacz wszystkie",
    "apply now",
    "aplikuj",
)


@dataclass(slots=True)
class CompanyScanSummary:
    selected_companies: int = 0
    scanned_companies: int = 0
    failed_companies: int = 0
    blocked_companies: int = 0
    outdated_companies: int = 0
    discovered_offers: int = 0


class CareerPagesCollector(BaseCollector):
    """Przeszukuje oficjalne strony kariery firm z config/companies.json."""

    def __init__(
        self,
        tiers: tuple[str, ...] = ("S",),
        session: requests.Session | None = None,
    ) -> None:
        self.session = session or requests.Session()
        self.tiers = {tier.upper() for tier in tiers}
        self.summary = CompanyScanSummary()
        self.failures: list[str] = []
        self.blocked: list[str] = []
        self.outdated: list[str] = []

    def collect(self) -> list[JobOffer]:
        companies = [company for company in load_companies() if company.priority in self.tiers]
        self.summary = CompanyScanSummary(selected_companies=len(companies))
        offers: list[JobOffer] = []
        self.failures = []
        self.blocked = []
        self.outdated = []

        with ThreadPoolExecutor(max_workers=6) as executor:
            results = executor.map(self._collect_company, companies)

        for company, company_offers, error in results:
            if error:
                self.summary.failed_companies += 1
                error_kind = _classify_error(error)
                message = f"{company.name}: {error}"
                if error_kind == "blocked":
                    self.summary.blocked_companies += 1
                    self.blocked.append(message)
                elif error_kind == "outdated":
                    self.summary.outdated_companies += 1
                    self.outdated.append(message)
                else:
                    self.failures.append(message)
            else:
                offers.extend(company_offers)
                self.summary.scanned_companies += 1

        unique_offers = list({offer.url: offer for offer in offers}.values())
        self.summary.discovered_offers = len(unique_offers)
        return unique_offers

    def _collect_company(self, company: Company) -> tuple[Company, list[JobOffer], str | None]:
        try:
            return company, self._scrape_company(company), None
        except requests.RequestException as error:
            return company, [], str(error)
        except Exception as error:
            return company, [], str(error)

    def _scrape_company(self, company: Company) -> list[JobOffer]:
        response = self.session.get(company.careers_url, headers=REQUEST_HEADERS, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")
        seen_urls: set[str] = set()
        offers: list[JobOffer] = []

        for anchor in soup.select("a[href]"):
            title = anchor.get_text(" ", strip=True)
            href = anchor.get("href", "").strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            if not _has_relevant_title(title) and not _has_relevant_title(href):
                continue
            if _should_skip_link(title):
                continue

            url = urljoin(company.careers_url, href)
            if url in seen_urls or not _looks_like_job_url(url):
                continue
            if not _is_allowed_career_url(url, company.careers_url):
                continue

            seen_urls.add(url)
            context = _link_context(anchor)
            location = _extract_location(context, company)
            work_mode = _extract_work_mode(context, company)
            offers.append(
                JobOffer(
                    company=company.name,
                    title=_clean_title(title),
                    location=location,
                    work_mode=work_mode,
                    contract_types=normalize_contracts(context),
                    salary=extract_salary(context),
                    url=url,
                    source=CAREER_SOURCE,
                    skills=extract_skills(context),
                    company_categories=company.categories,
                )
            )

        return offers


def _has_relevant_title(text: str) -> bool:
    normalized = text.casefold().replace("-", " ").replace("_", " ")
    return any(keyword in normalized for keyword in TITLE_KEYWORDS)


def _should_skip_link(text: str) -> bool:
    normalized = text.casefold().strip()
    if len(normalized) < 4 or len(normalized) > 120:
        return True
    return any(marker in normalized for marker in SKIP_LINK_TEXT)


def _looks_like_job_url(url: str) -> bool:
    lowered = url.casefold()
    if any(host in lowered for host in ATS_HOSTS):
        return True
    return any(marker in lowered for marker in JOB_URL_MARKERS)


def _is_allowed_career_url(url: str, careers_url: str) -> bool:
    url_host = urlsplit(url).netloc.casefold()
    careers_host = urlsplit(careers_url).netloc.casefold()
    if url_host == careers_host:
        return True
    if any(host in url_host for host in ATS_HOSTS):
        return True
    if careers_host and careers_host in url_host:
        return True
    return False


def _link_context(anchor) -> str:
    parent = anchor.find_parent(["article", "li", "div", "section", "tr"])
    if parent is None:
        return anchor.get_text(" ", strip=True)
    return " ".join(parent.stripped_strings)


def _extract_location(context: str, company: Company) -> str:
    if "wrocław" in context.casefold() or "wroclaw" in context.casefold():
        return "Wrocław"
    if company.location_hint:
        return company.location_hint
    return "Nie podano"


def _extract_work_mode(context: str, company: Company) -> str:
    detected = normalize_work_mode(context)
    if detected != "Nie podano":
        return detected
    if company.work_mode_hint:
        return company.work_mode_hint
    return "Nie podano"


def _clean_title(title: str) -> str:
    cleaned = re.sub(r"\s+", " ", title).strip(" -|•")
    return cleaned


def _classify_error(error: str) -> str:
    """Rozróżnia adres nieaktualny od blokady i błędu technicznego."""
    if "403 Client Error" in error:
        return "blocked"
    if "404 Client Error" in error:
        return "outdated"
    return "technical"
