"""
JOBHUNTER - BATCH 2 EMPLOYER ENGINE V1.0

Shadow engine for direct employer sources discovered in Batch 2.
No registry wiring here.

SuccessFactors employers reuse the existing SuccessFactorsClient for HTTP
session/detail cache. Umicore uses its official public job-finder.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from database.models import JobOffer
from sources.belgium_locations import BELGIUM, FOREIGN, UNKNOWN, classify_belgium_location
from sources.successfactors import SuccessFactorsClient

try:
    from sources.source_metrics import publish_metrics_from_locals
except Exception:
    def publish_metrics_from_locals(*args, **kwargs):
        return None


ENGINE_VERSION = "1.0"
ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = ROOT / "logs" / "batch2_direct_employers"

TARGET_PATTERNS = [
    # Lab / QC / pharma / chemistry
    r"\bqc\b",
    r"\bquality control\b",
    r"\bquality assurance\b",
    r"\bquality analyst\b",
    r"\bquality technician\b",
    r"\bquality specialist\b",
    r"\bquality officer\b",
    r"\bcontr[oô]le qualit[eé]\b",
    r"\bassurance qualit[eé]\b",
    r"\btechnicien(?:ne)?\s+(?:de\s+)?laboratoire\b",
    r"\btechnicien(?:ne)?\s+labo\b",
    r"\blab(?:oratory)?\s+technician\b",
    r"\blab(?:oratory)?\s+analyst\b",
    r"\blab\s+assistant\b",
    r"\blaborantin(?:e)?\b",
    r"\banalyste\s+(?:de\s+)?laboratoire\b",
    r"\banalytical\s+(?:scientist|analyst)\b",
    r"\bchemist\b",
    r"\bchimiste\b",
    r"\bmicrobiolog",
    r"\bformulation\b",
    r"\bhplc\b",
    r"\blc[- ]?ms\b",
    r"\bsample management\b",
    r"\bdata integrity\b",
    r"\bgmp\b",
    # Data / BI / Business
    r"\bdata analyst\b",
    r"\banalyste de donn[eé]es\b",
    r"\bbusiness analyst\b",
    r"\banalyste fonctionnel(?:le)?\b",
    r"\bbi analyst\b",
    r"\bbusiness intelligence\b",
    r"\bpower\s*bi\b",
    r"\breporting analyst\b",
    r"\bdata quality\b",
    r"\bmaster data\b",
    r"\bdata steward\b",
]

EXCLUDE_TITLE_PATTERNS = [
    r"\bsenior\b",
    r"\bsr\.?\b",
    r"\bprincipal\b",
    r"\bstaff\b",
    r"\bdirector\b",
    r"\bhead\b",
    r"\bmanager\b",
    r"\bteam lead\b",
    r"\bsupervisor\b",
    r"\bintern(?:ship)?\b",
    r"\bstage\b",
    r"\bstagiaire\b",
    r"\btrainee\b",
    r"\bapprentice\b",
    r"\bgraduate program\b",
    r"\bphd\b",
    r"\bdoctorat\b",
    r"\bsales\b",
    r"\baccount manager\b",
]

DUTCH_HARD_PATTERNS = [
    r"\bfluent\s+dutch\b",
    r"\bprofessional\s+dutch\b",
    r"\bdutch\s+(?:is\s+)?required\b",
    r"\bgoede\s+kennis\s+(?:van\s+het\s+)?nederlands\b",
    r"\bzeer\s+goede\s+kennis\s+(?:van\s+het\s+)?nederlands\b",
    r"\bnederlands\s+(?:is\s+)?vereist\b",
    r"\bvloeiend\s+nederlands\b",
    r"\btweetalig\b",
    r"\bma[iî]trise\s+du\s+n[eé]erlandais\b",
    r"\bn[eé]erlandais\s+(?:est\s+)?(?:exig[eé]|requis)\b",
    r"\bbilingue\s+(?:fr\s*[/+-]\s*nl|fran[cç]ais\s*[/+-]\s*n[eé]erlandais)\b",
]

OPTIONAL_DUTCH_MARKERS = [
    "asset", "plus", "preferred", "preference", "nice to have",
    "atout", "souhaité", "souhaite", "pluspunt", "préféré",
]

OR_DUTCH_PATTERNS = [
    r"\bfrench\s+or\s+dutch\b",
    r"\bdutch\s+or\s+french\b",
    r"\bfran[cç]ais\s+ou\s+n[eé]erlandais\b",
    r"\bn[eé]erlandais\s+ou\s+fran[cç]ais\b",
    r"\bnederlands\s+of\s+frans\b",
    r"\bfrans\s+of\s+nederlands\b",
]


@dataclass(frozen=True)
class EmployerConfig:
    key: str
    label: str
    company: str
    kind: str
    base_url: str
    listing_url: str
    job_href_re: str
    max_pages: int = 12
    page_size: int = 20


def clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value) -> str:
    text = clean(value).lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text


def title_is_target(title: str) -> bool:
    title = clean(title)
    if not title:
        return False
    if any(re.search(p, title, re.I) for p in EXCLUDE_TITLE_PATTERNS):
        return False
    return any(re.search(p, title, re.I) for p in TARGET_PATTERNS)


def _sentence_chunks(text: str) -> list[str]:
    return [
        clean(x)
        for x in re.split(r"(?<=[.!?;:])\s+|[\r\n•●▪◦]+", str(text or ""))
        if clean(x)
    ]


def dutch_requirement_is_hard(text: str) -> bool:
    low = norm(text)
    if any(re.search(p, low, re.I) for p in OR_DUTCH_PATTERNS):
        return False

    for sentence in _sentence_chunks(text):
        s = norm(sentence)
        if not any(re.search(p, s, re.I) for p in DUTCH_HARD_PATTERNS):
            continue
        if any(marker in s for marker in OPTIONAL_DUTCH_MARKERS):
            continue
        return True
    return False


def infer_language(html_text: str, visible: str) -> str | None:
    soup = BeautifulSoup(html_text or "", "html.parser")
    html_tag = soup.find("html")
    lang = clean(html_tag.get("lang") if html_tag else "").lower()
    if lang.startswith("nl"):
        return "nl"
    if lang.startswith("fr"):
        return "fr"
    if lang.startswith("en"):
        return "en"

    n = " " + norm(visible) + " "
    nl_hits = sum(n.count(f" {w} ") for w in [" wij ", " jouw ", " onze ", " functie ", " ervaring ", " nederlands "])
    fr_hits = sum(n.count(f" {w} ") for w in [" nous ", " votre ", " expérience ", " fonction ", " français "])
    en_hits = sum(n.count(f" {w} ") for w in [" we ", " your ", " experience ", " role ", " english "])

    best = max((nl_hits, "nl"), (fr_hits, "fr"), (en_hits, "en"))
    if best[0] >= 3:
        return best[1]
    return None


def extract_external_id(url: str, kind: str) -> str:
    if kind == "UMICORE":
        m = re.search(r"/job-finder/(\d+)-", url, re.I)
        if m:
            return m.group(1)

    m = re.search(r"/(\d{7,})/?(?:\?.*)?$", url)
    if m:
        return m.group(1)

    m = re.search(r"/job/[^?#]+/(\d+)/?", url, re.I)
    if m:
        return m.group(1)

    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]


def extract_rows(base_url: str, html_text: str, href_re: str) -> list[dict]:
    soup = BeautifulSoup(html_text or "", "html.parser")
    pattern = re.compile(href_re, re.I)
    rows = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = clean(a.get("href"))
        if not href or not pattern.search(href):
            continue

        url = urljoin(base_url, href).split("#", 1)[0]
        if url in seen:
            continue
        seen.add(url)

        title = clean(a.get_text(" ", strip=True))
        tr = a.find_parent("tr")
        location = ""

        if tr:
            cells = [clean(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
            cells = [x for x in cells if x]
            if cells:
                # Find the first cell that looks geographic.
                for cell in cells:
                    d = classify_belgium_location(cell)
                    if d.status in {BELGIUM, FOREIGN}:
                        location = cell
                        break

        if not title:
            parent = a.find_parent(["li", "article", "div"])
            if parent:
                title = clean(parent.get_text(" ", strip=True))[:240]

        rows.append({
            "title": title[:240],
            "location": location[:280],
            "url": url,
        })
    return rows


def _add_query(url: str, **params) -> str:
    parsed = urlparse(url)
    query = list(parse_qsl(parsed.query, keep_blank_values=True))
    existing = {k for k, _ in query}
    for key, value in params.items():
        query = [(k, v) for k, v in query if k != key]
        query.append((key, str(value)))
    return urlunparse(parsed._replace(query=urlencode(query)))


def _sf_client(config: EmployerConfig) -> SuccessFactorsClient:
    return SuccessFactorsClient(
        base_url=config.base_url,
        all_jobs_path="search",
        cache_dir=CACHE_ROOT / config.key.lower(),
        page_size=config.page_size,
        timeout=30,
    )


def fetch_successfactors_listing(config: EmployerConfig) -> list[dict]:
    client = _sf_client(config)
    client.warmup()
    rows = []
    seen = set()
    empty_streak = 0

    for page in range(config.max_pages):
        offset = page * config.page_size
        url = _add_query(
            config.listing_url,
            q="",
            startrow=offset,
            sortColumn="referencedate",
            sortDirection="desc",
        )
        try:
            response = client.session.get(url, timeout=30, allow_redirects=True)
            response.raise_for_status()
            page_rows = extract_rows(response.url, response.text or "", config.job_href_re)
        except Exception:
            page_rows = []

        new_count = 0
        for row in page_rows:
            if row["url"] in seen:
                continue
            seen.add(row["url"])
            rows.append(row)
            new_count += 1

        if new_count == 0:
            empty_streak += 1
        else:
            empty_streak = 0

        if empty_streak >= 2:
            break

    return rows


def fetch_umicore_listing(config: EmployerConfig) -> list[dict]:
    session = requests.Session()
    session.headers.update(_sf_client(
        EmployerConfig(
            key="TMP",
            label="TMP",
            company="TMP",
            kind="SUCCESSFACTORS",
            base_url=config.base_url,
            listing_url=config.listing_url,
            job_href_re=config.job_href_re,
        )
    ).session.headers)

    rows = []
    seen = set()
    empty_streak = 0

    for page in range(1, config.max_pages + 1):
        url = _add_query(config.listing_url, p=page)
        try:
            response = session.get(url, timeout=30, allow_redirects=True)
            response.raise_for_status()
            page_rows = extract_rows(response.url, response.text or "", config.job_href_re)
        except Exception:
            page_rows = []

        new_count = 0
        for row in page_rows:
            if row["url"] in seen:
                continue
            seen.add(row["url"])
            rows.append(row)
            new_count += 1

        if new_count == 0:
            empty_streak += 1
        else:
            empty_streak = 0

        if empty_streak >= 2:
            break

    return rows


def extract_location(soup: BeautifulSoup, fallback: str = "") -> str:
    # JSON-LD JobPosting first.
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            import json
            obj = json.loads(raw)
        except Exception:
            continue

        stack = obj if isinstance(obj, list) else [obj]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
                continue
            if not isinstance(item, dict):
                continue
            if item.get("@type") == "JobPosting":
                locs = item.get("jobLocation")
                locs = locs if isinstance(locs, list) else ([locs] if locs else [])
                pieces = []
                for loc in locs:
                    if not isinstance(loc, dict):
                        continue
                    address = loc.get("address")
                    if isinstance(address, dict):
                        for key in ["postalCode", "addressLocality", "addressRegion", "addressCountry"]:
                            value = address.get(key)
                            if isinstance(value, dict):
                                value = value.get("name")
                            value = clean(value)
                            if value and value not in pieces:
                                pieces.append(value)
                    name = clean(loc.get("name"))
                    if name and name not in pieces:
                        pieces.append(name)
                if pieces:
                    return ", ".join(pieces)
            stack.extend(item.values())

    # Structured DOM location.
    selectors = [
        '[itemprop="jobLocation"]',
        '[itemprop="addressLocality"]',
        '[class*="job-location"]',
        '[class*="jobLocation"]',
        '[class~="location"]',
        '[id*="location"]',
    ]
    candidates = []
    for selector in selectors:
        try:
            for node in soup.select(selector):
                value = clean(node.get("content") or node.get_text(" ", strip=True))
                if value and len(value) < 300:
                    candidates.append(value)
        except Exception:
            pass

    # Prefer candidates the central geo classifier can decide.
    for value in candidates:
        d = classify_belgium_location(value)
        if d.status in {BELGIUM, FOREIGN}:
            return value

    # Labelled text.
    visible_lines = [clean(x) for x in soup.stripped_strings if clean(x)]
    text = "\n".join(visible_lines)
    patterns = [
        r"(?:^|\n)Location\s*[:\-]\s*([^\n]{2,220})",
        r"(?:^|\n)Job Location\s*[:\-]\s*([^\n]{2,220})",
        r"(?:^|\n)Primary Location\s*[:\-]\s*([^\n]{2,220})",
        r"(?:^|\n)Lieu\s*[:\-]\s*([^\n]{2,220})",
        r"(?:^|\n)Plaats\s*[:\-]\s*([^\n]{2,220})",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            return clean(m.group(1))

    return clean(fallback)


def extract_detail_text(html_text: str) -> tuple[str, str, str | None]:
    soup = BeautifulSoup(html_text or "", "html.parser")

    for node in soup(["script", "style", "noscript", "svg"]):
        node.decompose()

    title = ""
    h1 = soup.find("h1")
    if h1:
        title = clean(h1.get_text(" ", strip=True))

    candidates = []
    selectors = [
        '[itemprop="description"]',
        ".jobdescription",
        ".job-description",
        ".jobDescription",
        "#job-description",
        ".job",
        "main",
    ]
    for selector in selectors:
        try:
            for node in soup.select(selector):
                value = clean(node.get_text(" ", strip=True))
                if len(value) >= 300:
                    candidates.append(value)
        except Exception:
            pass

    if candidates:
        description = max(candidates, key=len)
    else:
        description = clean(soup.get_text(" ", strip=True))

    language = infer_language(html_text, description)
    return title, description, language


def fetch_detail(config: EmployerConfig, row: dict) -> dict:
    external_id = extract_external_id(row["url"], config.kind)

    if config.kind == "SUCCESSFACTORS":
        client = _sf_client(config)
        html_text, from_cache, error = client.detail_html(
            row["url"], external_id=external_id, use_cache=True
        )
        if not html_text:
            return {"success": False, "error": error or "detail unavailable"}
    else:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/152 Safari/537.36",
            "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8",
        })
        try:
            response = session.get(row["url"], timeout=30, allow_redirects=True)
            response.raise_for_status()
            html_text = response.text or ""
            from_cache = False
        except Exception as exc:
            return {"success": False, "error": f"{type(exc).__name__}: {exc}"}

    soup = BeautifulSoup(html_text, "html.parser")
    detail_title, description, language = extract_detail_text(html_text)
    location = extract_location(soup, fallback=row.get("location") or "")

    return {
        "success": len(description) >= 250,
        "external_id": external_id,
        "title": detail_title or row.get("title") or "Titre inconnu",
        "description": description,
        "location": location,
        "language": language,
        "url": row["url"],
        "from_cache": bool(from_cache),
        "error": None if len(description) >= 250 else f"description too short ({len(description)})",
    }


def collect_employer(config: EmployerConfig) -> list[JobOffer]:
    if config.kind == "SUCCESSFACTORS":
        all_rows = fetch_successfactors_listing(config)
    elif config.kind == "UMICORE":
        all_rows = fetch_umicore_listing(config)
    else:
        raise ValueError(f"Unsupported employer kind: {config.kind}")

    seen = len(all_rows)
    candidate_rows = [row for row in all_rows if title_is_target(row.get("title") or "")]
    candidates = len(candidate_rows)

    jobs: list[JobOffer] = []
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    detail_errors = 0

    for row in candidate_rows:
        # If listing location explicitly says foreign, no need to open detail.
        listing_geo = classify_belgium_location(row.get("location") or "")
        if listing_geo.status == FOREIGN:
            rejected_geo += 1
            continue

        detail = fetch_detail(config, row)
        if not detail.get("success"):
            detail_errors += 1
            continue

        geo = classify_belgium_location(detail.get("location") or "")
        if geo.status != BELGIUM:
            rejected_geo += 1
            continue

        description = clean(detail.get("description"))
        language = clean(detail.get("language")).lower() or None

        if language == "nl" or dutch_requirement_is_hard(description):
            rejected_language += 1
            continue

        job = JobOffer(
            source=config.key,
            external_id=clean(detail.get("external_id")),
            title=clean(detail.get("title")),
            company=config.company,
            location=clean(detail.get("location")),
            description=description,
            url=clean(detail.get("url")),
            date_published=None,
            contract_type=None,
            language=language,
        )
        job.collection_channel = config.key
        job.origin_source = config.key
        job.detail_enrichment_success = True
        job.detail_matching_text_length = len(description)
        job.detail_from_cache = bool(detail.get("from_cache"))
        jobs.append(job)

    # STEP9.4.1-compatible detailed metrics.
    publish_metrics_from_locals(config.key, locals())

    # Batch 2 explicit metrics contract.
    # source_metrics.publish_metrics_from_locals() was originally written
    # around older connector-local variable names. These new generic
    # connectors publish the canonical fields explicitly so the runtime
    # source-yield table never degrades to n/a/None.
    try:
        from sources import source_metrics as _source_metrics

        _metrics_key = str(config.key or "").upper().strip()
        _metrics_payload = {
            "seen": int(seen),
            "candidates": int(candidates),
            "kept": int(len(jobs)),
            "non_target": max(0, int(seen) - int(candidates)),
            "rejected_language": int(rejected_language),
            "rejected_geo": int(rejected_geo),
            "closed": int(closed),
            "detail_errors": int(detail_errors),
        }

        _store = getattr(_source_metrics, "_STORE", None)
        if isinstance(_store, dict):
            _store[_metrics_key] = dict(_metrics_payload)
    except Exception:
        # Metrics must never break collection. The dedicated diagnostic
        # detects publication failures before a real MAIN is allowed.
        pass

    print()
    print("=" * 84)
    print(f"{config.label.upper()} - SHADOW CONNECTOR")
    print("=" * 84)
    print("seen              :", seen)
    print("candidates        :", candidates)
    print("kept              :", len(jobs))
    print("rejected_geo      :", rejected_geo)
    print("rejected_language :", rejected_language)
    print("detail_errors     :", detail_errors)
    for job in jobs:
        print("KEEP |", job.title, "|", job.location)

    return jobs


# JOBHUNTER_UNIFIED_DISCOVERY_DETAIL_V1
from sources.unified_discovery import matches_master_title

_ud_original_title_is_target = title_is_target

def title_is_target(*args, **kwargs):
    if _ud_original_title_is_target(*args, **kwargs):
        return True
    try:
        title = args[0] if args else kwargs.get('title', '')
    except Exception:
        return False
    return matches_master_title(title)
