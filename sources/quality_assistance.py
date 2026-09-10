"""
JOB HUNTER BELGIUM
QUALITY ASSISTANCE - VERSION 1.0

Direct-employer collector for Quality Assistance's public career site:
https://www.quality-assistance.com/en/jobs

Principles
==========
- small public catalogue: crawl all listing pages, then open only target roles;
- strict direct-site URLs (/en/jobs/<id>-<slug>);
- full-detail parsing with JSON-LD first and visible HTML fallback;
- CLOSED detection for stale job pages;
- French/English accepted, clear Dutch or professional Dutch requirement rejected;
- no anti-bot circumvention.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from database.models import JobOffer
from sources.randstad import dutch_professional_required
from sources.scienceatwork import detect_language
from sources.source_metrics import publish_metrics_from_locals


BASE_URL = "https://www.quality-assistance.com"
LIST_URL = f"{BASE_URL}/en/jobs"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "logs" / "quality_assistance_cache"
LIST_CACHE_DIR = CACHE_DIR / "listing"
DETAIL_CACHE_DIR = CACHE_DIR / "detail"
MAX_PAGES = 10
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAYS = (1, 2, 4)
DETAIL_DELAY_SECONDS = 0.08
MIN_DESCRIPTION_LENGTH = 160

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.3",
    "Cache-Control": "no-cache",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

JOB_URL_RE = re.compile(r"^/en/jobs/(\d+)-[^/?#]+/?$", re.I)
PAGE_URL_RE = re.compile(r"^/en/jobs/p(\d+)/?$", re.I)

TARGET_TITLE_PATTERNS = (
    '\\blab\\s+engineer\\b',
    '\\blaboratory\\s+(?:analyst|technician|engineer|associate|scientist)\\b',
    '\\blab(?:oratory)?\\s+(?:analyst|technician|engineer|associate|scientist)\\b',
    '\\banalytical\\s+chemistry\\s+engineer\\b',
    '\\banalytical\\s+(?:analyst|technician|scientist|chemist)\\b',
    '\\bchemist\\b',
    '\\bchemistry\\b',
    '\\bphysico[-\\s]?chemistry\\b',
    '\\bchromatograph(?:y|ic)\\b',
    '\\bhplc\\b',
    '\\blc[-\\s]?ms\\b',
    '\\bmass\\s+spectrometr(?:y|ist)\\b',
    '\\bcapillary\\s+electrophoresis\\b',
    '\\bcell\\s+culture\\b',
    '\\bbioassay\\b',
    '\\bmicrobiology\\b',
    '\\bquality\\s+control\\b',
    '\\bqc\\b.*\\b(?:analyst|technician|associate|specialist|officer)\\b',
    '\\bqa\\b.*\\b(?:analyst|technician|associate|specialist|officer)\\b',
    '\\bquality\\s+assurance\\b',
    '\\btalent\\s+pool\\b.*\\b(?:chromatography|electrophoresis|laboratory|analytical|bioassay)\\b',
    '\\bjunior\\s+data\\s+analyst\\b',
    '\\bdata\\s+analyst\\b',
    '\\bbusiness\\s+analyst\\b',
    '\\bdata\\s+quality\\b',
    '\\bdata\\s+integrity\\b',
    '\\bmaster\\s+data\\b',
    '\\breporting\\s+analyst\\b',
    '\\bpower\\s*bi\\b',
    '\\bbi\\s+(?:analyst|developer)\\b',
    '\\bbusiness\\s+intelligence\\b',
    '\\btechnicien(?:ne)?\\s+(?:de\\s+)?laboratoire\\b',
    '\\bcontr[oô]le\\s+qualit[eé]\\b',
    '\\bassurance\\s+qualit[eé]\\b',
    '\\banalyste\\s+(?:de\\s+)?laboratoire\\b',
    '\\banalyste\\s+(?:qc|qualit[eé])\\b',
    '\\btechnicien(?:ne)?\\s+chimiste\\b',
    '\\banalyste\\s+(?:de\\s+)?donn[eé]es\\b',
    '\\banalyste\\s+fonctionnel(?:le)?\\b',
    '\\banalyste\\s+bi\\b',
    '\\bd[eé]veloppeur\\s+power\\s*bi\\b',
)

NON_TARGET_TITLE_PATTERNS = (
    r"\bteam\s+leader\b",
    r"\bproject\s+leader\b",
    r"\b(?:director|head|vice president|vp)\b",
    r"\b(?:senior|sr\.?|lead|principal)\b",
    r"\bmanager\b",
    r"\breceptionist\b",
    r"\bmarketing\b",
    r"\bcommercial\b",
    r"\bbusiness\s+developer\b",
    r"\bkey\s+account\b",
    r"\bcleaning\s+operator\b",
    r"\bintern(?:ship)?\b",
    r"\bstage\b",
    r"\btrainee\b",
    r"\bstudent\b",
    r"\bspontaneous\s+application\b",
)

CLOSED_MARKERS = (
    "this job is no longer available",
    "this position is no longer available",
    "job is no longer available",
    "position is no longer available",
    "this job has been filled",
    "offre n'est plus disponible",
    "offre n’est plus disponible",
    "poste n'est plus disponible",
    "poste n’est plus disponible",
)


def clean_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        value = " ".join(str(x) for x in value if x is not None)
    text = html_lib.unescape(str(value)).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _norm(value) -> str:
    return clean_text(value).lower().replace("’", "'")


def _is_target_title(title: str) -> bool:
    low = _norm(title)
    if not low:
        return False
    if any(re.search(pattern, low, re.I) for pattern in NON_TARGET_TITLE_PATTERNS):
        return False
    return any(re.search(pattern, low, re.I) for pattern in TARGET_TITLE_PATTERNS)


def _listing_url(page: int) -> str:
    return LIST_URL if page <= 1 else f"{LIST_URL}/p{page}"


def _cache_path(url: str, folder: Path) -> Path:
    digest = hashlib.sha1(url.encode("utf-8", errors="ignore")).hexdigest()[:20]
    return folder / f"{digest}.html"


def _request_html(url: str, cache_path: Path | None = None, use_cache: bool = True):
    last_error = None
    status = None
    for attempt in range(MAX_RETRIES):
        try:
            response = SESSION.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            status = int(response.status_code)
            if status == 404:
                return "", False, "HTTP 404", status
            response.raise_for_status()
            text = response.text or ""
            if len(text) < 500:
                raise ValueError(f"HTML trop court ({len(text)} caractères)")
            if cache_path:
                try:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_text(text, encoding="utf-8")
                except Exception:
                    pass
            return text, False, None, status
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAYS[attempt])

    if use_cache and cache_path and cache_path.exists():
        try:
            cached = cache_path.read_text(encoding="utf-8", errors="ignore")
            if cached:
                return cached, True, last_error, status
        except Exception:
            pass
    return "", False, last_error, status


def _extract_announced_total(html: str) -> int | None:
    text = clean_text(BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True))
    m = re.search(r"\b(\d+)\s+jobs?\s+available\b", text, re.I)
    return int(m.group(1)) if m else None


def _extract_max_page(html: str) -> int:
    soup = BeautifulSoup(html or "", "html.parser")
    pages = [1]
    for anchor in soup.find_all("a", href=True):
        path = urlparse(urljoin(BASE_URL, clean_text(anchor.get("href")))).path.rstrip("/")
        match = PAGE_URL_RE.match(path)
        if match:
            try:
                pages.append(int(match.group(1)))
            except Exception:
                pass
    return min(MAX_PAGES, max(pages))


def _nearest_card(anchor):
    current = anchor
    for _ in range(7):
        parent = getattr(current, "parent", None)
        if parent is None:
            break
        current = parent
        text = clean_text(current.get_text(" ", strip=True))
        if len(text) > 1800:
            break
        urls = set()
        for a in current.find_all("a", href=True):
            path = urlparse(urljoin(BASE_URL, clean_text(a.get("href")))).path.rstrip("/")
            if JOB_URL_RE.match(path):
                urls.add(path)
        if len(urls) == 1 and ("contract type" in text.lower() or "location" in text.lower()):
            return current
    return None


def _extract_card_metadata(card_text: str) -> tuple[str, str, str]:
    text = clean_text(card_text)
    contract = ""
    duration = ""
    location = ""

    m = re.search(r"Contract\s+type\s+(.+?)(?=\s+Duration\b|\s+Location\b|$)", text, re.I)
    if m:
        contract = clean_text(m.group(1))
    m = re.search(r"Duration\s+(.+?)(?=\s+Location\b|$)", text, re.I)
    if m:
        duration = clean_text(m.group(1))
    m = re.search(r"Location\s+(.+?)$", text, re.I)
    if m:
        location = clean_text(m.group(1))

    if contract and duration and duration.lower() not in contract.lower():
        contract = f"{contract} — {duration}"
    return contract, duration, location


def _extract_listing_rows(html: str) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    found: dict[str, dict] = {}

    for anchor in soup.find_all("a", href=True):
        absolute = urljoin(BASE_URL, clean_text(anchor.get("href")))
        parsed = urlparse(absolute)
        if parsed.netloc.lower() not in {"www.quality-assistance.com", "quality-assistance.com"}:
            continue
        path = parsed.path.rstrip("/")
        match = JOB_URL_RE.match(path)
        if not match:
            continue
        external_id = match.group(1)
        title = clean_text(anchor.get_text(" ", strip=True))
        if not title or title.lower() in {"apply", "apply now", "join us now"}:
            continue

        card = _nearest_card(anchor)
        contract = duration = location = ""
        if card is not None:
            contract, duration, location = _extract_card_metadata(card.get_text(" ", strip=True))

        current = found.get(external_id)
        item = {
            "external_id": external_id,
            "title": title,
            "company": "Quality Assistance",
            "location": location or "Thuin, Belgium",
            "contract_type": contract,
            "duration": duration,
            "url": absolute.split("#", 1)[0],
            "date_published": "",
        }
        if current is None or len(title) > len(current.get("title", "")):
            found[external_id] = item

    return list(found.values())


def collect_quality_assistance_listing_candidates(use_cache: bool = True) -> tuple[list[dict], dict]:
    print("QUALITY ASSISTANCE - collecte directe via site carrière officiel")
    all_rows: dict[str, dict] = {}
    errors: list[str] = []
    cache_pages = 0
    first_total = None

    first_url = _listing_url(1)
    first_html, from_cache, error, _ = _request_html(
        first_url,
        _cache_path(first_url, LIST_CACHE_DIR),
        use_cache=use_cache,
    )
    if not first_html:
        return [], {
            "all_rows": [],
            "jobs_seen": 0,
            "candidates": 0,
            "pages": 0,
            "announced_total": None,
            "errors": [error or "listing inaccessible"],
            "cache_pages": 0,
            "listing_reachable": False,
        }

    first_total = _extract_announced_total(first_html)
    max_page = _extract_max_page(first_html)

    page = 1
    while page <= max_page and page <= MAX_PAGES:
        url = _listing_url(page)
        if page == 1:
            html, page_cache, page_error = first_html, from_cache, error
        else:
            html, page_cache, page_error, _ = _request_html(
                url,
                _cache_path(url, LIST_CACHE_DIR),
                use_cache=use_cache,
            )
        if not html:
            errors.append(f"page {page}: {page_error or 'réponse vide'}")
            print(f"QUALITY ASSISTANCE - page {page}/{max_page}: indisponible")
            page += 1
            continue

        max_page = min(MAX_PAGES, max(max_page, _extract_max_page(html)))
        rows = _extract_listing_rows(html)
        before = len(all_rows)
        for row in rows:
            key = clean_text(row.get("external_id")) or clean_text(row.get("url"))
            if key and key not in all_rows:
                all_rows[key] = row
        if page_cache:
            cache_pages += 1
        print(
            f"QUALITY ASSISTANCE - page {page}/{max_page}: {len(rows):2d} offre(s) | "
            f"+{len(all_rows)-before:2d} unique(s) | {'CACHE' if page_cache else 'WEB'}"
        )
        page += 1

    rows = list(all_rows.values())
    candidates = [row for row in rows if _is_target_title(row.get("title", ""))]
    candidates.sort(key=lambda row: (_norm(row.get("title")), row.get("external_id", "")))
    return candidates, {
        "all_rows": rows,
        "jobs_seen": len(rows),
        "candidates": len(candidates),
        "pages": max_page,
        "announced_total": first_total,
        "errors": errors,
        "cache_pages": cache_pages,
        "listing_reachable": True,
    }


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


def _jobposting_jsonld(soup: BeautifulSoup) -> dict:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        for item in _walk_jsonld(payload):
            typ = item.get("@type")
            if typ == "JobPosting" or (isinstance(typ, list) and "JobPosting" in typ):
                return item
    return {}


def _jsonld_location(data: dict) -> str:
    loc = data.get("jobLocation")
    if isinstance(loc, list):
        loc = loc[0] if loc else None
    if not isinstance(loc, dict):
        return ""
    address = loc.get("address")
    if isinstance(address, dict):
        parts = [address.get("addressLocality"), address.get("addressRegion"), address.get("addressCountry")]
        return clean_text(", ".join(clean_text(p) for p in parts if clean_text(p)))
    return clean_text(loc.get("name"))


def _html_to_text(fragment: str) -> str:
    return clean_text(BeautifulSoup(fragment or "", "html.parser").get_text(" ", strip=True))


def _visible_job_text(soup: BeautifulSoup) -> str:
    root = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.body or soup
    # Clone by parsing only the root HTML so we can safely remove chrome nodes.
    clone = BeautifulSoup(str(root), "html.parser")
    for tag in clone.find_all(["script", "style", "noscript", "svg", "form", "nav", "footer", "header"]):
        tag.decompose()
    text = clean_text(clone.get_text(" ", strip=True))
    # Start at the h1 title when possible; this cuts breadcrumb noise.
    h1 = clone.find("h1")
    if h1:
        title = clean_text(h1.get_text(" ", strip=True))
        pos = text.lower().find(title.lower()) if title else -1
        if pos >= 0:
            text = text[pos:]
    return text


def _detail_fields_from_visible(text: str) -> tuple[str, str]:
    location = ""
    contract = ""
    m = re.search(r"\bLocation\s+(.+?)(?=\s+Contract\s+type\b|\s+Share\b|\s+Download\b|\s+Your\s+next\s+challenge\b|$)", text, re.I)
    if m:
        location = clean_text(m.group(1))
    m = re.search(r"\bContract\s+type\s+(.+?)(?=\s+Share\b|\s+Download\b|\s+Your\s+next\s+challenge\b|$)", text, re.I)
    if m:
        contract = clean_text(m.group(1))
    return location, contract


def get_quality_assistance_job_detail(
    url: str = "",
    external_id: str | None = None,
    use_cache: bool = True,
    fallback: dict | None = None,
) -> dict:
    fallback = dict(fallback or {})
    if external_id:
        fallback.setdefault("external_id", clean_text(external_id))
    if not url:
        url = clean_text(fallback.get("url"))
    if not url:
        return {
            "success": False,
            "closed": False,
            "matching_text": "",
            "matching_text_length": 0,
            "structured": fallback,
            "from_cache": False,
            "error": "Quality Assistance : URL manquante.",
        }

    html, from_cache, error, status = _request_html(
        url,
        _cache_path(url, DETAIL_CACHE_DIR),
        use_cache=use_cache,
    )
    if status == 404:
        structured = dict(fallback)
        structured["url"] = url
        return {
            "success": False,
            "closed": True,
            "matching_text": "",
            "matching_text_length": 0,
            "structured": structured,
            "from_cache": from_cache,
            "error": "Quality Assistance : HTTP 404 / offre probablement clôturée.",
        }
    if not html:
        return {
            "success": False,
            "closed": False,
            "matching_text": "",
            "matching_text_length": 0,
            "structured": fallback,
            "from_cache": from_cache,
            "error": f"Quality Assistance : {error or 'lecture détail impossible'}",
        }

    soup = BeautifulSoup(html, "html.parser")
    visible = _visible_job_text(soup)
    low = _norm(visible)
    closed = any(marker in low for marker in CLOSED_MARKERS)

    jsonld = _jobposting_jsonld(soup)
    title = clean_text(jsonld.get("title") or jsonld.get("name"))
    if not title:
        h1 = soup.find("h1")
        title = clean_text(h1.get_text(" ", strip=True)) if h1 else clean_text(fallback.get("title"))

    description = _html_to_text(jsonld.get("description")) if jsonld else ""
    if len(description) < MIN_DESCRIPTION_LENGTH:
        description = visible

    visible_location, visible_contract = _detail_fields_from_visible(visible)
    location = _jsonld_location(jsonld) or visible_location or clean_text(fallback.get("location")) or "Thuin, Belgium"
    contract_type = clean_text(jsonld.get("employmentType")) or visible_contract or clean_text(fallback.get("contract_type"))
    date_published = clean_text(jsonld.get("datePosted")) or clean_text(fallback.get("date_published"))

    parsed = urlparse(url)
    match = JOB_URL_RE.match(parsed.path.rstrip("/"))
    ext_id = clean_text(external_id or fallback.get("external_id") or (match.group(1) if match else ""))

    language = detect_language(description)
    dutch_required = dutch_professional_required(description)
    structured = {
        **fallback,
        "external_id": ext_id,
        "quality_assistance_job_id": ext_id,
        "title": title,
        "company": "Quality Assistance",
        "location": location,
        "contract_type": contract_type,
        "date_published": date_published,
        "url": url,
        "language": language,
        "dutch_required": dutch_required,
        "closed": closed,
    }

    if closed:
        return {
            "success": False,
            "closed": True,
            "matching_text": description,
            "matching_text_length": len(description),
            "structured": structured,
            "from_cache": from_cache,
            "error": "Quality Assistance : offre clôturée.",
        }

    if len(description) < MIN_DESCRIPTION_LENGTH:
        return {
            "success": False,
            "closed": False,
            "matching_text": description,
            "matching_text_length": len(description),
            "structured": structured,
            "from_cache": from_cache,
            "error": f"Quality Assistance : description trop courte ({len(description)} caractères).",
        }

    return {
        "success": True,
        "closed": False,
        "matching_text": description,
        "matching_text_length": len(description),
        "structured": structured,
        "from_cache": from_cache,
        "error": None,
    }


def _job_from_detail(detail: dict, fallback: dict) -> JobOffer:
    structured = detail.get("structured") or {}
    description = clean_text(detail.get("matching_text"))
    job = JobOffer(
        source="QUALITY_ASSISTANCE",
        external_id=clean_text(structured.get("external_id") or fallback.get("external_id")),
        title=clean_text(structured.get("title") or fallback.get("title") or "Titre inconnu"),
        company="Quality Assistance",
        location=clean_text(structured.get("location") or fallback.get("location") or "Thuin, Belgium"),
        description=description,
        url=clean_text(structured.get("url") or fallback.get("url")),
        date_published=clean_text(structured.get("date_published") or fallback.get("date_published")) or None,
        contract_type=clean_text(structured.get("contract_type") or fallback.get("contract_type")) or None,
        language=clean_text(structured.get("language")) or None,
    )
    job.collection_channel = "QUALITY_ASSISTANCE"
    job.origin_source = "QUALITY_ASSISTANCE"
    job.detail_enrichment_attempted = True
    job.detail_enrichment_success = True
    job.detail_matching_text = description
    job.detail_matching_text_length = len(description)
    job.quality_assistance_job_id = clean_text(structured.get("quality_assistance_job_id") or job.external_id)
    return job


def collect_quality_assistance_jobs() -> list[JobOffer]:
    candidates, meta = collect_quality_assistance_listing_candidates(use_cache=True)
    print(
        "QUALITY ASSISTANCE - préfiltre : "
        f"{meta.get('jobs_seen', 0)} offre(s) publique(s), "
        f"{len(candidates)} candidate(s) métier"
    )
    for error in meta.get("errors") or []:
        print(f"QUALITY ASSISTANCE - avertissement : {error}")

    jobs: list[JobOffer] = []
    rejected_nl = 0
    rejected_dutch = 0
    closed = 0
    detail_errors = 0
    languages = {"fr": 0, "en": 0, "unknown": 0}

    for index, item in enumerate(candidates, start=1):
        detail = get_quality_assistance_job_detail(
            url=item.get("url", ""),
            external_id=item.get("external_id"),
            use_cache=True,
            fallback=item,
        )
        structured = detail.get("structured") or {}
        title = clean_text(structured.get("title") or item.get("title"))
        if detail.get("closed"):
            closed += 1
            print(f"[{index:02d}/{len(candidates):02d}] 💤 CLOSED | {title}")
            continue
        if not detail.get("success"):
            detail_errors += 1
            print(f"[{index:02d}/{len(candidates):02d}] ⚠️ DETAIL | {title} | {detail.get('error')}")
            continue

        language = clean_text(structured.get("language")).lower() or "unknown"
        if language == "nl":
            rejected_nl += 1
            print(f"[{index:02d}/{len(candidates):02d}] ⛔ NL     | {title}")
            continue
        if structured.get("dutch_required"):
            rejected_dutch += 1
            print(f"[{index:02d}/{len(candidates):02d}] ⛔ DUTCH  | {title} | néerlandais professionnel requis")
            continue

        language_key = language if language in languages else "unknown"
        languages[language_key] += 1
        job = _job_from_detail(detail, item)
        jobs.append(job)
        print(
            f"[{index:02d}/{len(candidates):02d}] ✅ {language.upper():<7} | "
            f"{len(job.description):4d} car. | {job.title} | {job.location}"
        )
        time.sleep(DETAIL_DELAY_SECONDS)

    print()
    print("=" * 76)
    print("              BILAN QUALITY ASSISTANCE V1.0")
    print("=" * 76)
    print(f"Offres publiques détectées          : {meta.get('jobs_seen', 0)}")
    print(f"Candidates métier préfiltrées       : {len(candidates)}")
    print(f"Conservées FR/EN/ambiguës           : {len(jobs)}")
    print(f"  Français                          : {languages['fr']}")
    print(f"  Anglais                           : {languages['en']}")
    print(f"  Langue ambiguë                    : {languages['unknown']}")
    print(f"Rejetées - fiche clairement NL      : {rejected_nl}")
    print(f"Rejetées - néerlandais requis       : {rejected_dutch}")
    print(f"Clôturées / 404                     : {closed}")
    print(f"Échecs détail                       : {detail_errors}")
    publish_metrics_from_locals("QUALITY_ASSISTANCE", locals())
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
