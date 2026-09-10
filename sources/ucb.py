"""
JOB HUNTER BELGIUM
UCB BELGIUM - VERSION 1.0

Direct-employer collector for UCB's public Phenom careers portal.
Targets Belgium roles close to QC/Lab/Pharma and Junior Data/BI profiles.

No authentication bypass or anti-bot circumvention is used.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from database.models import JobOffer
from sources.phenom import (
    PhenomClient,
    clean_text,
    job_contract,
    job_external_id,
    job_location,
    job_posted_date,
    job_teaser,
    job_title,
    phenom_jobs,
    phenom_total,
)
from sources.randstad import dutch_professional_required
from sources.scienceatwork import detect_language as detect_body_language
from sources.source_metrics import publish_metrics_from_locals


BASE_URL = "https://careers.ucb.com"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "logs" / "ucb_phenom_cache"
DETAIL_CACHE_DIR = CACHE_DIR / "details"
DETAIL_CACHE_DIR.mkdir(parents=True, exist_ok=True)

CLIENT = PhenomClient(
    host=BASE_URL,
    locale_path="/global/en",
    lang="en_global",
    country="global",
    cache_dir=CACHE_DIR,
)

REQUEST_TIMEOUT = 30
MAX_PAGES = 8
PAGE_SIZE = 50
DETAIL_DELAY_SECONDS = 0.25
MIN_DESCRIPTION_LENGTH = 180

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/151.0 Safari/537.36 Edg/151.0"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.2",
    }
)

BELGIUM_MARKERS = (
    "belgium",
    "belgique",
    "braine l'alleud",
    "braine-l'alleud",
    "braine l’alleud",
    "walloon brabant",
    "brabant wallon",
    "anderlecht",
    "brussels",
    "bruxelles",
)

TARGET_TITLE_PATTERNS = (
    '\\bqc\\b',
    '\\bquality\\s+control\\b',
    '\\bquality\\s+(?:technician|officer|associate|specialist|coordinator|engineer)\\b',
    '\\bqa\\s+(?:technician|officer|associate|specialist|coordinator)\\b',
    '\\btechnicien(?:ne)?\\s+(?:qa|qc|qualit[eé])\\b',
    '\\blab(?:oratory)?\\s+(?:technician|analyst|associate|specialist|operator)\\b',
    '\\btechnicien(?:ne)?\\s+(?:de\\s+)?laboratoire\\b',
    '\\blaborantin(?:e)?\\b',
    '\\banalytical\\s+(?:associate\\s+)?scientist\\b',
    '\\banalytical\\s+(?:technician|analyst)\\b',
    '\\bmicrobiology\\s+(?:technician|analyst|scientist)\\b',
    '\\benvironmental\\s+monitoring\\b',
    '\\bbiomanufacturing\\s+technician\\b',
    '\\bprocess\\s+technician\\b',
    '\\btechnicien(?:ne)?\\s+process\\b',
    '\\bproduction\\s+technician\\b',
    '\\bjunior\\s+data\\s+analyst\\b',
    '\\bdata\\s+analyst\\b',
    '\\bbusiness\\s+(?:data\\s+)?analyst\\b',
    '\\bmaster\\s+data(?:\\s+management)?\\b',
    '\\bdata\\s+quality\\b',
    '\\bdata\\s+integrity\\b',
    '\\bdata\\s+steward\\b',
    '\\breporting\\s+analyst\\b',
    '\\bpower\\s*bi\\b',
    '\\bbi\\s+(?:analyst|developer)\\b',
    '\\bbusiness\\s+intelligence\\b',
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
    r"\b(?:senior|sr\.?|principal)\b",
    r"\b(?:director|head|vice president|vp)\b",
    r"\bmanager\b",
    r"\blead\b",
    r"\bintern(?:ship)?\b",
    r"\bstage\b",
    r"\bstagiaire\b",
    r"\bgraduate\b",
    r"\bstudent\b",
    r"\bapprentice(?:ship)?\b",
    r"\btrainee\b",
)

FALLBACK_SEARCH_TERMS = (
    'Belgium',
    'Braine',
    'QC',
    'laboratory technician',
    'data analyst',
    'master data',
    'Belgique',
    'Bruxelles',
    "Braine-l'Alleud",
    'technicien de laboratoire',
    'laborantin',
    'contrôle qualité',
    'assurance qualité',
    'analyste de données',
    'analyste qualité',
)

CLOSED_MARKERS = (
    "the job you are trying to apply for has been filled",
    "the position you are trying to apply for has been filled",
    "le poste pour lequel vous essayez de postuler a été pourvu",
    "le poste pour lequel vous essayez de postuler a ete pourvu",
)

STOP_MARKERS = (
    "about us",
    "why work with us",
    "are you ready to 'go beyond'",
    "are you ready to ‘go beyond’",
    "explore location",
    "join our talent community",
)


def _normalize(value: Any) -> str:
    return clean_text(value).lower().replace("’", "'")


def _hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:24]


def _flatten_strings(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, dict):
        for item in value.values():
            out.extend(_flatten_strings(item))
    elif isinstance(value, list):
        for item in value:
            out.extend(_flatten_strings(item))
    elif isinstance(value, (str, int, float)):
        text = clean_text(value)
        if text:
            out.append(text)
    return out


def _is_belgium_row(row: dict) -> bool:
    haystack = _normalize(" | ".join(_flatten_strings(row)))
    return any(marker in haystack for marker in BELGIUM_MARKERS)


def _is_target_title(title: str, teaser: str = "") -> bool:
    title_low = _normalize(title)
    if not title_low:
        return False
    if any(re.search(pattern, title_low, flags=re.I) for pattern in NON_TARGET_TITLE_PATTERNS):
        return False
    if any(re.search(pattern, title_low, flags=re.I) for pattern in TARGET_TITLE_PATTERNS):
        return True

    # A few UCB cards use generic titles; only let the teaser rescue them when
    # the title itself is operational/analytical rather than management.
    combined = _normalize(f"{title} {teaser}")
    if re.search(r"\btechnician\b|\btechnicien(?:ne)?\b", title_low):
        return bool(re.search(r"\b(?:qc|quality|laboratory|lab|analytical|biomanufacturing|process)\b", combined))
    return False


def _candidate_from_row(row: dict) -> dict:
    return {
        "external_id": job_external_id(row) or _hash(json.dumps(row, sort_keys=True, default=str)),
        "title": job_title(row),
        "location": job_location(row),
        "date_published": job_posted_date(row),
        "contract_type": job_contract(row),
        "teaser": job_teaser(row),
        "url": CLIENT.public_job_url(row),
        "raw": row,
    }


def _merge_rows(target: dict[str, dict], rows: list[dict], trust_belgium: bool = False) -> tuple[int, int]:
    added = 0
    target_added = 0
    for row in rows:
        if not trust_belgium and not _is_belgium_row(row):
            continue
        candidate = _candidate_from_row(row)
        key = clean_text(candidate.get("external_id")) or clean_text(candidate.get("url"))
        if not key:
            continue
        if key not in target:
            target[key] = candidate
            added += 1
            if _is_target_title(candidate.get("title", ""), candidate.get("teaser", "")):
                target_added += 1
    return added, target_added


def _paginate(keywords: str = "", selected_fields: dict | None = None, label: str = "SEARCH"):
    rows_all: list[dict] = []
    errors: list[str] = []
    offset = 0
    total = None
    for page in range(1, MAX_PAGES + 1):
        payload, error = CLIENT.search(
            keywords=keywords,
            selected_fields=selected_fields,
            offset=offset,
            size=PAGE_SIZE,
        )
        if not payload:
            errors.append(error or "réponse vide")
            break
        rows = phenom_jobs(payload)
        if total is None:
            total = phenom_total(payload)
        print(
            f"UCB - {label:<18} page {page:2d}: {len(rows):2d} offre(s) "
            f"| total annoncé {total or '?'} | WEB"
        )
        if not rows:
            break
        rows_all.extend(rows)
        offset += len(rows)
        if len(rows) < PAGE_SIZE or (total and offset >= total):
            break
        time.sleep(0.35)
    return rows_all, errors, total or len(rows_all)


def collect_ucb_listing_candidates() -> tuple[list[dict], list[dict], dict]:
    print("UCB - collecte directe Belgique via portail Phenom public")
    belgium_rows: dict[str, dict] = {}
    errors: list[str] = []
    strategies: list[str] = []

    # Preferred path: Phenom facet. If the tenant uses a different country key,
    # the fallback searches below still discover Belgian postings.
    rows, errs, total = _paginate(
        keywords="",
        selected_fields={"country": ["Belgium"]},
        label="BELGIUM FACET",
    )
    errors.extend(errs)
    if rows:
        # The selected country facet is trusted only when the returned rows show
        # at least one Belgian signal. Otherwise keep only explicit Belgian rows.
        explicit_be = [row for row in rows if _is_belgium_row(row)]
        if explicit_be:
            _merge_rows(belgium_rows, rows, trust_belgium=True)
            strategies.append("facet:country=Belgium")
        else:
            _merge_rows(belgium_rows, rows, trust_belgium=False)

    # Fallback and coverage queries. Dedupe keeps this cheap when the facet works.
    if not belgium_rows:
        for term in FALLBACK_SEARCH_TERMS:
            payload, error = CLIENT.search(keywords=term, offset=0, size=PAGE_SIZE)
            if not payload:
                if error:
                    errors.append(f"{term}: {error}")
                continue
            rows_term = phenom_jobs(payload)
            added, _ = _merge_rows(belgium_rows, rows_term, trust_belgium=False)
            print(f"UCB - mot-clé {term:<24}: {len(rows_term):2d} résultat(s) | +{added} Belgique")
            strategies.append(f"search:{term}")
            time.sleep(0.25)

    all_belgium = list(belgium_rows.values())
    candidates = [
        item for item in all_belgium
        if _is_target_title(item.get("title", ""), item.get("teaser", ""))
    ]
    meta = {
        "belgium_jobs": len(all_belgium),
        "candidates": len(candidates),
        "strategies": strategies,
        "errors": errors,
        "facet_total": total,
    }
    return all_belgium, candidates, meta


def _detail_cache_path(url: str, external_id: str | None = None) -> Path:
    key = clean_text(external_id) or _hash(url)
    return DETAIL_CACHE_DIR / f"{re.sub(r'[^0-9A-Za-z_-]+', '_', key)}.html"


def _request_html(url: str) -> tuple[str | None, str | None]:
    try:
        response = SESSION.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        text = response.text or ""
        if len(text) < 500:
            raise ValueError(f"HTML trop court ({len(text)} caractères)")
        return text, None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _jsonld_jobposting(soup: BeautifulSoup) -> dict:
    def walk(value):
        if isinstance(value, dict):
            kind = value.get("@type")
            if kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind):
                return value
            for child in value.values():
                found = walk(child)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = walk(child)
                if found:
                    return found
        return None

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text() or ""
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        found = walk(payload)
        if found:
            return found
    return {}


def _strip_html(value: str) -> str:
    if not value:
        return ""
    return clean_text(BeautifulSoup(html_lib.unescape(value), "html.parser").get_text("\n", strip=True))


def _jsonld_location(jobposting: dict) -> str:
    locations = jobposting.get("jobLocation")
    if not isinstance(locations, list):
        locations = [locations] if locations else []
    labels = []
    for loc in locations:
        if not isinstance(loc, dict):
            continue
        address = loc.get("address")
        if isinstance(address, dict):
            parts = [
                clean_text(address.get("addressLocality")),
                clean_text(address.get("addressRegion")),
                clean_text(address.get("addressCountry")),
            ]
            label = ", ".join(part for part in parts if part)
            if label and label not in labels:
                labels.append(label)
    return " | ".join(labels)


def _body_text(soup: BeautifulSoup, title: str) -> str:
    main = soup.find("main") or soup.find("article") or soup.body
    if main is None:
        return ""
    text = clean_text(main.get_text("\n", strip=True))
    low = text.lower()
    if title:
        pos = low.find(title.lower())
        if pos >= 0:
            text = text[pos:]
            low = text.lower()
    cuts = []
    for marker in STOP_MARKERS:
        pos = low.find(marker)
        if pos > 250:
            cuts.append(pos)
    if cuts:
        text = text[: min(cuts)]
    return clean_text(text)


def _detect_language(text: str) -> str:
    lang = clean_text(detect_body_language(text)).lower()
    return lang if lang in {"fr", "en", "nl"} else "unknown"


def _external_id_from_url(url: str) -> str:
    path = urlparse(clean_text(url)).path
    match = re.search(r"/job/([^/]+)/", path, flags=re.I)
    return clean_text(match.group(1)) if match else ""


def parse_ucb_detail(html: str, url: str, external_id: str | None = None, fallback: dict | None = None) -> dict:
    fallback = fallback or {}
    soup = BeautifulSoup(html, "html.parser")
    page_text = clean_text(soup.get_text(" ", strip=True))
    page_low = _normalize(page_text)
    if any(marker in page_low for marker in CLOSED_MARKERS):
        return {
            "success": False,
            "matching_text": "",
            "matching_text_length": 0,
            "structured": {
                "external_id": clean_text(external_id) or _external_id_from_url(url),
                "url": url,
                "closed": True,
            },
            "from_cache": False,
            "error": "UCB : offre clôturée / déjà pourvue",
        }

    jobposting = _jsonld_jobposting(soup)
    h1 = soup.find("h1")
    title = clean_text(jobposting.get("title")) if jobposting else ""
    if not title and h1:
        title = clean_text(h1.get_text(" ", strip=True))
    title = title or clean_text(fallback.get("title"))

    description = _strip_html(clean_text(jobposting.get("description"))) if jobposting else ""
    if len(description) < MIN_DESCRIPTION_LENGTH:
        description = _body_text(soup, title)

    location = _jsonld_location(jobposting) if jobposting else ""
    location = location or clean_text(fallback.get("location")) or "Belgium"
    contract = clean_text(jobposting.get("employmentType")) if jobposting else ""
    contract = contract or clean_text(fallback.get("contract_type"))
    date_published = clean_text(jobposting.get("datePosted")) if jobposting else ""
    date_published = date_published or clean_text(fallback.get("date_published"))
    external_id = clean_text(external_id) or _external_id_from_url(url) or clean_text(fallback.get("external_id")) or _hash(url)

    language = _detect_language(description)
    dutch_required = dutch_professional_required(description)
    structured = {
        "external_id": external_id,
        "url": url,
        "title": title,
        "company": "UCB",
        "location": location,
        "contract_type": contract,
        "date_published": date_published,
        "language": language,
        "dutch_required": dutch_required,
        "phenom_job_seq_no": external_id,
        "closed": False,
    }
    success = bool(title and len(description) >= MIN_DESCRIPTION_LENGTH)
    return {
        "success": success,
        "matching_text": description,
        "matching_text_length": len(description),
        "structured": structured,
        "from_cache": False,
        "error": None if success else f"UCB : fiche incomplète (titre={bool(title)}, description={len(description)} car.)",
    }


def get_ucb_job_detail(url: str, external_id: str | None = None, use_cache: bool = True, fallback: dict | None = None) -> dict:
    cache = _detail_cache_path(url, external_id)
    if use_cache and cache.exists():
        try:
            result = parse_ucb_detail(cache.read_text(encoding="utf-8"), url, external_id, fallback=fallback)
            if result.get("success") or (result.get("structured") or {}).get("closed"):
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
            "error": f"UCB : {error or 'lecture HTTP impossible'}",
        }
    try:
        cache.write_text(html, encoding="utf-8")
    except Exception:
        pass
    return parse_ucb_detail(html, url, external_id, fallback=fallback)


def _job_from_detail(detail: dict, fallback: dict) -> JobOffer:
    structured = detail.get("structured") or {}
    job = JobOffer(
        source="UCB",
        external_id=clean_text(structured.get("external_id") or fallback.get("external_id")),
        title=clean_text(structured.get("title") or fallback.get("title") or "Titre inconnu"),
        company="UCB",
        location=clean_text(structured.get("location") or fallback.get("location") or "Belgium"),
        description=clean_text(detail.get("matching_text")),
        url=clean_text(structured.get("url") or fallback.get("url")),
        date_published=clean_text(structured.get("date_published") or fallback.get("date_published")) or None,
        contract_type=clean_text(structured.get("contract_type") or fallback.get("contract_type")) or None,
        language=clean_text(structured.get("language")) or None,
    )
    job.collection_channel = "UCB"
    job.origin_source = "UCB"
    job.phenom_job_seq_no = clean_text(structured.get("phenom_job_seq_no") or job.external_id)
    return job


def search_targeted_ucb_jobs() -> list[JobOffer]:
    all_belgium, candidates, meta = collect_ucb_listing_candidates()
    print()
    print("=" * 88)
    print("UCB - PREFILTRE LIVE")
    print("=" * 88)
    print(f"Offres Belgique détectées     : {len(all_belgium)}")
    print(f"Candidates métier             : {len(candidates)}")
    print(f"Stratégies                    : {', '.join(meta.get('strategies') or []) or '-'}")
    for error in meta.get("errors") or []:
        print(f"UCB - avertissement : {error}")

    if not candidates:
        print("UCB - aucune offre correspondant au profil cible actuellement.")
        return []

    jobs: list[JobOffer] = []
    errors = 0
    rejected_nl = 0
    rejected_dutch = 0
    closed = 0
    languages = {"fr": 0, "en": 0, "unknown": 0}

    for index, item in enumerate(candidates, start=1):
        url = clean_text(item.get("url"))
        title = clean_text(item.get("title")) or "Titre inconnu"
        if not url:
            errors += 1
            print(f"[{index:03d}/{len(candidates):03d}] ❌ URL    | {title}")
            continue
        detail = get_ucb_job_detail(url, item.get("external_id"), use_cache=True, fallback=item)
        structured = detail.get("structured") or {}
        title = clean_text(structured.get("title") or title)
        if structured.get("closed"):
            closed += 1
            print(f"[{index:03d}/{len(candidates):03d}] 💤 CLOSED | {title}")
            continue
        if not detail.get("success"):
            errors += 1
            print(f"[{index:03d}/{len(candidates):03d}] ❌ DETAIL | {title} | {clean_text(detail.get('error'))}")
            continue

        language = clean_text(structured.get("language") or "unknown").lower()
        if language == "nl":
            rejected_nl += 1
            print(f"[{index:03d}/{len(candidates):03d}] ⛔ NL     | {title}")
            continue
        if bool(structured.get("dutch_required")):
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
    print("                       BILAN UCB V1.0")
    print("=" * 76)
    print(f"Offres Belgique détectées           : {len(all_belgium)}")
    print(f"Candidates métier préfiltrées       : {len(candidates)}")
    print(f"Conservées FR/EN/ambiguës           : {len(jobs)}")
    print(f"  Français                          : {languages['fr']}")
    print(f"  Anglais                           : {languages['en']}")
    print(f"  Langue ambiguë                    : {languages['unknown']}")
    print(f"Rejetées - fiche clairement NL      : {rejected_nl}")
    print(f"Rejetées - néerlandais requis       : {rejected_dutch}")
    print(f"Clôturées / déjà pourvues           : {closed}")
    print(f"Échecs détail                       : {errors}")
    publish_metrics_from_locals("UCB", locals())
    return jobs


def collect_ucb_jobs() -> list[JobOffer]:
    return search_targeted_ucb_jobs()


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
