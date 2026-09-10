from __future__ import annotations

import hashlib
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from database.models import JobOffer

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/152.0.0.0 Safari/537.36"
)

TARGET_PATTERNS = [
    r"\bdata analyst\b",
    r"\bbusiness analyst\b",
    r"\bbi analyst\b",
    r"\bbusiness intelligence\b",
    r"\bpower\s*bi\b",
    r"\breporting analyst\b",
    r"\bdata quality\b",
    r"\bdata steward\b",
    r"\bmaster data\b",
    r"\bquality control\b",
    r"\bquality assurance\b",
    r"\bqc\b",
    r"\bqa\b",
    r"\bqc specialist\b",
    r"\bquality specialist\b",
    r"\blaboratory technician\b",
    r"\blab technician\b",
    r"\blaboratory analyst\b",
    r"\blab engineer\b",
    r"\blaborantin\b",
    r"\btechnologue de laboratoire\b",
    r"\btechnicien(?:ne)? de laboratoire\b",
    r"\banalytical chemistry\b",
    r"\banalytical scientist\b",
    r"\banalytical analyst\b",
    r"\banalytical project\b",
    r"\bchemist\b",
    r"\bchimiste\b",
    r"\bmicrobiology\b",
    r"\bmicrobiologie\b",
    r"\bvalidation technician\b",
    r"\btechnicien(?:ne)? validation\b",
    r"\bmsat\b",
    r"\bproduction gmp\b",
    r"\btechnicien(?:ne)? préparation\b",
]

EXCLUDE_PATTERNS = [
    r"\bsenior\b",
    r"\bsr\.?\b",
    r"\bprincipal\b",
    r"\bdirector\b",
    r"\bhead\b",
    r"\bvice president\b",
    r"\bvp\b",
    r"\bmanager\b",
    r"\bsupervisor\b",
    r"\bintern(?:ship)?\b",
    r"\bstage\b",
    r"\btrainee\b",
    r"\bapprentice\b",
]

DUTCH_HARD_PATTERNS = [
    r"\bfluent\s+dutch\b",
    r"\bprofessional\s+dutch\b",
    r"\bdutch\s+(?:is\s+)?required\b",
    r"\bdutch\s+mandatory\b",
    r"\bgoede\s+kennis\s+(?:van\s+het\s+)?nederlands\b",
    r"\bnederlands\s+(?:is\s+)?vereist\b",
    r"\bvloeiend\s+nederlands\b",
    r"\btweetalig\b",
    r"\bma[iî]trise\s+du\s+n[eé]erlandais\b",
    r"\bn[eé]erlandais\s+(?:est\s+)?(?:exig[eé]|requis|obligatoire)\b",
]

OPTIONAL_MARKERS = [
    "asset", "plus", "preferred", "nice to have",
    "atout", "pluspunt", "souhaité", "souhaite",
]

WALLONIA_BRUSSELS = [
    "donstiennes", "thuin", "charleroi", "gosselies",
    "liège", "liege", "seraing", "ougrée", "ougree",
    "nivelles", "louvain-la-neuve", "ottignies",
    "wavre", "braine-l'alleud", "braine l'alleud",
    "brussels", "bruxelles", "wallonia", "wallonie",
    "brabant wallon", "hainaut",
]


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def session():
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": UA,
            "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8",
        }
    )
    return s


def title_is_target(title):
    title = clean(title)
    return (
        bool(title)
        and not any(re.search(p, title, re.I) for p in EXCLUDE_PATTERNS)
        and any(re.search(p, title, re.I) for p in TARGET_PATTERNS)
    )


def dutch_hard(text):
    for chunk in re.split(r"(?<=[.!?;:])\s+|[\r\n•●▪◦]+", str(text or "")):
        low = clean(chunk).lower()
        if not low:
            continue
        if any(re.search(p, low, re.I) for p in DUTCH_HARD_PATTERNS):
            if any(marker in low for marker in OPTIONAL_MARKERS):
                continue
            return True
    return False


