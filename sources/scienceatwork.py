"""
JOB HUNTER BELGIUM
SCIENCE@WORK BELGIUM - VERSION 1.1

Objectif
========
Collecter les offres publiques de Science at Work Belgique, récupérer leur
fiche détaillée, puis ne conserver que les offres FR/EN (ou ambiguës) utiles
au pipeline. Les annonces clairement néerlandophones ou exigeant explicitement
un niveau professionnel de néerlandais sont rejetées à la source.

Principes
=========
- volume faible : on peut lire les fiches détaillées de toutes les offres ;
- requests + BeautifulSoup uniquement ;
- JSON-LD JobPosting prioritaire quand présent ;
- fallback HTML visible si le JSON-LD est absent ;
- cache HTML local ;
- aucune technique de contournement anti-bot ;
- descriptions complètes disponibles dès la collecte.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from database.models import JobOffer
from sources.source_metrics import publish_metrics_from_locals


BASE_URL = "https://www.scienceatwork.be"
LIST_URL = f"{BASE_URL}/vacatures"
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAYS = (1, 2, 4)
DETAIL_DELAY_SECONDS = 0.12
MIN_DESCRIPTION_LENGTH = 120

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LIST_CACHE = PROJECT_ROOT / "logs" / "scienceatwork_listing.html"  # compatibilité V1.0 page 1
LIST_CACHE_DIR = PROJECT_ROOT / "logs" / "scienceatwork_listing_cache"
LIST_CACHE_DIR.mkdir(parents=True, exist_ok=True)
MAX_LIST_PAGES = 10
DETAIL_CACHE_DIR = PROJECT_ROOT / "logs" / "scienceatwork_detail_cache"
DETAIL_CACHE_DIR.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/151.0 Safari/537.36 Edg/151.0"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.4",
        "Cache-Control": "no-cache",
    }
)

JOB_URL_RE = re.compile(
    r"/job/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/[^?#]+",
    re.I,
)

# Marqueurs utilisés uniquement sur le texte de la fiche, pas sur le chrome du site.
NL_MARKERS = (
    r"\bje\b",
    r"\bjouw\b",
    r"\bwij\b",
    r"\bonze\b",
    r"\bvoor\b",
    r"\bzoeken\b",
    r"\bbent\b",
    r"\bhebt\b",
    r"\bbeschikt\b",
    r"\bervaring\b",
    r"\bopleiding\b",
    r"\bfunctie\b",
    r"\bvereisten\b",
    r"\baanbod\b",
    r"\bverantwoordelijkheden\b",
    r"\bwerkzaamheden\b",
    r"\bsolliciteren\b",
    r"\bklant\b",
    r"\bnederlands\b",
    r"\bkwaliteitscontrole\b",
)

FR_MARKERS = (
    r"\bvous\b",
    r"\bvotre\b",
    r"\bnous\b",
    r"\bnotre\b",
    r"\brecherchons\b",
    r"\bexp[ée]rience\b",
    r"\bdipl[oô]me\b",
    r"\bprofil\b",
    r"\bresponsabilit[ée]s\b",
    r"\bexigences\b",
    r"\boffre\b",
    r"\bposte\b",
    r"\bfran[cç]ais\b",
    r"\bcomp[ée]tences\b",
    r"\bcandidat\w*\b",
)

EN_MARKERS = (
    r"\byou\b",
    r"\byour\b",
    r"\bwe\b",
    r"\bour\b",
    r"\bexperience\b",
    r"\bdegree\b",
    r"\brequirements\b",
    r"\bresponsibilities\b",
    r"\brole\b",
    r"\bposition\b",
    r"\bcandidate\b",
    r"\benglish\b",
    r"\bskills\b",
    r"\blooking for\b",
    r"\bapply\b",
)

DUTCH_REQUIRED_PATTERNS = (
    r"\bspreekt\s+en\s+schrijft\s+vlot\s+nederlands\b",
    r"\bspreekt\s+vlot\s+nederlands\b",
    r"\bgoede\s+kennis\s+van\s+(?:het\s+)?nederlands\b",
    r"\bzeer\s+goede\s+kennis\s+van\s+(?:het\s+)?nederlands\b",
    r"\bvloeiend\s+nederlands\b",
    r"\bnederlands\s+is\s+vereist\b",
    r"\bdutch\s+is\s+required\b",
    r"\bfluent\s+(?:in\s+)?dutch\b",
    r"\bprofessional\s+(?:working\s+)?proficiency\s+in\s+dutch\b",
    r"\bexcellent\s+command\s+of\s+dutch\b",
    r"\bn[ée]erlandais\s+(?:est\s+)?(?:requis|exig[ée])\b",
    r"\bma[iî]trise\s+du\s+n[ée]erlandais\b",
)

STOP_TEXT_MARKERS = (
    "bedankt voor je interesse",
    "helaas zijn sollicitaties",
    "spontaan solliciteren",
    "twijfel je of deze job",
    "nog vragen?",
    "neem contact op",
)


def clean_text(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip()


def _normalize(value) -> str:
    return clean_text(value).lower().replace("’", "'")


def _pattern_score(text: str, patterns: tuple[str, ...]) -> int:
    low = _normalize(text)
    return sum(min(3, len(re.findall(pattern, low, flags=re.I))) for pattern in patterns)


def detect_language(text: str) -> str:
    """Retourne fr, en, nl ou unknown sur le corps réel de l'annonce."""
    sample = clean_text(text)[:15000]
    if not sample:
        return "unknown"

    nl = _pattern_score(sample, NL_MARKERS)
    fr = _pattern_score(sample, FR_MARKERS)
    en = _pattern_score(sample, EN_MARKERS)

    # NL seulement quand le signal est vraiment dominant.
    if nl >= 7 and nl >= max(fr, en) + 4:
        return "nl"
    if fr >= 4 and fr >= en:
        return "fr"
    if en >= 4:
        return "en"
    if nl >= 5 and fr <= 1 and en <= 1:
        return "nl"
    return "unknown"


