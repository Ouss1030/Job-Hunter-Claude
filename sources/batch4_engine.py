from __future__ import annotations

import hashlib
import re

from database.models import JobOffer

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
    r"\bqualification\b",
    r"\bvalidation\b",
    r"\btechnicien(?:ne)? qualification\b",
    r"\btechnicien(?:ne)? de production\b",
    r"\bproduction technician\b",
    r"\blaboratory technician\b",
    r"\blab technician\b",
    r"\blaboratory analyst\b",
    r"\blaborantin\b",
    r"\btechnologue de laboratoire\b",
    r"\btechnicien(?:ne)? de laboratoire\b",
    r"\baide technique de laboratoire\b",
    r"\banalytical chemistry\b",
    r"\banalytical scientist\b",
    r"\bchemist\b",
    r"\bchimiste\b",
    r"\bmicrobiology\b",
    r"\bmicrobiologie\b",
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
    "asset",
    "plus",
    "preferred",
    "nice to have",
    "atout",
    "pluspunt",
    "souhaité",
    "souhaite",
]


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


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


def stable_id(source, title, url):
    token = f"{source}|{clean(title).lower()}|{clean(url).lower()}"
    return hashlib.sha1(token.encode("utf-8")).hexdigest()[:20]


def publish_metrics(source, metrics):
    try:
        from sources import source_metrics
        store = getattr(source_metrics, "_STORE", None)
        if isinstance(store, dict):
            store[str(source).upper()] = dict(metrics)
    except Exception:
        pass


def build_jobs(source, company, rows, detail_errors=0):
    candidates = [row for row in rows if title_is_target(row["title"])]
    kept_rows = []
    rejected_language = 0

    for row in candidates:
        if row.get("hard_dutch"):
            rejected_language += 1
            continue
        if len(clean(row.get("description"))) < 250:
            detail_errors += 1
            continue
        kept_rows.append(row)

    jobs = [
        JobOffer(
            source=source,
            external_id=row.get("external_id") or stable_id(source, row["title"], row["url"]),
            title=clean(row["title"]),
            company=clean(row.get("company") or company),
            location=clean(row.get("location")),
            description=clean(row.get("description")),
            url=clean(row.get("url")),
            date_published=None,
            contract_type=None,
            language=None,
        )
        for row in kept_rows
    ]

    metrics = {
        "seen": len(rows),
        "candidates": len(candidates),
        "kept": len(jobs),
        "non_target": max(0, len(rows) - len(candidates)),
        "rejected_language": rejected_language,
        "rejected_geo": 0,
        "closed": 0,
        "detail_errors": detail_errors,
    }

    publish_metrics(source, metrics)

    print()
    print("=" * 88)
    print(source)
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
