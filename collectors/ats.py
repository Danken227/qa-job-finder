"""Adaptery publicznych API systemów rekrutacyjnych (ATS).

Strony karier dużych firm to zwykle tylko landing page - właściwa lista ofert
jest w zewnętrznym ATS (Workday, SmartRecruiters, Teamtailor...) i ładuje się
JavaScriptem, więc zwykły parser HTML jej nie widzi. Te same systemy mają
jednak publiczne endpointy JSON/RSS, z których korzystają ich własne widżety.

Każdy adapter zwraca oferty z tytułem pasującym do profilu i lokalizacją
w kraju z profilu (lub zdalne / bez podanej lokalizacji).
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from html import unescape
from urllib.parse import urlencode, urlsplit

import requests
from bs4 import BeautifulSoup

from config.companies_loader import AtsSpec, Company
from config.profile import PROFILE
from .base import JobOffer
from .parsing import (
    contains_keyword,
    extract_salary,
    extract_skills,
    fold_text,
    normalize_contracts,
    normalize_work_mode,
    work_mode_from_flags,
)


REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/138.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}
TIMEOUT = 25
# Limit wyników na jedno słowo kluczowe w ATS z wyszukiwarką po stronie
# serwera - chroni przed pobieraniem tysięcy ofert globalnych korporacji.
MAX_RESULTS_PER_KEYWORD = 100

COUNTRY_ALIASES = {
    "poland": ("Poland", "Polska", "PL", "POL"),
    "germany": ("Germany", "Deutschland", "DE", "DEU"),
}
COUNTRY_CODES = {"poland": "pl", "germany": "de"}
# Oferta zdalna "dla regionu" też może obejmować kraj z profilu.
REGION_MARKERS = ("europe", "emea", "anywhere", "worldwide", "global", "cee")


@dataclass(frozen=True, slots=True)
class AtsBoard:
    type: str
    key: str
    params: dict = field(default_factory=dict, hash=False, compare=False)

    @property
    def label(self) -> str:
        return f"{self.type}:{self.key}"


# --- Wykrywanie --------------------------------------------------------------

_URL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("greenhouse", re.compile(r"https?://(?:job-)?boards(?:-api)?(\.eu)?\.greenhouse\.io/(?:v1/boards/|embed/job_board\?for=)?([\w-]+)", re.I)),
    ("lever", re.compile(r"https?://(?:jobs|api)(\.eu)?\.lever\.co/(?:v0/postings/)?([\w.-]+)", re.I)),
    ("smartrecruiters", re.compile(r"https?://(?:careers|jobs)\.smartrecruiters\.com/(?:my-applications/)?([\w-]+)", re.I)),
    ("smartrecruiters", re.compile(r"https?://api\.smartrecruiters\.com/v1/companies/([\w-]+)", re.I)),
    ("workable", re.compile(r"https?://apply\.workable\.com/(?!j/|api/)([\w-]+)", re.I)),
    ("workday", re.compile(r"https?://([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]+)", re.I)),
    ("recruitee", re.compile(r"https?://([\w-]+)\.recruitee\.com", re.I)),
    ("ashby", re.compile(r"https?://jobs\.ashbyhq\.com/([\w.-]+)", re.I)),
    ("traffit", re.compile(r"https?://([\w-]+)\.traffit\.com/public/", re.I)),
    ("teamtailor", re.compile(r"https?://([\w-]+)\.teamtailor\.com", re.I)),
    ("erecruiter", re.compile(r"https?://skk\.erecruiter\.pl/(?:Code|GetHtml|Offer)\.as[hp]x\?[^\"'<>\s]*?cfg=([0-9a-f]{32})", re.I)),
)
_IGNORED_KEYS = {"www", "app", "api", "assets", "cdn", "static", "embed", "wday", "subscriptions", "login"}


def board_from_url(url: str, type_hint: str = "") -> AtsBoard | None:
    """Rozpoznaje ATS po adresie tablicy ofert (lub typie podanym w bazie)."""

    url = unescape(url).replace("\\/", "/").rstrip("\\")
    if type_hint in ("teamtailor", "successfactors", "phenom"):
        parts = urlsplit(url)
        base = f"{parts.scheme or 'https'}://{parts.netloc}"
        params = {"base": base}
        if type_hint == "phenom":
            params["prefix"] = _phenom_prefix(parts.path)
        return AtsBoard(type_hint, parts.netloc.casefold(), params)

    for ats_type, pattern in _URL_PATTERNS:
        if type_hint and ats_type != type_hint:
            continue
        match = pattern.search(url)
        if not match:
            continue
        if ats_type == "greenhouse":
            region, token = match.groups()
            return _board(ats_type, token, eu=bool(region))
        if ats_type == "lever":
            region, token = match.groups()
            return _board(ats_type, token, eu=bool(region))
        if ats_type == "workday":
            tenant, instance, site = match.groups()
            if site.casefold() in _IGNORED_KEYS:
                return None
            host = f"{tenant}.{instance}.myworkdayjobs.com"
            return AtsBoard(ats_type, f"{host}/{site}", {"host": host, "tenant": tenant, "site": site})
        if ats_type == "teamtailor":
            token = match.group(1)
            return _board(ats_type, token, base=f"https://{token}.teamtailor.com")
        if ats_type == "erecruiter":
            return _board(ats_type, match.group(1).casefold())
        return _board(ats_type, match.group(1))
    return None


def _board(ats_type: str, key: str, **params) -> AtsBoard | None:
    if not key or key.casefold() in _IGNORED_KEYS:
        return None
    return AtsBoard(ats_type, key, params)


def board_from_spec(spec: AtsSpec) -> AtsBoard | None:
    return board_from_url(spec.url, spec.type)


def find_boards_in_html(html: str, page_url: str) -> list[AtsBoard]:
    """Szuka w kodzie strony kariery odnośników do ATS i znanych platform."""

    boards: dict[str, AtsBoard] = {}
    for raw_url in re.findall(r"https?:(?:\\?/){2}[^\s\"'<>)]+", html):
        board = board_from_url(raw_url)
        if board and board.type != "teamtailor":
            boards.setdefault(board.label, board)

    page = urlsplit(page_url)
    lowered = html.casefold()
    # Platformy hostowane pod domeną firmy rozpoznajemy po "odciskach" w HTML.
    if "teamtailor" in lowered and ("teamtailor-cdn" in lowered or "powered by teamtailor" in lowered
                                   or "utm_campaign=poweredby" in lowered):
        board = board_from_url(page_url, "teamtailor")
        boards.setdefault(board.label, board)
    if "phenompeople.com" in lowered and '"refnum"' in lowered:
        board = board_from_url(page_url, "phenom")
        boards.setdefault(board.label, board)
    if "jobtitle-link" in lowered or ("rmkcdn.successfactors.com" in lowered and "/search/" in lowered):
        board = board_from_url(page_url, "successfactors")
        boards.setdefault(board.label, board)
    if page.netloc.endswith("teamtailor.com"):
        board = board_from_url(page_url, "teamtailor")
        boards.setdefault(board.label, board)
    return list(boards.values())


# --- Pobieranie --------------------------------------------------------------

def fetch_board(
    session: requests.Session,
    board: AtsBoard,
    company: Company,
    keywords: tuple[str, ...] = (),
) -> list[JobOffer]:
    """Oferty z tablicy ATS z tytułem pasującym do ``keywords`` (domyślnie z profilu)."""

    keywords = keywords or PROFILE.title_keywords
    offers = _FETCHERS[board.type](session, board, company, keywords)
    unique = {offer.url: offer for offer in offers if _is_relevant(offer, keywords)}
    return list(unique.values())


def _is_relevant(offer: JobOffer, keywords: tuple[str, ...]) -> bool:
    return contains_keyword(offer.title, keywords) and in_target_country(offer.location)


def in_target_country(location: str) -> bool:
    """Czy lokalizacja leży w kraju z profilu (lub jest nieokreślona)."""

    if not location or location == "Nie podano":
        return True
    if any(fold_text(city) in fold_text(location) for city in PROFILE.city_names if city):
        return True
    aliases = COUNTRY_ALIASES.get(fold_text(PROFILE.country), (PROFILE.country,))
    if contains_keyword(location, aliases):
        return True
    return contains_keyword(location, REGION_MARKERS) and contains_keyword(location, ("remote", "zdalnie"))


def _offer(company: Company, board: AtsBoard, *, title: str, url: str, location: str = "",
           work_mode: str = "Nie podano", description: str = "", contracts: tuple[str, ...] = (),
           salary: str = "") -> JobOffer:
    text = BeautifulSoup(unescape(description), "lxml").get_text(" ", strip=True) if description else ""
    if work_mode == "Nie podano":
        work_mode = normalize_work_mode(f"{location} {title}")
    return JobOffer(
        company=company.name,
        title=" ".join(title.split()),
        location=location or "Nie podano",
        work_mode=work_mode,
        contract_types=contracts or normalize_contracts(text),
        salary=salary or extract_salary(text),
        url=url,
        source=f"Strona kariery ({board.type})",
        skills=extract_skills(text),
        company_categories=company.categories,
        api_confirmed=True,
    )


def _get_json(session: requests.Session, url: str, **kwargs):
    response = session.get(url, headers=REQUEST_HEADERS, timeout=TIMEOUT, **kwargs)
    response.raise_for_status()
    return response.json()


def _post_json(session: requests.Session, url: str, payload: dict, **kwargs):
    response = session.post(url, json=payload, headers=REQUEST_HEADERS, timeout=TIMEOUT, **kwargs)
    response.raise_for_status()
    return response.json()


def _country_code() -> str:
    return COUNTRY_CODES.get(fold_text(PROFILE.country), "")


def _country_names() -> tuple[str, ...]:
    return COUNTRY_ALIASES.get(fold_text(PROFILE.country), (PROFILE.country,))


def _greenhouse(session, board, company, keywords):
    host = "boards-api.eu.greenhouse.io" if board.params.get("eu") else "boards-api.greenhouse.io"
    payload = _get_json(session, f"https://{host}/v1/boards/{board.key}/jobs", params={"content": "true"})
    return [
        _offer(
            company, board,
            title=job.get("title", ""),
            url=job.get("absolute_url", ""),
            location=(job.get("location") or {}).get("name", ""),
            description=job.get("content", ""),
        )
        for job in payload.get("jobs", [])
    ]


def _lever(session, board, company, keywords):
    host = "api.eu.lever.co" if board.params.get("eu") else "api.lever.co"
    jobs = _get_json(session, f"https://{host}/v0/postings/{board.key}", params={"mode": "json"})
    offers = []
    for job in jobs:
        categories = job.get("categories") or {}
        locations = categories.get("allLocations") or [categories.get("location", "")]
        workplace = str(job.get("workplaceType", "")).casefold()
        salary_range = job.get("salaryRange") or {}
        salary = ""
        if salary_range.get("min") and salary_range.get("currency"):
            interval = {"per-hour-wage": " /h", "per-month-salary": " /month", "per-year-salary": " /year"}
            salary = (f"{salary_range['min']} - {salary_range.get('max', salary_range['min'])} "
                      f"{salary_range['currency']}{interval.get(salary_range.get('interval', ''), '')}")
        offers.append(_offer(
            company, board,
            title=job.get("text", ""),
            url=job.get("hostedUrl", ""),
            location="; ".join(location for location in locations if location),
            work_mode=work_mode_from_flags(workplace == "remote", workplace == "hybrid"),
            description=job.get("descriptionPlain", "") + " " + (categories.get("commitment") or ""),
            salary=salary,
        ))
    return offers


def _smartrecruiters(session, board, company, keywords):
    offers: dict[str, JobOffer] = {}
    for keyword in PROFILE.career_search_keywords:
        params = {"q": keyword, "limit": 100}
        if _country_code():
            params["country"] = _country_code()
        payload = _get_json(session, f"https://api.smartrecruiters.com/v1/companies/{board.key}/postings", params=params)
        for job in payload.get("content", [])[:MAX_RESULTS_PER_KEYWORD]:
            location = job.get("location") or {}
            url = f"https://jobs.smartrecruiters.com/{board.key}/{job.get('id')}"
            offers[url] = _offer(
                company, board,
                title=job.get("name", ""),
                url=url,
                location=location.get("fullLocation") or location.get("city", ""),
                work_mode=work_mode_from_flags(bool(location.get("remote")), bool(location.get("hybrid"))),
            )
    # Szczegóły (opis -> umiejętności) tylko dla ofert, które przejdą filtr tytułu.
    detailed = []
    for url, offer in offers.items():
        if _is_relevant(offer, keywords):
            try:
                job_id = url.rsplit("/", 1)[-1]
                details = _get_json(session, f"https://api.smartrecruiters.com/v1/companies/{board.key}/postings/{job_id}")
                sections = ((details.get("jobAd") or {}).get("sections") or {}).values()
                description = " ".join(str(section.get("text", "")) for section in sections if isinstance(section, dict))
                text = BeautifulSoup(description, "lxml").get_text(" ", strip=True)
                offer.skills = extract_skills(text)
                offer.contract_types = normalize_contracts(text)
                offer.salary = extract_salary(text)
            except (requests.RequestException, ValueError):
                pass
        detailed.append(offer)
    return detailed


def _workable(session, board, company, keywords):
    payload = _get_json(session, f"https://apply.workable.com/api/v1/widget/accounts/{board.key}")
    offers = []
    for job in payload.get("jobs", []):
        locations = job.get("locations") or [{"city": job.get("city"), "country": job.get("country")}]
        location = "; ".join(
            ", ".join(part for part in (item.get("city"), item.get("country")) if part) for item in locations
        )
        offers.append(_offer(
            company, board,
            title=job.get("title", ""),
            url=job.get("url") or job.get("shortlink", ""),
            location=location,
            work_mode=work_mode_from_flags(bool(job.get("telecommuting"))),
            contracts=normalize_contracts(job.get("employment_type", "")),
        ))
    return offers


def _workday(session, board, company, keywords):
    host, tenant, site = board.params["host"], board.params["tenant"], board.params["site"]
    api = f"https://{host}/wday/cxs/{tenant}/{site}"
    country_facet: dict = {}
    postings: dict[str, dict] = {}
    for keyword in PROFILE.career_search_keywords:
        offset = 0
        while offset < MAX_RESULTS_PER_KEYWORD:
            payload = {"appliedFacets": country_facet or {}, "limit": 20, "offset": offset, "searchText": keyword}
            result = _post_json(session, f"{api}/jobs", payload)
            if not payload["appliedFacets"]:
                # Zapytanie bez filtra zwraca facety; zawężamy do kraju z profilu.
                facet, has_country_facet = _workday_country_facet(result.get("facets") or [])
                if facet:
                    country_facet = facet
                    continue
                if has_country_facet:
                    # Facet krajów istnieje, ale bez naszego kraju - brak takich ofert.
                    break
            jobs = result.get("jobPostings") or []
            for job in jobs:
                if job.get("externalPath"):
                    postings.setdefault(job["externalPath"], job)
            offset += 20
            if len(jobs) < 20 or offset >= int(result.get("total") or 0):
                break

    offers = []
    for path, job in postings.items():
        title = job.get("title", "")
        location = job.get("locationsText", "")
        work_mode = _workday_work_mode(job.get("remoteType", ""))
        description = ""
        if contains_keyword(title, keywords):
            # "3 Locations" nic nie mówi - szczegóły podają wszystkie miasta i opis.
            try:
                info = _get_json(session, f"{api}{path}").get("jobPostingInfo") or {}
                cities = [info.get("location", ""), *(info.get("additionalLocations") or [])]
                location = "; ".join(city for city in cities if city) or location
                country = (info.get("country") or {}).get("descriptor", "")
                if country and country not in location:
                    location = f"{location}, {country}" if location else country
                work_mode = _workday_work_mode(info.get("remoteType", "")) if info.get("remoteType") else work_mode
                description = info.get("jobDescription", "")
            except (requests.RequestException, ValueError):
                pass
        offers.append(_offer(
            company, board,
            title=title,
            url=f"https://{host}/{site}{path}",
            location=location,
            work_mode=work_mode,
            description=description,
        ))
    return offers


def _workday_country_facet(facets: list[dict]) -> tuple[dict | None, bool]:
    """Zwraca (facet z krajem z profilu, czy strona w ogóle ma facet krajów)."""

    names = {fold_text(name) for name in _country_names()}
    has_country_facet = False
    stack = list(facets)
    while stack:
        facet = stack.pop()
        parameter = facet.get("facetParameter") or ""
        is_country = "country" in parameter.casefold()
        has_country_facet = has_country_facet or is_country
        for value in facet.get("values") or []:
            if "values" in value:
                stack.append(value)
            elif is_country and fold_text(str(value.get("descriptor", ""))) in names and value.get("id"):
                return {parameter: [value["id"]]}, True
    return None, has_country_facet


def _workday_work_mode(remote_type: str) -> str:
    normalized = remote_type.casefold()
    if "partially" in normalized or "hybrid" in normalized:
        return "Hybrid"
    if "remote" in normalized:
        return "Remote"
    if "on-site" in normalized or "onsite" in normalized:
        return "Office"
    return "Nie podano"


def _teamtailor(session, board, company, keywords):
    response = session.get(f"{board.params['base']}/jobs.rss", headers=REQUEST_HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)
    namespace = {"tt": "https://teamtailor.com/locations"}
    offers = []
    for item in root.iter("item"):
        locations = []
        for location in item.findall("tt:locations/tt:location", namespace):
            city = location.findtext("tt:city", default="", namespaces=namespace)
            country = location.findtext("tt:country", default="", namespaces=namespace)
            locations.append(", ".join(part for part in (city, country) if part))
        remote_status = (item.findtext("remoteStatus") or "").casefold()
        offers.append(_offer(
            company, board,
            title=item.findtext("title") or "",
            url=item.findtext("link") or "",
            location="; ".join(location for location in locations if location),
            work_mode=work_mode_from_flags(remote_status in ("fully", "remote"), remote_status == "hybrid"),
            description=item.findtext("description") or "",
        ))
    return offers


def _recruitee(session, board, company, keywords):
    payload = _get_json(session, f"https://{board.key}.recruitee.com/api/offers/")
    return [
        _offer(
            company, board,
            title=job.get("title", ""),
            url=job.get("careers_url", ""),
            location=", ".join(part for part in (job.get("city"), job.get("country")) if part),
            work_mode=work_mode_from_flags(bool(job.get("remote")), bool(job.get("hybrid"))),
            description=job.get("description", "") + " " + job.get("requirements", ""),
            contracts=normalize_contracts(job.get("employment_type_code", "")),
        )
        for job in payload.get("offers", [])
    ]


def _ashby(session, board, company, keywords):
    payload = _get_json(
        session,
        f"https://api.ashbyhq.com/posting-api/job-board/{board.key}",
        params={"includeCompensation": "true"},
    )
    offers = []
    for job in payload.get("jobs", []):
        locations = [job.get("location", "")] + [item.get("location", "") for item in job.get("secondaryLocations") or []]
        workplace = str(job.get("workplaceType", "")).casefold()
        offers.append(_offer(
            company, board,
            title=job.get("title", ""),
            url=job.get("jobUrl", ""),
            location="; ".join(location for location in locations if location),
            work_mode=work_mode_from_flags(bool(job.get("isRemote")) or workplace == "remote", workplace == "hybrid"),
            description=job.get("descriptionPlain", ""),
            salary=((job.get("compensation") or {}).get("compensationTierSummary") or ""),
        ))
    return offers


def _traffit(session, board, company, keywords):
    offers = []
    page = 1
    while page <= 5:
        response = session.get(
            f"https://{board.key}.traffit.com/public/job_posts/published",
            headers={**REQUEST_HEADERS, "X-Request-Page-Size": "100", "X-Request-Current-Page": str(page)},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        jobs = response.json()
        for job in jobs:
            advert = job.get("advert") or {}
            values = {item.get("field_id"): item.get("value") for item in advert.get("values") or []}
            location = ""
            try:
                geo = json.loads(values.get("geolocation") or "{}")
                location = ", ".join(part for part in (geo.get("locality"), geo.get("country")) if part)
            except (TypeError, ValueError):
                pass
            options = job.get("options") or {}
            offers.append(_offer(
                company, board,
                title=advert.get("name", ""),
                url=job.get("url", ""),
                location=location,
                work_mode=normalize_work_mode(str(values.get("remote", "")) + " " + str(options.get("remote", ""))),
                description=str(values.get("description", "")),
                contracts=normalize_contracts(str(options.get("jobType", ""))),
            ))
        if len(jobs) < 100:
            break
        page += 1
    return offers


def _successfactors(session, board, company, keywords):
    """SAP SuccessFactors Recruiting Marketing (strony z /search/?q=)."""

    base = board.params["base"]
    offers: dict[str, JobOffer] = {}
    for keyword in PROFILE.career_search_keywords:
        for location_filter in (PROFILE.country, ""):
            found = 0
            for start_row in range(0, MAX_RESULTS_PER_KEYWORD, 25):
                params = {"q": keyword, "startrow": start_row}
                if location_filter:
                    params["locationsearch"] = location_filter
                response = session.get(f"{base}/search/?{urlencode(params)}", headers=REQUEST_HEADERS, timeout=TIMEOUT)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "lxml")
                links = soup.select("a.jobTitle-link")
                for link in links:
                    url = requests.compat.urljoin(base, link.get("href", ""))
                    row = link.find_parent(["tr", "li"]) or link.find_parent(class_=re.compile("job-tile|tile"))
                    location_node = row.select_one(".jobLocation, [class*=location]") if row else None
                    location = location_node.get_text(" ", strip=True) if location_node else ""
                    found += 1
                    offers.setdefault(url, _offer(
                        company, board,
                        title=link.get_text(" ", strip=True),
                        url=url,
                        location=location,
                    ))
                if len(links) < 10:
                    break
            if found:
                break
    for offer in offers.values():
        # Lista nie zawiera opisu - szczegóły uzupełni wzbogacanie strony oferty.
        offer.api_confirmed = False
    return list(offers.values())


def _phenom(session, board, company, keywords):
    base, prefix = board.params["base"], board.params.get("prefix") or "global/en"
    page = session.get(f"{base}/{prefix}/search-results", headers=REQUEST_HEADERS, timeout=TIMEOUT)
    page.raise_for_status()
    match = re.search(r'"refNum"\s*:\s*"([^"]+)"', page.text)
    if not match:
        raise ValueError("Phenom: brak refNum na stronie wyszukiwania")
    country, language = (prefix.split("/") + ["en"])[:2]
    offers = []
    for keyword in PROFILE.career_search_keywords:
        payload = {
            "lang": f"{language}_{country}",
            "deviceType": "desktop",
            "country": country,
            "pageName": "search-results",
            "ddoKey": "refineSearch",
            "from": 0,
            "size": MAX_RESULTS_PER_KEYWORD,
            "jobs": True,
            "counts": False,
            "all_fields": ["country", "city"],
            "clearAll": False,
            "jdsource": "facets",
            "siteType": "external",
            "keywords": keyword,
            "global": True,
            "selected_fields": {"country": [PROFILE.country]},
            "refNum": match.group(1),
            "locationData": {},
        }
        result = _post_json(session, f"{base}/widgets", payload)
        for job in ((result.get("refineSearch") or {}).get("data") or {}).get("jobs") or []:
            locations = job.get("multi_location") or [job.get("location", "")]
            offers.append(_offer(
                company, board,
                title=job.get("title", ""),
                url=f"{base}/{prefix}/job/{job.get('jobId')}",
                location="; ".join(location for location in locations if location),
                description=" ".join([job.get("descriptionTeaser", ""), ", ".join(job.get("ml_skills") or [])]),
            ))
    return offers


def _erecruiter(session, board, company, keywords):
    """Widżet eRecruiter (skk.erecruiter.pl) - ten sam endpoint, z którego korzysta strona."""

    offers = []
    page, total_pages = 1, 1
    while page <= min(total_pages, 20):
        params = {"cfg": board.key, "filters": "all", "grid": "all" if page == 1 else "rows", "jsoncallback": "cb"}
        if page > 1:
            params["pn"] = page
        response = session.get("https://skk.erecruiter.pl/GetHtml.ashx", params=params,
                               headers=REQUEST_HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        match = re.search(r"cb\((.*)\)\s*;?\s*$", response.text, re.DOTALL)
        if not match:
            raise ValueError("eRecruiter: nieoczekiwany format odpowiedzi")
        soup = BeautifulSoup(json.loads(match.group(1)).get("htm", ""), "lxml")
        rows = soup.select("tr[offerid]")
        for row in rows:
            title_cell = row.select_one(".skk_positionName") or row.find("td")
            cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td")]
            # Ostatnia kolumna to zwykle miejscowość; eRecruiter to system
            # polskich pracodawców, więc sama nazwa miasta oznacza Polskę.
            city = cells[-1] if len(cells) > 1 else ""
            offers.append(_offer(
                company, board,
                title=title_cell.get_text(" ", strip=True) if title_cell else "",
                url=f"https://skk.erecruiter.pl/Offer.aspx?oid={row['offerid']}&cfg={board.key}",
                location=f"{city}, Polska" if city and "," not in city else city,
            ))
        if not rows:
            break
        pager = soup.select_one("[tp]")
        if pager is not None and str(pager.get("tp", "")).isdigit():
            total_pages = int(pager["tp"])
        page += 1
    return offers


def _phenom_prefix(path: str) -> str:
    segments = [segment for segment in path.split("/") if segment]
    if len(segments) >= 2 and len(segments[1]) == 2:
        return f"{segments[0]}/{segments[1]}"
    return "global/en"


_FETCHERS = {
    "greenhouse": _greenhouse,
    "lever": _lever,
    "smartrecruiters": _smartrecruiters,
    "workable": _workable,
    "workday": _workday,
    "teamtailor": _teamtailor,
    "recruitee": _recruitee,
    "ashby": _ashby,
    "traffit": _traffit,
    "successfactors": _successfactors,
    "phenom": _phenom,
    "erecruiter": _erecruiter,
}

SUPPORTED_ATS = tuple(_FETCHERS)