def geo_status(text):
    value = clean(text)

    try:
        from sources.belgium_locations import classify_belgium_location
        decision = classify_belgium_location(value)
        status = getattr(decision, "status", getattr(decision, "state", "UNKNOWN"))
        if status in {"BELGIUM", "FOREIGN"}:
            return status
    except Exception:
        pass

    low = value.lower()
    if (
        "belgium" in low
        or "belgique" in low
        or "belgië" in low
        or any(hint in low for hint in WALLONIA_BRUSSELS)
    ):
        return "BELGIUM"

    return "UNKNOWN"


def fetch_detail(s, url):
    r = s.get(url, timeout=30, allow_redirects=True)

    if r.status_code in {404, 410}:
        return {
            "closed": True,
            "http": r.status_code,
            "url": r.url,
        }

    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    text = clean(soup.get_text(" ", strip=True))

    h1 = soup.find("h1")
    title = clean(h1.get_text(" ", strip=True)) if h1 else ""

    location = ""

    for selector in [
        '[itemprop="jobLocation"]',
        '[class*="location"]',
        '[id*="location"]',
        '[class*="place"]',
    ]:
        try:
            for node in soup.select(selector):
                candidate = clean(node.get("content") or node.get_text(" ", strip=True))
                if not (2 < len(candidate) < 400):
                    continue
                if geo_status(candidate) == "BELGIUM":
                    location = candidate
                    break
                if not location:
                    location = candidate
        except Exception:
            pass

        if location and geo_status(location) == "BELGIUM":
            break

    if geo_status(location) != "BELGIUM":
        low = text.lower()
        for hint in WALLONIA_BRUSSELS:
            if hint in low:
                location = hint
                break

    return {
        "closed": False,
        "http": r.status_code,
        "url": r.url,
        "title": title,
        "location": location,
        "geo": geo_status(location or text[:3000]),
        "description": text,
        "hard_dutch": dutch_hard(text),
    }


def stable_id(source, title, url):
    token = f"{source}|{clean(title).lower()}|{clean(url).lower()}"
    return hashlib.sha1(token.encode("utf-8")).hexdigest()[:20]


def make_job(
    *,
    source,
    company,
    title,
    location,
    description,
    url,
    external_id=None,
):
    return JobOffer(
        source=source,
        external_id=external_id or stable_id(source, title, url),
        title=clean(title),
        company=clean(company),
        location=clean(location),
        description=clean(description),
        url=clean(url),
        date_published=None,
        contract_type=None,
        language=None,
    )


def publish_metrics(source, metrics):
    try:
        from sources import source_metrics
        store = getattr(source_metrics, "_STORE", None)
        if isinstance(store, dict):
            store[str(source).upper()] = dict(metrics)
    except Exception:
        pass


def finalize(
    *,
    source,
    company,
    rows,
    detail_errors=0,
    closed=0,
):
    candidates = [row for row in rows if title_is_target(row["title"])]

    kept_rows = []
    rejected_language = 0
    rejected_geo = 0

    for row in candidates:
        if row.get("hard_dutch"):
            rejected_language += 1
            continue
        if row.get("geo") != "BELGIUM":
            rejected_geo += 1
            continue
        if len(clean(row.get("description"))) < 250:
            detail_errors += 1
            continue
        kept_rows.append(row)

    jobs = [
        make_job(
            source=source,
            company=row.get("company") or company,
            title=row["title"],
            location=row["location"],
            description=row["description"],
            url=row["url"],
            external_id=row.get("external_id"),
        )
        for row in kept_rows
    ]

    metrics = {
        "seen": len(rows),
        "candidates": len(candidates),
        "kept": len(jobs),
        "non_target": max(0, len(rows) - len(candidates)),
        "rejected_language": rejected_language,
        "rejected_geo": rejected_geo,
        "closed": closed,
        "detail_errors": detail_errors,
    }

    publish_metrics(source, metrics)

    print()
    print("=" * 88)
    print(f"{source} - WALLONIA / BRUSSELS")
    print("=" * 88)
    for key, value in metrics.items():
        print(f"{key:<20}: {value}")
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
