"""
JOB HUNTER BELGIUM
SCIENSANO - VERSION 1.3

Primary source: Sciensano's EasyToRecruit tenant through the reusable
``sources.easytorecruit`` engine. If Sciensano's host is unreachable from the
local PC, ``sources.public_search_index`` provides discovery-only rows that
remain provisional until a direct detail can be refreshed. The official HR-Technologies API returns
published vacancies plus full vacancy content once a tenant X-Client-Uuid can
be validated from public configuration (or explicit local configuration).

Fallback: legacy/editorial pages on sciensano.be.  The fallback is never used
as proof that the connector is healthy when the EasyToRecruit API itself could
not be validated, because those pages can be stale.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import re
import time
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, parse_qs, unquote

import requests
from bs4 import BeautifulSoup

from database.models import JobOffer
from sources.randstad import dutch_professional_required
from sources.scienceatwork import detect_language
from sources.public_search_index import PublicSearchIndex
from sources.easytorecruit import (
    EasyToRecruitClient,
    EasyToRecruitTenant,
    vacancy_text as e2r_vacancy_text,
    contract_summary as e2r_contract_summary,
)


# ---------------------------------------------------------------------------
# URLs / runtime
# ---------------------------------------------------------------------------

BASE_URL = "https://www.sciensano.be"
PORTAL_BASE = "https://jobs.sciensano.be"
API_BASE = "https://api.hr-technologies.com/v1"

# Legacy/editorial fallback only.
LIST_URLS = (
    ("fr", f"{BASE_URL}/fr/travailler-faire-un-stage-chez-sciensano/mes-opportunites-demploi"),
    ("en", f"{BASE_URL}/en/working-doing-internship-sciensano/my-employment-opportunities"),
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "logs" / "sciensano_cache"
LIST_CACHE_DIR = CACHE_DIR / "listing"
DETAIL_CACHE_DIR = CACHE_DIR / "detail"
UUID_CACHE = CACHE_DIR / "easytorecruit_client_uuid.txt"
SEARCH_INDEX_CACHE_DIR = CACHE_DIR / "public_search_index"
SEARCH_INDEX = PublicSearchIndex(SEARCH_INDEX_CACHE_DIR, timeout=15, max_retries=2, query_delay=0.20)

# Conservative web-index fallback. Each query remains scoped to Sciensano's
# public career host. The results are discovery only until a direct detail page
# or the official EasyToRecruit API can be read.
SEARCH_INDEX_QUERIES = (
    'site:jobs.sciensano.be/content/login.asp Sciensano jdkid',
    'site:jobs.sciensano.be/content/jobpage.asp Sciensano jdkid',
    'site:jobs.sciensano.be/front/fr/vacancies Sciensano',
    'site:jobs.sciensano.be/front/en/vacancies Sciensano',
    'site:jobs.sciensano.be Sciensano 2026 "data scientist"',
    'site:jobs.sciensano.be Sciensano 2026 "data engineer"',
    'site:jobs.sciensano.be Sciensano 2026 laboratoire',
    'site:jobs.sciensano.be Sciensano "quality control"',
    'site:jobs.sciensano.be Sciensano chimie',
)

E2R_TENANT = EasyToRecruitTenant(
    key="SCIENSANO",
    company="Sciensano",
    portal_base=PORTAL_BASE,
    languages=("fr", "en"),
    client_uuid_env="JOBHUNTER_SCIENSANO_E2R_UUID",
    cache_dir=CACHE_DIR / "easytorecruit",
    # Sciensano currently exposes both the newer /front shell and an older
    # /content EasyToRecruit interface. The generic engine checks both.
    frontend_paths=(
        "/front/fr/vacancies",
        "/front/en/vacancies",
        "/front/nl/vacancies",
        "/front/fr/users/login",
        "/front/en/users/login",
        "/front/nl/users/login",
        "/content/login.asp",
    ),
    extra_discovery_urls=(
        "/content/login.asp?l=FRENCH",
        "/content/login.asp?l=DUTCH",
    ),
    discovery_timeout=10,
    request_timeout=20,
)
E2R_CLIENT = EasyToRecruitClient(E2R_TENANT)
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAYS = (1, 2, 4)
DETAIL_DELAY_SECONDS = 0.08
MIN_DESCRIPTION_LENGTH = 180
API_PAGE_SIZE = 50
API_MAX_PAGES = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.2",
    "Cache-Control": "no-cache",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

DATE_RE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b")
VACANCY_ID_RE = re.compile(r"(?:/vacancies/|[?&]jdkid=)(\d+)", re.I)

TARGET_TITLE_PATTERNS = (
    # Laboratory / QC / analytical chemistry
    r"\blaborantin(?:e)?\b",
    r"\blaboratory\s+(?:assistant|technician|technologist|analyst|associate)\b",
    r"\blab\s+(?:assistant|technician|technologist|analyst|associate)\b",
    r"\btechnicien(?:ne)?\b.*\blaboratoire\b",
    r"\btechnologue\b.*\blaboratoire\b",
    r"\bquality\s+control\b",
    r"\bcontr[oô]le\s+qualit[eé]\b",
    r"\bqc\b",
    r"\bchimie\s+analytique\b",
    r"\banalytical\s+chemistry\b",
    r"\bscientifique\b.*\b(?:chimie|analytique|vaccin|qualit[eé]|laboratoire|g[eé]nom|microbiolog)\b",
    r"\bcollaborateur(?:rice)?\s+scientifique\b.*\b(?:chimie|analytique|vaccin|qualit[eé]|laboratoire|g[eé]nom|microbiolog)\b",
    r"\bscientific\s+(?:officer|collaborator|researcher)\b.*\b(?:chem|analyt|vaccin|quality|lab|genom|microbiolog)\b",
    # Data / statistics / epidemiology
    r"\bdata\s+scientist\b",
    r"\bdata\s+analyst\b",
    r"\bdata\s+engineer\b",
    r"\bjunior\s+data\s+(?:analyst|engineer)\b",
    r"\bresearch\s+assistant\b.*\b(?:health\s+econom|data|statistics|epidemiolog)\b",
    r"\bcollaborateur(?:rice)?\s+scientifique\b.*\b(?:donn[eé]es|data|statisti|[eé]pid[eé]miolog|[eé]conomie\s+de\s+la\s+sant[eé])\b",
    r"\bjunior\s+scientist\b.*\b(?:data|statistics|epidemiolog|health|cancer)\b",
    r"\bpower\s*bi\b",
    r"\bbusiness\s+intelligence\b",
    r"\breporting\s+analyst\b",
    r"\bdata\s+quality\b",
    r"\bdata\s+integrity\b",
)

NON_TARGET_TITLE_PATTERNS = (
    r"\b(?:senior|sr\.?|principal)\b",
    r"\bchef\s+(?:de\s+)?service\b",
    r"\bchef\s+d['’]?équipe\b",
    r"\bteam\s+lead(?:er)?\b",
    r"\b(?:director|head|manager|supervisor)\b",
    r"\barchitect\b",
    r"\bintern(?:ship)?\b",
    r"\bstage\b",
    r"\bstagiaire\b",
    r"\bstudent\b",
    r"\btrainee\b",
    r"\bdoctorat\b",
    r"\bphd\b",
    r"\bmaster\s+thesis\b",
)

GENERIC_ANCHOR_TEXT = {
    "apply", "postuler", "solliciter", "read more", "lees meer", "more", "plus",
    "jobs", "job offers", "vacatures", "postes vacants", "candidature spontanée",
    "spontaneous application", "contact", "home", "accueil", "login", "connexion",
}

CLOSED_MARKERS = (
    "this vacancy is no longer available",
    "this job is no longer available",
    "this position is no longer available",
    "vacature is niet langer beschikbaar",
    "vacature is niet meer beschikbaar",
    "cette offre n'est plus disponible",
    "cette offre n’est plus disponible",
    "ce poste n'est plus disponible",
    "ce poste n’est plus disponible",
    "cet emploi n'est pas disponible",
    "cet emploi n’est pas disponible",
    "application deadline has passed",
)


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------

def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        value = " ".join(str(x) for x in value if x is not None)
    text = html_lib.unescape(str(value)).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _norm(value: Any) -> str:
    return clean_text(value).lower().replace("’", "'")


def _hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8", errors="ignore")).hexdigest()[:24]


def _cache_path(url: str, folder: Path) -> Path:
    return folder / f"{_hash(url)}.html"


def _request_html(url: str, cache_path: Path | None = None, use_cache: bool = True):
    last_error = None
    status = None
    for attempt in range(MAX_RETRIES):
        try:
            response = SESSION.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            status = int(response.status_code)
            if status == 404:
                return "", False, "HTTP 404", status, response.url
            response.raise_for_status()
            text = response.text or ""
            if len(text) < 250:
                raise ValueError(f"HTML trop court ({len(text)} caractères)")
            if cache_path:
                try:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_text(text, encoding="utf-8")
                except Exception:
                    pass
            return text, False, None, status, response.url
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAYS[attempt])

    if use_cache and cache_path and cache_path.exists():
        try:
            cached = cache_path.read_text(encoding="utf-8", errors="ignore")
            if cached:
                return cached, True, last_error, status, url
        except Exception:
            pass
    return "", False, last_error, status, url


def _is_target_title(title: str) -> bool:
    low = _norm(title)
    if not low:
        return False
    if any(re.search(pattern, low, re.I) for pattern in NON_TARGET_TITLE_PATTERNS):
        return False
    return any(re.search(pattern, low, re.I) for pattern in TARGET_TITLE_PATTERNS)


def _html_to_text(fragment: Any) -> str:
    if fragment is None:
        return ""
    raw = str(fragment)
    return clean_text(BeautifulSoup(html_lib.unescape(raw), "html.parser").get_text(" ", strip=True))


def _first_nonempty(*values: Any) -> str:
    for value in values:
        text = clean_text(value)
        if text:
            return text
    return ""


# ---------------------------------------------------------------------------
# EasyToRecruit public API (generic engine adapter)
# ---------------------------------------------------------------------------

def discover_e2r_client_uuid(use_cache: bool = True) -> tuple[str, dict]:
    """Compatibility wrapper around the generic EasyToRecruit client."""
    return E2R_CLIENT.discover_client_uuid(use_cache=use_cache)


def _api_get(
    path: str,
    client_uuid: str,
    language: str = "fr",
    params: dict | None = None,
) -> tuple[dict | None, str | None, int | None]:
    # Keep the former Sciensano helper signature for Job Refresh code.
    if path.strip("/") == "vacancies" and params:
        return E2R_CLIENT._api_get(
            path, client_uuid, language=language, params=params, use_cache=False
        )
    if path.strip("/").startswith("vacancies/"):
        return E2R_CLIENT._api_get(path, client_uuid, language=language, use_cache=False)
    return E2R_CLIENT._api_get(path, client_uuid, language=language, params=params, use_cache=False)


def _extract_api_pages(client_uuid: str, language: str) -> tuple[list[dict], dict]:
    rows, meta = E2R_CLIENT.collect_all(
        client_uuid,
        language,
        page_size=API_PAGE_SIZE,
        max_pages=API_MAX_PAGES,
        use_cache=False,
    )
    pages = int(meta.get("pages") or 0)
    total = int(meta.get("total") or len(rows))
    if pages:
        print(
            f"SCIENSANO - API {language.upper():<2}: {len(rows):2d} offre(s) "
            f"sur {pages} page(s) | total annoncé {total}"
        )
    return rows, meta

def _api_item_text(item: dict) -> str:
    return e2r_vacancy_text(item)


def _extract_deadline(text: str) -> str:
    month_names = {
        "janvier": 1, "january": 1, "januari": 1,
        "février": 2, "fevrier": 2, "february": 2, "februari": 2,
        "mars": 3, "march": 3, "maart": 3,
        "avril": 4, "april": 4,
        "mai": 5, "may": 5, "mei": 5,
        "juin": 6, "june": 6, "juni": 6,
        "juillet": 7, "july": 7, "juli": 7,
        "août": 8, "aout": 8, "august": 8, "augustus": 8,
        "septembre": 9, "september": 9,
        "octobre": 10, "october": 10, "oktober": 10,
        "novembre": 11, "november": 11,
        "décembre": 12, "decembre": 12, "december": 12,
    }
    patterns = (
        r"(?:date\s+limite(?:\s+des?\s+candidatures?)?|application\s+deadline|closing\s+date|sollicitatie\s*deadline|uiterlijk\s+solliciteren)\s*[:\-]?\s*(?:au\s+plus\s+tard\s*(?:le|pour)?\s*)?(\d{1,2}[./-]\d{1,2}[./-](?:20)?\d{2})",
        r"(?:au\s+plus\s+tard\s+(?:le\s+)?)?(\d{1,2})\s+(janvier|january|januari|février|fevrier|february|februari|mars|march|maart|avril|april|mai|may|mei|juin|june|juni|juillet|july|juli|août|aout|august|augustus|septembre|september|octobre|october|oktober|novembre|november|décembre|decembre|december)\s+(20\d{2})",
    )
    m = re.search(patterns[0], text, re.I)
    if m:
        raw = m.group(1)
        dm = re.match(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})", raw)
        if dm:
            d, mo, y = dm.groups()
            if len(y) == 2:
                y = "20" + y
            try:
                return date(int(y), int(mo), int(d)).isoformat()
            except Exception:
                pass
    m = re.search(patterns[1], text, re.I)
    if m:
        d, month_name, y = m.groups()
        mo = month_names.get(_norm(month_name))
        if mo:
            try:
                return date(int(y), mo, int(d)).isoformat()
            except Exception:
                pass
    return ""


def _deadline_passed(value: str) -> bool:
    if not value:
        return False
    try:
        return date.fromisoformat(value) < date.today()
    except Exception:
        return False


def _dutch_required(text: str) -> bool:
    low = _norm(text)
    alternatives = (
        r"\b(?:dutch|nederlands|néerlandais|neerlandais)\b.{0,80}\b(?:or|of|ou|and/or|et/ou)\b.{0,80}\b(?:french|frans|français|francais)\b",
        r"\b(?:french|frans|français|francais)\b.{0,80}\b(?:or|of|ou|and/or|et/ou)\b.{0,80}\b(?:dutch|nederlands|néerlandais|neerlandais)\b",
    )
    if any(re.search(pattern, low, re.I) for pattern in alternatives):
        return False
    strict_local = (
        r"\b(?:excellente?|tr[eè]s\s+bonne|bonne)\s+(?:connaissance|ma[iî]trise)\b.{0,55}\b(?:du\s+)?(?:néerlandais|neerlandais)\b.{0,55}\b(?:requise?|obligatoire|indispensable)\b",
        r"\b(?:néerlandais|neerlandais)\b.{0,55}\b(?:excellente?|courant|fluent)\b.{0,55}\b(?:requis|required|obligatoire)\b",
    )
    if any(re.search(pattern, low, re.I) for pattern in strict_local):
        return True
    return dutch_professional_required(text)


def _contract_from_api(item: dict) -> str:
    return e2r_contract_summary(item)


# JOBHUNTER_SCIENSANO_PUBLIC_URL_FIX_V1
def _public_vacancy_url(vacancy_id: str, slug: str = "", language: str = "fr") -> str:
    """Build the stable public EasyToRecruit URL used by Sciensano."""
    vacancy_id = clean_text(vacancy_id)
    language_key = clean_text(language).lower()

    language_code = {
        "fr": "FRENCH",
        "fra": "FRENCH",
        "french": "FRENCH",
        "nl": "DUTCH",
        "nld": "DUTCH",
        "dutch": "DUTCH",
        "en": "ENGLISH",
        "eng": "ENGLISH",
        "english": "ENGLISH",
    }.get(language_key, "FRENCH")

    if not vacancy_id:
        return f"{PORTAL_BASE}/content/login.asp"

    return (
        f"{PORTAL_BASE}/content/login.asp"
        f"?a=APPLY&jdkid={vacancy_id}&l={language_code}"
    )


def _row_from_api_item(item: dict, language: str) -> dict:
    vacancy_id = clean_text(item.get("id"))
    title = clean_text(item.get("title") or item.get("title_internal"))
    slug = clean_text(item.get("slug"))
    matching_text = _api_item_text(item)
    deadline = _extract_deadline(matching_text)
    date_published = clean_text(item.get("created_at"))
    if date_published:
        date_published = date_published[:10]
    location = clean_text(item.get("location"))
    if not location:
        regions = item.get("regions")
        if isinstance(regions, list):
            location = ", ".join(clean_text(x) for x in regions if clean_text(x))
    location = location or "Brussels, Belgium"
    return {
        "external_id": vacancy_id,
        "sciensano_job_id": vacancy_id,
        "title": title,
        "location": location,
        "date_published": date_published,
        "contract_type": _contract_from_api(item),
        "url": _public_vacancy_url(vacancy_id, slug, language),
        "listing_language": language,
        "application_deadline": deadline,
        "api_payload": item,
        "api_slug": slug,
        "matching_text": matching_text,
    }


def _collect_api_listing_candidates(use_cache: bool = True):
    client_uuid, uuid_meta = discover_e2r_client_uuid(use_cache=use_cache)
    if not client_uuid:
        return [], {
            "all_rows": [], "jobs_seen": 0, "candidates": 0,
            "api_reachable": False, "api_total": 0,
            "client_uuid_found": False, "client_uuid_source": uuid_meta.get("source", ""),
            "uuid_meta": uuid_meta,
            "errors": list(uuid_meta.get("errors") or []),
            "listing_reachable": False,
            "mode": "easytorecruit-api",
        }

    merged: dict[str, dict] = {}
    errors: list[str] = list(uuid_meta.get("errors") or [])
    api_reachable = False
    totals: dict[str, int] = {}
    pages: dict[str, int] = {}

    # Prefer French content, then use English only to fill missing IDs / richer text.
    for language in ("fr", "en"):
        items, lang_meta = _extract_api_pages(client_uuid, language)
        api_reachable = api_reachable or bool(lang_meta.get("reachable"))
        totals[language] = int(lang_meta.get("total") or 0)
        pages[language] = int(lang_meta.get("pages") or 0)
        errors.extend(lang_meta.get("errors") or [])
        for item in items:
            row = _row_from_api_item(item, language)
            key = clean_text(row.get("external_id"))
            if not key:
                continue
            existing = merged.get(key)
            if existing is None:
                merged[key] = row
                continue
            # FR wins by default; otherwise retain the richer text.
            if existing.get("listing_language") != "fr" and language == "fr":
                merged[key] = row
            elif len(row.get("matching_text", "")) > len(existing.get("matching_text", "")) + 100:
                merged[key] = row

    rows = list(merged.values())
    rows.sort(key=lambda r: (_norm(r.get("title")), clean_text(r.get("external_id"))))
    candidates = [row for row in rows if _is_target_title(row.get("title", ""))]
    api_total = max(totals.values()) if totals else len(rows)
    return candidates, {
        "all_rows": rows,
        "jobs_seen": len(rows),
        "candidates": len(candidates),
        "api_reachable": api_reachable,
        "api_total": api_total,
        "api_totals_by_language": totals,
        "api_pages_by_language": pages,
        "client_uuid_found": True,
        "client_uuid": client_uuid,
        "client_uuid_source": uuid_meta.get("source", ""),
        "uuid_meta": uuid_meta,
        "errors": errors,
        "listing_reachable": api_reachable,
        "mode": "easytorecruit-api",
    }


# ---------------------------------------------------------------------------
# Legacy/editorial fallback (kept only as secondary discovery)
# ---------------------------------------------------------------------------

def _nearby_date(anchor) -> str:
    current = anchor
    for _ in range(6):
        parent = getattr(current, "parent", None)
        if parent is None:
            break
        current = parent
        text = clean_text(current.get_text(" ", strip=True))
        match = DATE_RE.search(text)
        if match:
            d, m, y = match.groups()
            try:
                return date(int(y), int(m), int(d)).isoformat()
            except Exception:
                return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
        if len(text) > 1200:
            break
    return ""


def _looks_like_job_link(anchor, page_url: str) -> bool:
    text = clean_text(anchor.get_text(" ", strip=True))
    if len(text) < 7 or len(text) > 220 or _norm(text) in GENERIC_ANCHOR_TEXT:
        return False
    href = clean_text(anchor.get("href"))
    if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
        return False
    absolute = urljoin(page_url, href)
    parsed = urlparse(absolute)
    low_url = absolute.lower()
    if _nearby_date(anchor):
        return True
    allowed_host = any(host in (parsed.netloc or "").lower() for host in (
        "sciensano.be", "jobs.sciensano.be", "wiv-isp.be"
    ))
    route_signal = any(token in low_url for token in (
        "/job", "/jobs/", "vacature", "vacancy", "offre", "/node/"
    ))
    return bool(allowed_host and route_signal and _is_target_title(text))


def _extract_listing_rows(html: str, page_url: str, page_language: str) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    root = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.body or soup
    rows: dict[str, dict] = {}
    for anchor in root.find_all("a", href=True):
        if not _looks_like_job_link(anchor, page_url):
            continue
        title = clean_text(anchor.get_text(" ", strip=True))
        url = urljoin(page_url, clean_text(anchor.get("href")))
        if url.split("#", 1)[0].rstrip("/") == page_url.split("#", 1)[0].rstrip("/"):
            continue
        vacancy_match = VACANCY_ID_RE.search(url)
        external_id = vacancy_match.group(1) if vacancy_match else _hash(url)
        rows[url.lower().rstrip("/")] = {
            "external_id": external_id,
            "sciensano_job_id": external_id,
            "title": title,
            "location": "Brussels, Belgium",
            "date_published": _nearby_date(anchor),
            "contract_type": "",
            "url": url,
            "listing_language": page_language,
        }
    return list(rows.values())


def _collect_legacy_editorial_rows(use_cache: bool = True) -> tuple[list[dict], dict]:
    all_rows: dict[str, dict] = {}
    errors: list[str] = []
    pages_ok = 0
    for language, url in LIST_URLS:
        html, from_cache, error, status, final_url = _request_html(
            url, _cache_path(url, LIST_CACHE_DIR), use_cache=use_cache
        )
        if not html:
            errors.append(f"legacy {language.upper()}: {error or status or 'lecture impossible'}")
            continue
        pages_ok += 1
        rows = _extract_listing_rows(html, final_url or url, language)
        print(
            f"SCIENSANO - fallback éditorial {language.upper():<2}: "
            f"{len(rows):2d} lien(s) | {'CACHE' if from_cache else 'WEB'}"
        )
        for row in rows:
            key = clean_text(row.get("external_id")) or clean_text(row.get("url"))
            if key not in all_rows:
                all_rows[key] = row
    return list(all_rows.values()), {"pages_ok": pages_ok, "errors": errors}


def _search_result_title(raw_title: str, snippet: str, url: str) -> str:
    """Recover the real vacancy title from an indexed EasyToRecruit result."""
    raw_title = clean_text(raw_title)
    snippet = clean_text(snippet)

    # New EasyToRecruit URLs often carry a human-readable title query param.
    try:
        query = parse_qs(urlparse(url).query)
        encoded_title = clean_text((query.get("title") or [""])[0])
    except Exception:
        encoded_title = ""
    if encoded_title:
        candidate = unquote(encoded_title).replace("-", " ")
        candidate = re.sub(r"\s*\(\d+\)\s*$", "", candidate)
        candidate = clean_text(candidate)
        if len(candidate) >= 5:
            return candidate

    generic = (
        not raw_title
        or "login sciensano" in _norm(raw_title)
        or "s'identifier sciensano" in _norm(raw_title)
        or "postes vacants | sciensano" in _norm(raw_title)
        or "vacatures | sciensano" in _norm(raw_title)
        or "jobpage | sciensano" in _norm(raw_title)
    )
    if not generic:
        return raw_title

    # Search snippets for legacy login/apply pages usually start with the job
    # title, followed by a standard "not available in this language" sentence.
    candidate = snippet
    for marker in (
        " Cet emploi n'est pas disponible",
        " Cet emploi n’est pas disponible",
        " Deze job is niet beschikbaar",
        " We're sorry but EasyToRecruit",
        " Description de l'emploi",
        " Job description",
        " Profile",
        " Profil",
        " L'offre",
        " We offer",
    ):
        pos = candidate.find(marker)
        if pos > 4:
            candidate = candidate[:pos]
            break
    candidate = clean_text(candidate).lstrip("#-–— ")
    if 5 <= len(candidate) <= 220:
        return candidate
    return raw_title or "Offre Sciensano"


def _is_sciensano_vacancy_url(url: str) -> bool:
    parsed = urlparse(clean_text(url))
    host = (parsed.netloc or "").lower()
    low = clean_text(url).lower()
    if host != "jobs.sciensano.be":
        return False
    return bool(VACANCY_ID_RE.search(low)) and (
        "/content/login.asp" in low
        or "/content/jobpage.asp" in low
        or "/front/" in low and "/vacancies/" in low
    )


def _row_from_search_result(result) -> dict | None:
    url = clean_text(getattr(result, "url", ""))
    if not _is_sciensano_vacancy_url(url):
        return None
    match = VACANCY_ID_RE.search(url)
    if not match:
        return None
    external_id = match.group(1)
    snippet = clean_text(getattr(result, "snippet", ""))
    title = _search_result_title(getattr(result, "title", ""), snippet, url)
    combined = clean_text(f"{title} {snippet}")
    language = detect_language(combined)
    deadline = _extract_deadline(combined)
    low = _norm(combined)
    # "Cet emploi n'est pas disponible dans cette langue" / its Dutch
    # equivalent is a language-routing message from legacy EasyToRecruit, not
    # proof that the vacancy itself is closed. Only strict closure markers are
    # accepted at discovery stage.
    search_closed_markers = (
        "this vacancy is no longer available",
        "this job is no longer available",
        "this position is no longer available",
        "vacature is niet langer beschikbaar",
        "vacature is niet meer beschikbaar",
        "cette offre n'est plus disponible",
        "cette offre n’est plus disponible",
        "ce poste n'est plus disponible",
        "ce poste n’est plus disponible",
        "application deadline has passed",
    )
    closed = any(marker in low for marker in search_closed_markers) or _deadline_passed(deadline)
    return {
        "external_id": external_id,
        "sciensano_job_id": external_id,
        "title": title,
        "location": "Brussels, Belgium",
        "date_published": "",
        "contract_type": "",
        "url": url,
        "listing_language": language if language in {"fr", "en", "nl"} else "unknown",
        "search_snippet": snippet,
        "matching_text": combined,
        "application_deadline": deadline,
        "dutch_required": _dutch_required(combined),
        "closed": closed,
        "discovery_only": True,
        "search_engine": clean_text(getattr(result, "engine", "bing")),
        "search_query": clean_text(getattr(result, "query", "")),
    }


def _collect_search_index_rows(use_cache: bool = True) -> tuple[list[dict], dict]:
    results, metas = SEARCH_INDEX.search_many(SEARCH_INDEX_QUERIES, use_cache=use_cache)
    rows_by_id: dict[str, dict] = {}
    errors: list[str] = []
    successful_queries = 0
    modes: Counter = Counter()

    for meta in metas:
        mode = clean_text(meta.get("mode"))
        if mode and mode != "failed":
            successful_queries += 1
            modes[mode] += 1
        if meta.get("error"):
            errors.append(f"index {meta.get('query')}: {meta.get('error')}")

    raw_samples: list[dict] = []
    for result in results:
        if len(raw_samples) < 12:
            normalized_url = clean_text(getattr(result, "url", ""))
            raw_url = clean_text(getattr(result, "raw_url", "")) or normalized_url
            raw_samples.append({
                "title": clean_text(getattr(result, "title", "")),
                "raw_url": raw_url,
                "normalized_url": normalized_url,
                "accepted_sciensano": _is_sciensano_vacancy_url(normalized_url),
                "engine": clean_text(getattr(result, "engine", "")),
                "query": clean_text(getattr(result, "query", "")),
            })
        row = _row_from_search_result(result)
        if not row:
            continue
        key = row["external_id"]
        existing = rows_by_id.get(key)
        if existing is None or len(row.get("matching_text", "")) > len(existing.get("matching_text", "")):
            rows_by_id[key] = row

    rows = list(rows_by_id.values())
    rows.sort(key=lambda r: (_norm(r.get("title")), clean_text(r.get("external_id"))))
    return rows, {
        "reachable": successful_queries > 0,
        "queries_ok": successful_queries,
        "queries_total": len(SEARCH_INDEX_QUERIES),
        "modes": dict(modes),
        "results_raw": len(results),
        "rows": len(rows),
        "raw_samples": raw_samples,
        "errors": errors,
    }


def collect_sciensano_listing_candidates(use_cache: bool = True):
    candidates, meta = _collect_api_listing_candidates(use_cache=use_cache)
    if meta.get("api_reachable"):
        return candidates, meta

    # If Sciensano's own host is unreachable from the local PC, keep discovery
    # alive through the public web index. These rows are explicitly provisional
    # until a direct detail page or the official API can be read.
    index_rows, index_meta = _collect_search_index_rows(use_cache=use_cache)
    if index_meta.get("reachable"):
        candidates = [
            row for row in index_rows
            if _is_target_title(row.get("title", "")) and not row.get("closed")
        ]
        meta["all_rows"] = index_rows
        meta["jobs_seen"] = len(index_rows)
        meta["candidates"] = len(candidates)
        meta["search_index_reachable"] = True
        meta["search_index_meta"] = index_meta
        meta["errors"].extend(index_meta.get("errors") or [])
        meta["listing_reachable"] = True
        meta["mode"] = "search-index-provisional"
        return candidates, meta

    # Editorial pages remain a last diagnostic fallback only.
    legacy_rows, legacy_meta = _collect_legacy_editorial_rows(use_cache=use_cache)
    for row in legacy_rows:
        row["fallback_only"] = True
    legacy_candidates = [row for row in legacy_rows if _is_target_title(row.get("title", ""))]
    meta["all_rows"] = legacy_rows
    meta["jobs_seen"] = len(legacy_rows)
    meta["candidates"] = len(legacy_candidates)
    meta["fallback_pages_ok"] = legacy_meta.get("pages_ok", 0)
    meta["search_index_reachable"] = False
    meta["search_index_meta"] = index_meta
    meta["errors"].extend(index_meta.get("errors") or [])
    meta["errors"].extend(legacy_meta.get("errors") or [])
    meta["mode"] = "legacy-fallback-unvalidated"
    return legacy_candidates, meta


# ---------------------------------------------------------------------------
# Details / Job Refresh
# ---------------------------------------------------------------------------

def _vacancy_id_from_inputs(url: str, external_id: str | None, fallback: dict) -> str:
    ext = clean_text(external_id or fallback.get("sciensano_job_id") or fallback.get("external_id"))
    if ext.isdigit():
        return ext
    match = VACANCY_ID_RE.search(clean_text(url or fallback.get("url")))
    return match.group(1) if match else ""


def _detail_from_api_item(item: dict, language: str, fallback: dict) -> dict:
    row = _row_from_api_item(item, language)
    text = row.get("matching_text", "")
    language_detected = detect_language(text)
    dutch_required = _dutch_required(text)
    deadline = row.get("application_deadline", "") or _extract_deadline(text)
    closed = _deadline_passed(deadline)
    structured = {
        **fallback,
        **row,
        "company": "Sciensano",
        "language": language_detected,
        "dutch_required": dutch_required,
        "closed": closed,
    }
    if closed:
        return {
            "success": False, "closed": True, "matching_text": text,
            "matching_text_length": len(text), "structured": structured,
            "from_cache": False, "error": "Sciensano : deadline dépassée."
        }
    if len(text) < MIN_DESCRIPTION_LENGTH:
        return {
            "success": False, "closed": False, "matching_text": text,
            "matching_text_length": len(text), "structured": structured,
            "from_cache": False,
            "error": f"Sciensano : description API trop courte ({len(text)} caractères)."
        }
    return {
        "success": True, "closed": False, "matching_text": text,
        "matching_text_length": len(text), "structured": structured,
        "from_cache": False, "error": None,
    }


def _visible_job_text(soup: BeautifulSoup) -> str:
    root = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.body or soup
    clone = BeautifulSoup(str(root), "html.parser")
    for tag in clone.find_all(["script", "style", "noscript", "svg", "form", "nav", "footer", "header"]):
        tag.decompose()
    return clean_text(clone.get_text(" ", strip=True))


def get_sciensano_job_detail(
    url: str = "",
    external_id: str | None = None,
    use_cache: bool = True,
    fallback: dict | None = None,
) -> dict:
    fallback = dict(fallback or {})
    if external_id:
        fallback.setdefault("external_id", clean_text(external_id))
    url = clean_text(url or fallback.get("url"))
    vacancy_id = _vacancy_id_from_inputs(url, external_id, fallback)

    # If the listing already supplied a full API payload, use it only as a
    # fallback.  Job Refresh should still hit the detail endpoint when possible.
    listing_payload = fallback.get("api_payload") if isinstance(fallback.get("api_payload"), dict) else None

    if vacancy_id:
        client_uuid, uuid_meta = discover_e2r_client_uuid(use_cache=use_cache)
        if client_uuid:
            preferred = clean_text(fallback.get("listing_language")).lower()
            languages = [preferred] if preferred in {"fr", "en"} else []
            for candidate in ("fr", "en"):
                if candidate not in languages:
                    languages.append(candidate)
            api_errors: list[str] = []
            for language in languages:
                payload, error, status = _api_get(f"vacancies/{vacancy_id}", client_uuid, language)
                if status == 404:
                    return {
                        "success": False, "closed": True, "matching_text": "", "matching_text_length": 0,
                        "structured": {**fallback, "external_id": vacancy_id, "sciensano_job_id": vacancy_id},
                        "from_cache": False, "error": "Sciensano : offre absente de l'API / clôturée."
                    }
                if payload and isinstance(payload.get("data"), dict):
                    return _detail_from_api_item(payload["data"], language, fallback)
                api_errors.append(f"{language}: {error or status}")
            if listing_payload:
                result = _detail_from_api_item(
                    listing_payload,
                    clean_text(fallback.get("listing_language")) or "fr",
                    fallback,
                )
                if result.get("success") or result.get("closed"):
                    result["error"] = result.get("error")
                    return result
            return {
                "success": False, "closed": False, "matching_text": "", "matching_text_length": 0,
                "structured": fallback, "from_cache": False,
                "error": "Sciensano API détail : " + "; ".join(api_errors or uuid_meta.get("errors") or ["échec inconnu"]),
            }
        elif listing_payload:
            return _detail_from_api_item(
                listing_payload,
                clean_text(fallback.get("listing_language")) or "fr",
                fallback,
            )

    # Last-resort legacy public HTML detail path.
    if not url:
        return {
            "success": False, "closed": False, "matching_text": "", "matching_text_length": 0,
            "structured": fallback, "from_cache": False, "error": "Sciensano : URL / ID manquant."
        }
    html, from_cache, error, status, final_url = _request_html(
        url, _cache_path(url, DETAIL_CACHE_DIR), use_cache=use_cache
    )
    if status == 404:
        return {
            "success": False, "closed": True, "matching_text": "", "matching_text_length": 0,
            "structured": {**fallback, "url": url}, "from_cache": from_cache,
            "error": "Sciensano : HTTP 404 / offre probablement clôturée."
        }
    if not html:
        fallback_text = clean_text(fallback.get("matching_text") or fallback.get("search_snippet"))
        deadline = clean_text(fallback.get("application_deadline")) or _extract_deadline(fallback_text)
        closed = bool(fallback.get("closed")) or _deadline_passed(deadline)
        structured = {
            **fallback,
            "external_id": vacancy_id or clean_text(fallback.get("external_id")),
            "sciensano_job_id": vacancy_id or clean_text(fallback.get("external_id")),
            "company": "Sciensano",
            "url": url,
            "language": clean_text(fallback.get("listing_language")) or detect_language(fallback_text),
            "dutch_required": bool(fallback.get("dutch_required")) or _dutch_required(fallback_text),
            "application_deadline": deadline,
            "closed": closed,
            "discovery_only": bool(fallback.get("discovery_only")),
        }
        return {
            "success": False, "closed": closed, "matching_text": fallback_text,
            "matching_text_length": len(fallback_text), "structured": structured,
            "from_cache": from_cache,
            "provisional": bool(fallback_text) and not closed,
            "error": f"Sciensano : {error or 'lecture détail impossible'}"
        }
    soup = BeautifulSoup(html, "html.parser")
    visible = _visible_job_text(soup)
    low = _norm(visible)
    closed = any(marker in low for marker in CLOSED_MARKERS)
    title = clean_text((soup.find("h1") or soup.find("h2") or {}).get_text(" ", strip=True)) if (soup.find("h1") or soup.find("h2")) else clean_text(fallback.get("title"))
    login_only = (
        ("gebruikersnaam" in low and "paswoord" in low and "aanmelden" in low)
        or ("username" in low and "password" in low and len(visible) < 1400)
    )
    structured = {
        **fallback,
        "external_id": vacancy_id or clean_text(fallback.get("external_id")) or _hash(final_url or url),
        "sciensano_job_id": vacancy_id or clean_text(fallback.get("external_id")),
        "title": title,
        "company": "Sciensano",
        "url": final_url or url,
        "language": detect_language(visible),
        "dutch_required": _dutch_required(visible),
        "application_deadline": _extract_deadline(visible),
        "closed": closed,
    }
    if closed:
        return {"success": False, "closed": True, "matching_text": visible, "matching_text_length": len(visible), "structured": structured, "from_cache": from_cache, "error": "Sciensano : offre clôturée."}
    if login_only:
        return {"success": False, "closed": False, "matching_text": visible, "matching_text_length": len(visible), "structured": structured, "from_cache": from_cache, "error": "Sciensano : page de login EasyToRecruit, API publique non résolue."}
    if len(visible) < MIN_DESCRIPTION_LENGTH:
        return {"success": False, "closed": False, "matching_text": visible, "matching_text_length": len(visible), "structured": structured, "from_cache": from_cache, "error": f"Sciensano : description trop courte ({len(visible)} caractères)."}
    return {"success": True, "closed": False, "matching_text": visible, "matching_text_length": len(visible), "structured": structured, "from_cache": from_cache, "error": None}


def _job_from_detail(detail: dict, fallback: dict) -> JobOffer:
    structured = detail.get("structured") or {}
    description = clean_text(detail.get("matching_text"))
    job = JobOffer(
        source="SCIENSANO",
        external_id=clean_text(structured.get("external_id") or fallback.get("external_id")),
        title=clean_text(structured.get("title") or fallback.get("title") or "Titre inconnu"),
        company="Sciensano",
        location=clean_text(structured.get("location") or fallback.get("location") or "Brussels, Belgium"),
        description=description,
        url=clean_text(structured.get("url") or fallback.get("url")),
        date_published=clean_text(structured.get("date_published") or fallback.get("date_published")) or None,
        contract_type=clean_text(structured.get("contract_type") or fallback.get("contract_type")) or None,
        language=clean_text(structured.get("language")) or None,
    )
    job.collection_channel = "SCIENSANO"
    job.origin_source = "SCIENSANO"
    job.detail_enrichment_attempted = True
    job.detail_enrichment_success = True
    job.detail_matching_text = description
    job.detail_matching_text_length = len(description)
    job.sciensano_job_id = clean_text(structured.get("sciensano_job_id") or job.external_id)
    job.application_deadline = clean_text(structured.get("application_deadline"))
    return job


def _job_from_provisional(detail: dict, fallback: dict) -> JobOffer:
    structured = detail.get("structured") or {}
    description = clean_text(
        detail.get("matching_text")
        or structured.get("matching_text")
        or fallback.get("matching_text")
        or fallback.get("search_snippet")
    )
    job = JobOffer(
        source="SCIENSANO",
        external_id=clean_text(structured.get("external_id") or fallback.get("external_id")),
        title=clean_text(structured.get("title") or fallback.get("title") or "Titre inconnu"),
        company="Sciensano",
        location=clean_text(structured.get("location") or fallback.get("location") or "Brussels, Belgium"),
        description=description,
        url=clean_text(structured.get("url") or fallback.get("url")),
        date_published=clean_text(structured.get("date_published") or fallback.get("date_published")) or None,
        contract_type=clean_text(structured.get("contract_type") or fallback.get("contract_type")) or None,
        language=clean_text(structured.get("language") or fallback.get("listing_language")) or None,
    )
    job.collection_channel = "SCIENSANO"
    job.origin_source = "SCIENSANO"
    job.detail_enrichment_attempted = True
    job.detail_enrichment_success = False
    job.detail_matching_text = description
    job.detail_matching_text_length = len(description)
    job.sciensano_job_id = clean_text(structured.get("sciensano_job_id") or job.external_id)
    job.application_deadline = clean_text(structured.get("application_deadline") or fallback.get("application_deadline"))
    job.sciensano_discovery_only = True
    job.sciensano_search_snippet = clean_text(fallback.get("search_snippet"))
    job.sciensano_search_engine = clean_text(fallback.get("search_engine"))
    return job


def collect_sciensano_jobs() -> list[JobOffer]:
    candidates, meta = collect_sciensano_listing_candidates(use_cache=True)
    print(
        "SCIENSANO - préfiltre : "
        f"{meta.get('jobs_seen', 0)} offre(s) publique(s), "
        f"{len(candidates)} candidate(s) métier | mode={meta.get('mode')}"
    )
    for error in meta.get("errors") or []:
        print(f"SCIENSANO - avertissement : {error}")

    api_mode = bool(meta.get("api_reachable"))
    index_mode = bool(meta.get("search_index_reachable"))
    if not api_mode and not index_mode:
        print("SCIENSANO - ni API EasyToRecruit ni index public validé : collecte principale ignorée.")
        return []

    jobs: list[JobOffer] = []
    rejected_nl = 0
    rejected_dutch = 0
    closed = 0
    detail_errors = 0
    provisional = 0

    for index, item in enumerate(candidates, start=1):
        detail = get_sciensano_job_detail(
            url=item.get("url", ""), external_id=item.get("external_id"),
            use_cache=True, fallback=item,
        )
        st = detail.get("structured") or {}
        title = clean_text(st.get("title") or item.get("title"))
        if detail.get("closed"):
            closed += 1
            print(f"[{index:02d}/{len(candidates):02d}] 💤 CLOSED | {title}")
            continue

        language = clean_text(st.get("language") or item.get("listing_language")).lower() or "unknown"
        evidence_text = clean_text(detail.get("matching_text") or item.get("matching_text") or item.get("search_snippet"))
        if language == "unknown" and evidence_text:
            language = detect_language(evidence_text)
        dutch_required = bool(st.get("dutch_required")) or _dutch_required(evidence_text)

        if language == "nl":
            rejected_nl += 1
            print(f"[{index:02d}/{len(candidates):02d}] ⛔ NL     | {title}")
            continue
        if dutch_required:
            rejected_dutch += 1
            print(f"[{index:02d}/{len(candidates):02d}] ⛔ DUTCH  | {title} | néerlandais professionnel requis")
            continue

        if detail.get("success"):
            jobs.append(_job_from_detail(detail, item))
            print(
                f"[{index:02d}/{len(candidates):02d}] ✅ {language.upper():<7} | "
                f"{int(detail.get('matching_text_length') or 0):4d} car. | {title} | {clean_text(st.get('location'))}"
            )
        elif index_mode and evidence_text:
            # Discovery-only rows are intentionally kept as provisional. The
            # matcher already maps detail_enrichment_success=False to a LOW /
            # provisional score and the application gate forces VERIFY.
            provisional += 1
            jobs.append(_job_from_provisional(detail, item))
            print(
                f"[{index:02d}/{len(candidates):02d}] ⚠️ PROV   | "
                f"{len(evidence_text):4d} car. index | {title} | détail direct indisponible"
            )
        else:
            detail_errors += 1
            print(f"[{index:02d}/{len(candidates):02d}] ⚠️ DETAIL | {title} | {detail.get('error')}")

        if DETAIL_DELAY_SECONDS:
            time.sleep(DETAIL_DELAY_SECONDS)

    print(
        "SCIENSANO - bilan : "
        f"{len(jobs)} conservée(s), dont {provisional} provisoire(s), "
        f"{rejected_nl} NL, {rejected_dutch} Dutch requis, "
        f"{closed} clôturée(s), {detail_errors} erreur(s) détail"
    )
    return jobs


# JOBHUNTER_UNIFIED_DISCOVERY_DETAIL_V1
from sources.unified_discovery import matches_master_title

_ud_original__is_target_title = _is_target_title

def _is_target_title(*args, **kwargs):
    if _ud_original__is_target_title(*args, **kwargs):
        return True
    try:
        title = args[0] if args else kwargs.get('title', '')
    except Exception:
        return False
    return matches_master_title(title)