def dutch_required(text: str) -> bool:
    low = _normalize(text)
    return any(re.search(pattern, low, flags=re.I) for pattern in DUTCH_REQUIRED_PATTERNS)


def _cache_key(url: str, external_id: str | None = None) -> str:
    if external_id:
        safe = re.sub(r"[^0-9A-Za-z_-]+", "_", clean_text(external_id))
        if safe:
            return safe
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:24]


def _detail_cache_path(url: str, external_id: str | None = None) -> Path:
    return DETAIL_CACHE_DIR / f"{_cache_key(url, external_id)}.html"


def _request_html(url: str) -> tuple[str | None, str | None]:
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            response = SESSION.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            html = response.text or ""
            if len(html) < 500:
                raise ValueError(f"HTML trop court ({len(html)} caractères)")
            return html, None
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAYS[attempt])
    return None, last_error


def _listing_url(page: int) -> str:
    return LIST_URL if page <= 1 else f"{LIST_URL}?page={page}"


def _listing_cache_path(page: int) -> Path:
    return LIST_CACHE_DIR / f"page_{max(1, int(page))}.html"


def _listing_html(page: int = 1, use_cache: bool = True) -> tuple[str | None, bool, str | None]:
    page = max(1, int(page))
    url = _listing_url(page)
    html, error = _request_html(url)
    cache_path = _listing_cache_path(page)

    if html:
        try:
            cache_path.write_text(html, encoding="utf-8")
            # Garde l'ancien cache page 1 pour compatibilité avec les versions précédentes.
            if page == 1:
                LIST_CACHE.parent.mkdir(parents=True, exist_ok=True)
                LIST_CACHE.write_text(html, encoding="utf-8")
        except Exception:
            pass
        return html, False, None

    if use_cache:
        candidates = [cache_path]
        if page == 1:
            candidates.append(LIST_CACHE)
        for candidate in candidates:
            if not candidate.exists():
                continue
            try:
                cached = candidate.read_text(encoding="utf-8")
                if cached:
                    return cached, True, error
            except Exception:
                pass
    return None, False, error


def _extract_max_page(html: str) -> int:
    """Détecte la pagination publique ?page=N sans dépendre du texte visible."""
    if not html:
        return 1
    pages = [1]
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a", href=True):
        href = clean_text(anchor.get("href"))
        match = re.search(r"(?:[?&])page=(\d+)(?:[&#]|$)", href, flags=re.I)
        if match:
            try:
                pages.append(int(match.group(1)))
            except Exception:
                pass
    return min(MAX_LIST_PAGES, max(pages))


