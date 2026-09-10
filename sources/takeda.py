"""
JOB HUNTER BELGIUM
TAKEDA BELGIUM - VERSION 1.3

Direct-employer collector for Takeda's current public careers site:
https://jobs.takeda.com/

Why this connector does NOT use Workday listings:
- Takeda's public Workday CXS listing endpoint currently returns HTTP 422
  for requests that work on other Workday tenants (GSK/Pfizer).
- Takeda's official public career site exposes the Belgium catalogue and
  full job pages server-side, while the Apply button may still point to
  Workday.

No authentication bypass or anti-bot circumvention is used.
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


BASE_URL = "https://jobs.takeda.com"
BELGIUM_LIST_URLS = (
    "https://jobs.takeda.com/en/location/belgium-jobs/1113/2802361/2/1",
    "https://jobs.takeda.com/location/belgium-jobs/1113/2802361/2/1",
    # Fallback plus strict: Takeda Belgium's manufacturing site is in Lessines.
    "https://jobs.takeda.com/location/lessines-jobs/1113/2802361-3337387-2792567/4",
    "https://jobs.takeda.com/en/location/lessines-jobs/1113/2802361-3337387-2792567/4",
)
BELGIUM_CITY_SLUGS = {"lessines"}

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "logs" / "takeda_public_cache"
LIST_CACHE = CACHE_DIR / "belgium_listing.html"
DETAIL_DELAY_SECONDS = 0.10
MIN_DESCRIPTION_LENGTH = 220

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0 Safari/537.36"
    ),
    "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8",
}

TARGET_TITLE_PATTERNS = (
    '\\btechnicien(?:ne)?\\s+chimiste\\b',
    '\\bpurification\\s+technician\\b',
    '\\bqualification\\s+technician\\b',
    '\\bproduction\\s+technician\\b',
    '\\bprocess\\s+technician\\b',
    '\\bmanufacturing\\s+technician\\b',
    '\\btechnicien(?:ne)?\\s+(?:de\\s+)?production\\b',
    '\\bqc\\s+(?:analyst|technician|specialist|associate|officer)\\b',
    '\\bquality\\s+control\\s+(?:analyst|technician|specialist|associate|officer)\\b',
    '\\bqa\\s+(?:analyst|technician|specialist|associate|officer)\\b',
    '\\bqa\\s+ops\\s+specialist\\b',
    '\\blab(?:oratory)?\\s+(?:technician|analyst|associate|specialist)\\b',
    '\\btechnicien(?:ne)?\\s+(?:de\\s+)?laboratoire\\b',
    '\\btechnicien(?:ne)?\\s+(?:qa|qc|qualit[eé])\\b',
    '\\blaborantin(?:e)?\\b',
    '\\banalytical\\s+(?:technician|analyst|scientist)\\b',
    '\\bmicrobiology\\s+(?:technician|analyst|scientist)\\b',
    '\\bem\\s+analyst\\b',
    '\\benvironmental\\s+monitoring\\b',
    '\\bdata\\s+integrity\\b',
    '\\bjunior\\s+data\\s+analyst\\b',
    '\\bdata\\s+analyst\\b',
    '\\bbusiness\\s+data\\s+analyst\\b',
    '\\bbusiness\\s+analyst\\b',
    '\\bdata\\s+quality\\b',
    '\\bdata\\s+steward\\b',
    '\\bmaster\\s+data\\b',
    '\\breporting\\s+analyst\\b',
    '\\bpower\\s*bi\\b',
    '\\bbi\\s+(?:analyst|developer)\\b',
    '\\bbusiness\\s+intelligence\\b',
    '\\bjunior\\s+mes\\s+engineer\\b',
    '\\bcontr[oô]le\\s+qualit[eé]\\b',
    '\\bassurance\\s+qualit[eé]\\b',
    '\\banalyste\\s+(?:de\\s+)?laboratoire\\b',
    '\\banalyste\\s+(?:qc|qualit[eé])\\b',
    '\\banalyste\\s+(?:de\\s+)?donn[eé]es\\b',
    '\\banalyste\\s+fonctionnel(?:le)?\\b',
    '\\banalyste\\s+bi\\b',
    '\\bd[eé]veloppeur\\s+power\\s*bi\\b',
)

NON_TARGET_TITLE_PATTERNS = (
    r"\b(?:director|head|vice president|vp)\b",
    r"\b(?:senior|sr\.?|lead|principal)\b",
    r"\bmanager\b",
    r"\bteam\s+leader\b",
    r"\bintern(?:ship)?\b",
    r"\bstage\b",
    r"\bstagiair\b",
    r"\bbachelorstage\b",
    r"\bmasterproef\b",
    r"\bthesis\b",
    r"\bgraduate\b",
    r"\bapprentice(?:ship)?\b",
    r"\btrainee\b",
    r"\bstudent\b",
)

CLOSED_MARKERS = (
    "job is no longer available",
    "position is no longer available",
    "job you are trying to access is no longer available",
    "this job has been filled",
    "page not found",
    "404 not found",
)


def clean_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        value = " ".join(str(x) for x in value if x is not None)
    text = html_lib.unescape(str(value))
    text = text.replace("\xa0", " ")
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


def _cache_path_for_url(url: str) -> Path:
    digest = hashlib.sha1(url.encode("utf-8", errors="ignore")).hexdigest()[:18]
    return CACHE_DIR / f"detail_{digest}.html"


def _request_html(url: str, cache_path: Path | None = None, use_cache: bool = True):
    if use_cache and cache_path and cache_path.exists():
        try:
            return cache_path.read_text(encoding="utf-8", errors="ignore"), True, None, 200
        except Exception:
            pass

    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        response = session.get(url, timeout=25, allow_redirects=True)
        status = int(response.status_code)
        if status == 404:
            return "", False, "HTTP 404 - offre introuvable / probablement clôturée", status
        response.raise_for_status()
        text = response.text or ""
        if cache_path and text:
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(text, encoding="utf-8")
            except Exception:
                pass
        return text, False, None, status
    except requests.HTTPError as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        return "", False, f"HTTPError: {exc}", status
    except Exception as exc:
        return "", False, f"{type(exc).__name__}: {exc}", None


def _listing_scope(html: str) -> tuple[int | None, str]:
    """Return the announced result count and geographic scope of a TalentBrew listing."""
    text = clean_text(BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True))
    m = re.search(r"\b(\d+)\s+result\(s\)\s+found\s+for\s+(Belgium|Lessines)\b", text, re.I)
    if not m:
        return None, ""
    return int(m.group(1)), clean_text(m.group(2))


def _listing_html(use_cache: bool = True):
    errors = []
    # Never trust an arbitrary 200 page here: TalentBrew can redirect an old
    # location URL to the global search page. We only accept a page that still
    # announces a Belgium/Lessines-scoped result set.
    for idx, url in enumerate(BELGIUM_LIST_URLS):
        cache_path = LIST_CACHE if idx == 0 else CACHE_DIR / f"belgium_listing_{idx+1}.html"
        html, from_cache, error, status = _request_html(url, cache_path, use_cache=use_cache)
        if not html:
            errors.append(f"{url}: {error or status or 'réponse vide'}")
            continue
        announced_total, scope = _listing_scope(html)
        if scope.lower() not in {"belgium", "lessines"}:
            errors.append(f"{url}: page non filtrée / redirection vers recherche mondiale")
            continue
        return html, from_cache, None, url, announced_total, scope
    return "", False, " | ".join(errors), "", None, ""


def _job_path_info(url: str) -> tuple[str, str]:
    """Return (city_slug, numeric_id) for a Takeda TalentBrew job URL."""
    path = urlparse(url).path.rstrip("/")
    parts = [part for part in path.split("/") if part]
    try:
        job_idx = next(i for i, part in enumerate(parts) if part.lower() == "job")
    except StopIteration:
        return "", ""
    city_slug = parts[job_idx + 1].lower() if len(parts) > job_idx + 1 else ""
    numeric_id = parts[-1] if parts and parts[-1].isdigit() else ""
    return city_slug, numeric_id


def _nearest_single_job_card(anchor, listing_url: str):
    """Find the smallest local card containing only this job link.

    This prevents a recommendation link from climbing to a huge parent that
    happens to contain the word 'Lessines' elsewhere on the page.
    """
    current = anchor
    for _ in range(7):
        parent = getattr(current, "parent", None)
        if parent is None:
            break
        current = parent
        text = clean_text(current.get_text(" ", strip=True))
        if len(text) > 2200:
            # A real result card is compact. Beyond this size we are almost
            # certainly inside the whole results/recommendations section.
            break
        job_urls = set()
        for a in current.find_all("a", href=True):
            abs_url = urljoin(listing_url or BASE_URL, clean_text(a.get("href")))
            city_slug, numeric_id = _job_path_info(abs_url)
            if numeric_id:
                job_urls.add(abs_url.rstrip("/"))
        if len(job_urls) != 1:
            continue
        low = text.lower()
        if "category:" in low and ("lessines" in low or "wallonia" in low or "belgium" in low):
            return current
    return None


def _extract_listing_rows(html: str, listing_url: str) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    found: dict[str, dict] = {}

    for anchor in soup.find_all("a", href=True):
        href = clean_text(anchor.get("href"))
        if not href:
            continue
        absolute = urljoin(listing_url or BASE_URL, href)
        parsed = urlparse(absolute)
        if parsed.netloc.lower() != "jobs.takeda.com":
            continue

        # Hard geographic guard. Takeda Belgium's public manufacturing jobs
        # are served under /job/lessines/... . This alone excludes the global
        # "Jobs for You" cards (Tianjin, Singapore, Bengaluru, ...).
        city_slug, numeric_id = _job_path_info(absolute)
        if city_slug not in BELGIUM_CITY_SLUGS or not numeric_id:
            continue

        title = clean_text(anchor.get_text(" ", strip=True))
        if not title or title.lower() in {"apply now", "save job", "view more jobs"}:
            continue

        card = _nearest_single_job_card(anchor, listing_url)
        if card is None:
            # Do not invent Belgium metadata from a broad ancestor. The URL is
            # geographically valid, but without a local card we skip it and
            # let the next crawl recover it if the site markup stabilises.
            continue
        card_text = clean_text(card.get_text(" ", strip=True))

        m_loc = re.search(r"\b(Lessines(?:,\s*Wallonia(?:,\s*Belgium)?)?)\b", card_text, re.I)
        location = clean_text(m_loc.group(1)) if m_loc else "Lessines, Wallonia, Belgium"
        m_cat = re.search(r"Category:\s*(.+?)(?=(?:Save for Later|$))", card_text, re.I)
        category = clean_text(m_cat.group(1)) if m_cat else ""

        key = absolute.rstrip("/")
        found[key] = {
            "external_id": numeric_id,
            "listing_id": numeric_id,
            "title": title,
            "location": location,
            "category": category,
            "url": absolute,
            "external_path": "",
            "date_published": "",
        }

    return list(found.values())


def _extract_probe_rows(html: str, listing_url: str, limit: int = 8) -> list[dict]:
    """Extract a few global job links only for diagnostics, never for ingestion."""
    soup = BeautifulSoup(html or "", "html.parser")
    out = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        absolute = urljoin(listing_url or BASE_URL, clean_text(anchor.get("href")))
        if urlparse(absolute).netloc.lower() != "jobs.takeda.com":
            continue
        city_slug, numeric_id = _job_path_info(absolute)
        if not numeric_id or absolute.rstrip("/") in seen:
            continue
        title = clean_text(anchor.get_text(" ", strip=True))
        if not title or title.lower() in {"apply now", "save job", "view more jobs"}:
            continue
        seen.add(absolute.rstrip("/"))
        out.append({"external_id": numeric_id, "title": title, "location": city_slug, "url": absolute})
        if len(out) >= limit:
            break
    return out


def collect_takeda_listing_candidates(use_cache: bool = True) -> tuple[list[dict], dict]:
    print("TAKEDA - collecte directe Belgique via site carrière officiel jobs.takeda.com")
    html, from_cache, error, listing_url, announced_total, listing_scope = _listing_html(use_cache=use_cache)
    if not html:
        return [], {
            "belgium_rows": 0,
            "candidates": 0,
            "errors": [error or "listing Takeda Belgique/Lessines inaccessible ou redirigé"],
            "strategy": ["official-career-site"],
            "all_belgium_rows": [],
            "probe_rows": [],
            "listing_url": listing_url,
            "from_cache": from_cache,
            "collector_mode": "jobs.takeda.com",
            "announced_total": announced_total,
            "listing_scope": listing_scope,
            "listing_reachable": False,
        }

    rows = _extract_listing_rows(html, listing_url)
    candidates = [row for row in rows if _is_target_title(row.get("title", ""))]
    print(
        f"TAKEDA - {listing_scope.upper() or 'BELGIQUE'} : {len(rows)} offre(s) belge(s) valide(s) | "
        f"{len(candidates)} candidate(s) métier | annoncé={announced_total if announced_total is not None else '?'} | "
        f"{'CACHE' if from_cache else 'WEB'}"
    )
    return candidates, {
        "belgium_rows": len(rows),
        "candidates": len(candidates),
        "errors": [],
        "strategy": [f"official-career-site:{listing_scope or 'Belgium'}"],
        "all_belgium_rows": rows,
        "probe_rows": _extract_probe_rows(html, listing_url),
        "listing_url": listing_url,
        "from_cache": from_cache,
        "collector_mode": "jobs.takeda.com",
        "announced_total": announced_total,
        "listing_scope": listing_scope,
        "listing_reachable": True,
    }

def _extract_jobposting_jsonld(soup: BeautifulSoup) -> dict:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop(0)
            if isinstance(item, list):
                stack.extend(item)
                continue
            if not isinstance(item, dict):
                continue
            typ = item.get("@type")
            if typ == "JobPosting" or (isinstance(typ, list) and "JobPosting" in typ):
                return item
            graph = item.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)
    return {}


def _jsonld_location(data: dict) -> str:
    loc = data.get("jobLocation")
    if isinstance(loc, list):
        loc = loc[0] if loc else None
    if not isinstance(loc, dict):
        return ""
    address = loc.get("address")
    if not isinstance(address, dict):
        return clean_text(loc.get("name"))
    parts = [
        address.get("addressLocality"),
        address.get("addressRegion"),
        address.get("addressCountry"),
    ]
    return clean_text(", ".join(clean_text(p) for p in parts if clean_text(p)))


def _html_to_text(fragment: str) -> str:
    if not fragment:
        return ""
    return clean_text(BeautifulSoup(fragment, "html.parser").get_text(" ", strip=True))


def _extract_description_from_page(soup: BeautifulSoup) -> str:
    # Prefer an explicitly labelled job-description container if present.
    selectors = (
        "[itemprop='description']",
        ".job-description",
        ".jobDescription",
        ".job-description-content",
        ".job-posting-description",
        "#job-description",
    )
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            text = clean_text(node.get_text(" ", strip=True))
            if len(text) >= MIN_DESCRIPTION_LENGTH:
                return text

    # TalentBrew pages are server-rendered. Slice the readable page between
    # the stable section headings rather than depending on CSS class names.
    text = "\n".join(
        clean_text(line)
        for line in soup.get_text("\n", strip=True).splitlines()
        if clean_text(line)
    )
    match = re.search(r"(?:^|\n)Job Description(?:\n|$)", text, re.I)
    if match:
        body = text[match.end():]
        end = re.search(r"\n(?:Locations|Share this job|Related content)(?:\n|$)", body, re.I)
        if end:
            body = body[:end.start()]
        body = clean_text(body)
        if len(body) >= MIN_DESCRIPTION_LENGTH:
            return body
    return clean_text(text)


def parse_takeda_detail(
    html: str,
    url: str,
    external_id: str | None = None,
    fallback: dict | None = None,
    from_cache: bool = False,
) -> dict:
    fallback = dict(fallback or {})
    soup = BeautifulSoup(html or "", "html.parser")
    full_text = clean_text(soup.get_text(" ", strip=True))
    low = _norm(full_text)
    jsonld = _extract_jobposting_jsonld(soup)

    title = clean_text(jsonld.get("title"))
    if not title:
        h1 = soup.find("h1")
        title = clean_text(h1.get_text(" ", strip=True) if h1 else "")
    title = title or clean_text(fallback.get("title"))

    req_match = re.search(r"\bJob\s+ID\s+(R\d+)\b", full_text, re.I)
    req = clean_text(req_match.group(1) if req_match else "")
    identifier = jsonld.get("identifier") if isinstance(jsonld, dict) else None
    if not req and isinstance(identifier, dict):
        req = clean_text(identifier.get("value"))
    req = req or clean_text(external_id) or clean_text(fallback.get("external_id"))

    location = _jsonld_location(jsonld)
    if not location:
        m = re.search(r"\bLocations?\s+(BEL\s*-\s*Lessines|Lessines(?:,\s*Wallonia)?)\b", full_text, re.I)
        if m:
            location = clean_text(m.group(1))
    location = location or clean_text(fallback.get("location")) or ""

    # A jobs.takeda.com detail can be perfectly readable while belonging to a
    # recommendation outside Belgium. Never let such a page enter the Belgian
    # source simply because the listing fallback said Lessines.
    detail_city_slug, _detail_numeric_id = _job_path_info(url)
    location_low = _norm(location)
    belgian_detail = (
        detail_city_slug in BELGIUM_CITY_SLUGS
        or "lessines" in location_low
        or "belgium" in location_low
    )

    contract = clean_text(jsonld.get("employmentType"))
    if not contract:
        m = re.search(r"\bJob\s+Type\s+(.+?)(?=\s+By clicking|\s+Job Description|$)", full_text, re.I)
        if m:
            contract = clean_text(m.group(1))
    if not contract:
        m = re.search(r"\bTime\s+Type\s+(Full time|Part time)\b", full_text, re.I)
        if m:
            contract = clean_text(m.group(1))

    date_published = clean_text(jsonld.get("datePosted"))
    description = _html_to_text(clean_text(jsonld.get("description")))
    if len(description) < MIN_DESCRIPTION_LENGTH:
        description = _extract_description_from_page(soup)

    closed = any(marker in low for marker in CLOSED_MARKERS)
    language = detect_language(description or full_text)
    dutch_required = dutch_professional_required(description or full_text)

    structured = {
        "external_id": req,
        "job_requisition_id": req,
        "title": title,
        "company": "Takeda",
        "location": location,
        "contract_type": contract,
        "date_published": date_published,
        "language": language,
        "dutch_required": dutch_required,
        "url": url,
        "closed": closed,
        "category": clean_text(fallback.get("category")),
        "external_path": "",
    }

    if not belgian_detail:
        return {
            "success": False,
            "matching_text": "",
            "matching_text_length": 0,
            "structured": structured,
            "from_cache": from_cache,
            "error": f"Takeda : fiche hors Belgique détectée ({location or detail_city_slug or 'lieu inconnu'}).",
        }

    if closed:
        return {
            "success": False,
            "matching_text": "",
            "matching_text_length": 0,
            "structured": structured,
            "from_cache": from_cache,
            "error": "Takeda : offre clôturée / non disponible.",
        }
    if len(description) < MIN_DESCRIPTION_LENGTH:
        return {
            "success": False,
            "matching_text": description,
            "matching_text_length": len(description),
            "structured": structured,
            "from_cache": from_cache,
            "error": f"Takeda : description trop courte ({len(description)} caractères).",
        }
    return {
        "success": True,
        "matching_text": description,
        "matching_text_length": len(description),
        "structured": structured,
        "from_cache": from_cache,
        "error": None,
    }


def get_takeda_job_detail(
    url: str = "",
    external_id: str | None = None,
    external_path: str | None = None,  # compatibility with older JobHunter rows
    use_cache: bool = True,
    fallback: dict | None = None,
) -> dict:
    fallback = dict(fallback or {})
    url = clean_text(url or fallback.get("url"))
    if not url:
        return {
            "success": False,
            "matching_text": "",
            "matching_text_length": 0,
            "structured": {"external_id": external_id, "url": url},
            "from_cache": False,
            "error": "Takeda : URL jobs.takeda.com introuvable.",
        }

    # New connector intentionally reads jobs.takeda.com. Old Workday URLs are
    # still useful as application links, but they are not a reliable listing/
    # detail source anymore.
    if "jobs.takeda.com" not in urlparse(url).netloc.lower():
        return {
            "success": False,
            "matching_text": "",
            "matching_text_length": 0,
            "structured": {"external_id": external_id, "url": url},
            "from_cache": False,
            "error": "Takeda : ancienne URL Workday. Un nouveau passage de collecte est requis.",
        }

    cache_path = _cache_path_for_url(url)
    html, from_cache, error, status = _request_html(url, cache_path, use_cache=use_cache)
    if not html:
        closed = status == 404
        return {
            "success": False,
            "matching_text": "",
            "matching_text_length": 0,
            "structured": {
                "external_id": external_id or clean_text(fallback.get("external_id")),
                "title": clean_text(fallback.get("title")),
                "location": clean_text(fallback.get("location")),
                "url": url,
                "closed": closed,
            },
            "from_cache": bool(from_cache),
            "error": "Takeda : offre clôturée / HTTP 404." if closed else f"Takeda : {error or 'lecture HTTP impossible'}",
        }
    return parse_takeda_detail(
        html,
        url,
        external_id=external_id,
        fallback=fallback,
        from_cache=bool(from_cache),
    )


def _job_from_detail(detail: dict, fallback: dict) -> JobOffer:
    st = detail.get("structured") or {}
    description = clean_text(detail.get("matching_text"))
    job = JobOffer(
        source="TAKEDA",
        external_id=clean_text(st.get("external_id") or fallback.get("external_id")),
        title=clean_text(st.get("title") or fallback.get("title") or "Titre inconnu"),
        company="Takeda",
        location=clean_text(st.get("location") or fallback.get("location") or "Belgium"),
        description=description,
        url=clean_text(st.get("url") or fallback.get("url")),
        date_published=clean_text(st.get("date_published")) or None,
        contract_type=clean_text(st.get("contract_type")) or None,
        language=clean_text(st.get("language")) or None,
    )
    job.collection_channel = "TAKEDA"
    job.origin_source = "TAKEDA"
    job.detail_enrichment_attempted = True
    job.detail_enrichment_success = True
    job.detail_matching_text = description
    job.detail_matching_text_length = len(description)
    job.workday_external_path = ""
    job.takeda_requisition_id = clean_text(st.get("job_requisition_id") or st.get("external_id"))
    return job


def collect_takeda_jobs() -> list[JobOffer]:
    candidates, meta = collect_takeda_listing_candidates(use_cache=False)
    print(
        "TAKEDA - préfiltre : "
        f"{meta.get('belgium_rows', 0)} offre(s) Belgique détectée(s), "
        f"{len(candidates)} candidate(s) métier"
    )
    for error in meta.get("errors") or []:
        print(f"TAKEDA - avertissement : {error}")

    jobs: list[JobOffer] = []
    rejected_nl = rejected_dutch = closed = errors = 0
    languages = {"fr": 0, "en": 0, "unknown": 0}

    for index, item in enumerate(candidates, start=1):
        detail = get_takeda_job_detail(
            url=item.get("url", ""),
            external_id=item.get("external_id"),
            use_cache=True,
            fallback=item,
        )
        st = detail.get("structured") or {}
        title = clean_text(st.get("title") or item.get("title"))
        if st.get("closed"):
            closed += 1
            print(f"[{index:03d}/{len(candidates):03d}] 💤 CLOSED | {title}")
            continue
        if not detail.get("success"):
            errors += 1
            print(f"[{index:03d}/{len(candidates):03d}] ⚠️ DETAIL | {title} | {detail.get('error')}")
            continue
        language = clean_text(st.get("language")).lower() or "unknown"
        if language == "nl":
            rejected_nl += 1
            print(f"[{index:03d}/{len(candidates):03d}] ⛔ NL     | {title}")
            continue
        if st.get("dutch_required"):
            rejected_dutch += 1
            print(f"[{index:03d}/{len(candidates):03d}] ⛔ DUTCH  | {title} | néerlandais professionnel requis")
            continue
        if language not in languages:
            language = "unknown"
        languages[language] += 1
        job = _job_from_detail(detail, item)
        jobs.append(job)
        print(
            f"[{index:03d}/{len(candidates):03d}] ✅ {language.upper():<7} | "
            f"{len(job.description):4d} car. | {job.title} | {job.location}"
        )
        time.sleep(DETAIL_DELAY_SECONDS)

    print()
    print("=" * 76)
    print("                     BILAN TAKEDA V1.2")
    print("=" * 76)
    print(f"Offres Belgique détectées           : {meta.get('belgium_rows', 0)}")
    print(f"Candidates métier préfiltrées       : {len(candidates)}")
    print(f"Conservées FR/EN/ambiguës           : {len(jobs)}")
    print(f"  Français                          : {languages['fr']}")
    print(f"  Anglais                           : {languages['en']}")
    print(f"  Langue ambiguë                    : {languages['unknown']}")
    print(f"Rejetées - fiche clairement NL      : {rejected_nl}")
    print(f"Rejetées - néerlandais requis       : {rejected_dutch}")
    print(f"Clôturées / 404                     : {closed}")
    print(f"Échecs détail                       : {errors}")
    publish_metrics_from_locals("TAKEDA", locals())
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