def _collect_listing_links(use_cache: bool = True) -> tuple[list[dict], dict]:
    """Parcourt toutes les pages de /vacatures et fusionne les offres par UUID."""
    first_html, first_from_cache, first_error = _listing_html(page=1, use_cache=use_cache)
    if not first_html:
        return [], {"pages": 0, "from_cache_pages": 0, "errors": [first_error] if first_error else []}

    max_page = _extract_max_page(first_html)
    found: dict[str, dict] = {}
    errors: list[str] = []
    cache_pages = 0

    def merge_page(page: int, html: str, from_cache: bool) -> None:
        nonlocal cache_pages
        page_links = _extract_job_links(html)
        before = len(found)
        for item in page_links:
            current = found.get(item["external_id"])
            if current is None or len(item.get("title") or "") > len(current.get("title") or ""):
                found[item["external_id"]] = item
        if from_cache:
            cache_pages += 1
        source_label = "CACHE" if from_cache else "WEB"
        print(
            f"SCIENCE@WORK - page {page}/{max_page} : "
            f"{len(page_links)} lien(s) | +{len(found) - before} unique(s) | {source_label}"
        )

    merge_page(1, first_html, first_from_cache)

    page = 2
    # max_page peut être réévalué sur les pages suivantes si le site l'étend.
    while page <= max_page and page <= MAX_LIST_PAGES:
        html, from_cache, error = _listing_html(page=page, use_cache=use_cache)
        if not html:
            if error:
                errors.append(f"page {page}: {error}")
            print(f"SCIENCE@WORK - page {page}/{max_page} : indisponible")
            page += 1
            continue
        max_page = min(MAX_LIST_PAGES, max(max_page, _extract_max_page(html)))
        merge_page(page, html, from_cache)
        page += 1

    return list(found.values()), {
        "pages": max_page,
        "from_cache_pages": cache_pages,
        "errors": errors,
    }


def _extract_job_links(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, dict] = {}
    for anchor in soup.find_all("a", href=True):
        href = clean_text(anchor.get("href"))
        absolute = urljoin(BASE_URL, href)
        match = JOB_URL_RE.search(urlparse(absolute).path)
        if not match:
            continue
        external_id = match.group(1).lower()
        title = clean_text(anchor.get_text(" ", strip=True))
        current = found.get(external_id)
        if current is None or len(title) > len(current.get("title") or ""):
            found[external_id] = {
                "external_id": external_id,
                "url": absolute.split("#", 1)[0],
                "title": title,
            }
    return list(found.values())


def _walk_jsonld(value):
    if isinstance(value, dict):
        yield value
        graph = value.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from _walk_jsonld(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_jsonld(item)


def _jsonld_jobposting(soup: BeautifulSoup) -> dict:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        for item in _walk_jsonld(payload):
            types = item.get("@type")
            if isinstance(types, str):
                types = [types]
            if any(str(t).lower() == "jobposting" for t in (types or [])):
                return item
    return {}


def _html_to_text(value) -> str:
    if value is None:
        return ""
    return clean_text(BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True))


def _parse_location(value) -> str:
    if not value:
        return ""
    locations = value if isinstance(value, list) else [value]
    parts = []
    for loc in locations:
        if isinstance(loc, str):
            parts.append(clean_text(loc))
            continue
        if not isinstance(loc, dict):
            continue
        address = loc.get("address") or {}
        if isinstance(address, str):
            parts.append(clean_text(address))
            continue
        if isinstance(address, dict):
            for key in ("addressLocality", "addressRegion", "addressCountry"):
                text = clean_text(address.get(key))
                if text and text not in parts:
                    parts.append(text)
    return ", ".join(parts)


def _visible_detail_fallback(soup: BeautifulSoup) -> str:
    root = soup.find("main") or soup.find("article") or soup.body or soup
    pieces = []
    started = False
    for node in root.find_all(["h1", "h2", "h3", "p", "li"]):
        text = clean_text(node.get_text(" ", strip=True))
        if not text:
            continue
        if node.name == "h1":
            started = True
            continue
        if not started:
            continue
        low = text.lower()
        if any(marker in low for marker in STOP_TEXT_MARKERS):
            break
        # Évite de polluer le matching avec les micro-labels de l'interface.
        if low in {"locatie", "type werk", "solliciteer nu", "of"}:
            continue
        pieces.append(text)
    return clean_text("\n".join(pieces))


def _visible_metadata(soup: BeautifulSoup) -> dict:
    root = soup.find("main") or soup.find("article") or soup.body or soup
    lines = [clean_text(x) for x in root.stripped_strings]
    lines = [x for x in lines if x]

    def after(label: str) -> str:
        target = label.lower()
        for i, value in enumerate(lines):
            if value.lower() == target and i + 1 < len(lines):
                return lines[i + 1]
        return ""

    degrees = []
    for value in lines[:40]:
        if value in {"Secondary", "Bachelor", "Master"} and value not in degrees:
            degrees.append(value)

    category = ""
    for value in lines[:25]:
        if value in {"Lab", "QA", "Process and Manufacturing", "Sales and Customer Service", "Administration", "HR"}:
            category = value
            break

    return {
        "location": after("Locatie"),
        "work_type": after("Type werk"),
        "degree": ", ".join(degrees),
        "category": category,
    }


def parse_scienceatwork_detail(html: str, url: str, external_id: str | None = None) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    posting = _jsonld_jobposting(soup)
    visible = _visible_metadata(soup)

    h1 = soup.find("h1")
    title = clean_text(posting.get("title")) or (clean_text(h1.get_text(" ", strip=True)) if h1 else "")

    description = _html_to_text(posting.get("description"))
    if len(description) < MIN_DESCRIPTION_LENGTH:
        description = _visible_detail_fallback(soup)

    organization = posting.get("hiringOrganization") or {}
    if isinstance(organization, dict):
        company = clean_text(organization.get("name"))
    else:
        company = clean_text(organization)
    if not company:
        company = "Science at Work Belgium"

    location = _parse_location(posting.get("jobLocation")) or visible.get("location") or "Belgique"

    employment = posting.get("employmentType")
    if isinstance(employment, list):
        contract_type = ", ".join(clean_text(x) for x in employment if clean_text(x))
    else:
        contract_type = clean_text(employment)
    if not contract_type:
        contract_type = visible.get("work_type") or None

    language = detect_language(description)
    structured = {
        "external_id": external_id,
        "title": title,
        "company": company,
        "location": location,
        "contract_type": contract_type,
        "date_published": clean_text(posting.get("datePosted")) or None,
        "valid_through": clean_text(posting.get("validThrough")) or None,
        "language": language,
        "degree": visible.get("degree") or None,
        "category": visible.get("category") or None,
        "dutch_required": dutch_required(description),
        "url": url,
    }

    success = bool(title and len(description) >= MIN_DESCRIPTION_LENGTH)
    return {
        "success": success,
        "matching_text": description if success else "",
        "matching_text_length": len(description) if success else 0,
        "structured": structured,
        "from_cache": False,
        "error": None if success else f"Science@Work : fiche inexploitable ({len(description)} caractères).",
    }


def get_scienceatwork_job_detail(
    url: str,
    external_id: str | None = None,
    use_cache: bool = True,
) -> dict:
    path = _detail_cache_path(url, external_id)

    if use_cache and path.exists():
        try:
            html = path.read_text(encoding="utf-8")
            result = parse_scienceatwork_detail(html, url, external_id)
            if result.get("success"):
                result["from_cache"] = True
                return result
        except Exception:
            pass

    html, error = _request_html(url)
    if not html:
        return {
            "success": False,
            "matching_text": "",
            "matching_text_length": 0,
            "structured": {"external_id": external_id, "url": url},
            "from_cache": False,
            "error": f"Science@Work : {error or 'lecture HTTP impossible'}",
        }

    try:
        path.write_text(html, encoding="utf-8")
    except Exception:
        pass

    return parse_scienceatwork_detail(html, url, external_id)


def _job_from_detail(detail: dict, fallback: dict) -> JobOffer:
    structured = detail.get("structured") or {}
    job = JobOffer(
        source="SCIENCEATWORK",
        external_id=clean_text(structured.get("external_id") or fallback.get("external_id")),
        title=clean_text(structured.get("title") or fallback.get("title") or "Titre inconnu"),
        company=clean_text(structured.get("company") or "Science at Work Belgium"),
        location=clean_text(structured.get("location") or "Belgique"),
        description=clean_text(detail.get("matching_text")),
        url=clean_text(structured.get("url") or fallback.get("url")),
        date_published=clean_text(structured.get("date_published")) or None,
        contract_type=clean_text(structured.get("contract_type")) or None,
        language=clean_text(structured.get("language")) or None,
    )
    job.collection_channel = "SCIENCEATWORK"
    job.origin_source = "SCIENCEATWORK"
    job.detail_enrichment_attempted = True
    job.detail_enrichment_success = True
    job.detail_matching_text = job.description
    job.detail_matching_text_length = len(job.description)
    job.degree_requirement = structured.get("degree")
    job.job_category = structured.get("category")
    job.valid_through = structured.get("valid_through")
    return job



_NOISE_TITLE_PATTERNS = (
    r"\bsales\b",
    r"\baccount\s+manager\b",
    r"\brecruiter\b",
    r"\bbusiness\s+development\b",
    r"\bcommercial\b",
)

def _is_obvious_noise_title(title: str) -> bool:
    value = clean_text(title)
    return bool(value) and any(
        re.search(pattern, value, flags=re.I)
        for pattern in _NOISE_TITLE_PATTERNS
    )

def search_targeted_scienceatwork_jobs() -> list[JobOffer]:
    print("SCIENCE@WORK - collecte des offres publiques Belgique")
    links, listing_meta = _collect_listing_links(use_cache=True)
    print(
        f"SCIENCE@WORK - liens uniques détectés : {len(links)} "
        f"sur {listing_meta.get('pages', 0)} page(s)"
    )
    if listing_meta.get("errors"):
        for error in listing_meta["errors"]:
            print(f"SCIENCE@WORK - avertissement listing : {error}")
    if not links:
        raise RuntimeError("Science@Work : aucun lien /job/ détecté sur les pages des vacatures.")

    jobs = []
    errors = 0
    rejected_nl = 0
    rejected_dutch_requirement = 0
    languages: dict[str, int] = {"fr": 0, "en": 0, "unknown": 0}

    for index, item in enumerate(links, start=1):
        detail = get_scienceatwork_job_detail(
            url=item["url"],
            external_id=item["external_id"],
            use_cache=True,
        )
        structured = detail.get("structured") or {}
        title = clean_text(structured.get("title") or item.get("title") or "Titre inconnu")
        lang = clean_text(structured.get("language") or "unknown").lower()

        if not detail.get("success"):
            errors += 1
            print(f"[{index:02d}/{len(links):02d}] ❌ DETAIL | {title} | {clean_text(detail.get('error'))}")
            continue

        if lang == "nl":
            rejected_nl += 1
            print(f"[{index:02d}/{len(links):02d}] ⛔ NL     | {title}")
            continue

        if bool(structured.get("dutch_required")):
            rejected_dutch_requirement += 1
            print(f"[{index:02d}/{len(links):02d}] ⛔ DUTCH  | {title} | néerlandais professionnel requis")
            continue

        if lang not in languages:
            lang = "unknown"
        languages[lang] += 1
        job = _job_from_detail(detail, item)
        jobs.append(job)
        label = {"fr": "FR", "en": "EN", "unknown": "?"}.get(lang, "?")
        print(
            f"[{index:02d}/{len(links):02d}] ✅ {label:<2}     | "
            f"{len(job.description):4d} car. | {job.title} | {job.location}"
        )
        time.sleep(DETAIL_DELAY_SECONDS)

    print()
    print("=" * 76)
    print("                BILAN SCIENCE@WORK V1.1")
    print("=" * 76)
    print(f"Fiches détectées                  : {len(links)}")
    print(f"Conservées FR/EN/ambiguës         : {len(jobs)}")
    print(f"  Français                        : {languages['fr']}")
    print(f"  Anglais                         : {languages['en']}")
    print(f"  Langue ambiguë                  : {languages['unknown']}")
    print(f"Rejetées - fiche clairement NL    : {rejected_nl}")
    print(f"Rejetées - néerlandais requis     : {rejected_dutch_requirement}")
    print(f"Échecs détail                     : {errors}")
    # V3.8 STEP 9.7.1 - conservative returned-job noise guard
    _before_noise_guard = len(jobs)
    jobs = [job for job in jobs if not _is_obvious_noise_title(getattr(job, "title", ""))]
    _noise_guard_rejected = _before_noise_guard - len(jobs)
    if _noise_guard_rejected:
        print(f"Source noise guard - rejet évident : {_noise_guard_rejected}")
    publish_metrics_from_locals("SCIENCEATWORK", locals())
    return jobs


def collect_scienceatwork_jobs() -> list[JobOffer]:
    return search_targeted_scienceatwork_jobs()
