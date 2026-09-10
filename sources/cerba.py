from __future__ import annotations

import re
import requests
from bs4 import BeautifulSoup

from database.models import JobOffer
from sources.batch4_engine import clean, dutch_hard, title_is_target, publish_metrics

CERBA_VERSION = "1.1"
BASE = "https://fr.jobs.cerbahealthcare.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/152 Safari/537.36"

SEED_IDS = ("827941", "811670", "829166")
BELGIUM_MARKERS = (
    "anderlecht", "bruxelles", "brussels", "belgique", "belgium",
    "liège", "liege", "gand", "gent",
)


def _detail(s, jid):
    r = s.get(f"{BASE}/our-offers/{jid}", timeout=25, allow_redirects=True)
    if r.status_code in {404, 410}:
        return None, "closed"
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    text = clean(soup.get_text(" ", strip=True))
    h1 = soup.find("h1")
    title = clean(h1.get_text(" ", strip=True)) if h1 else ""
    low = text.lower()
    location = "Belgium"
    for marker in ("anderlecht", "bruxelles", "brussels", "liège", "liege", "gand", "gent"):
        if marker in low:
            location = marker
            break
    return {
        "external_id": jid,
        "title": title,
        "location": location,
        "description": text,
        "hard_dutch": dutch_hard(text),
        "url": r.url,
        "belgium": any(x in low for x in BELGIUM_MARKERS),
    }, None


def collect_cerba_jobs():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "fr-BE,fr;q=0.9"})

    seen = 0
    candidates = 0
    kept = []
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    detail_errors = 0

    for jid in SEED_IDS:
        seen += 1
        try:
            row, state = _detail(s, jid)
        except Exception:
            detail_errors += 1
            continue

        if state == "closed":
            closed += 1
            continue
        if not row:
            detail_errors += 1
            continue
        if not row["belgium"]:
            rejected_geo += 1
            continue
        if not title_is_target(row["title"]):
            continue

        candidates += 1

        if len(row["description"]) < 250:
            detail_errors += 1
            continue
        if row["hard_dutch"]:
            rejected_language += 1
            continue

        kept.append(
            JobOffer(
                source="CERBA",
                external_id=row["external_id"],
                title=row["title"],
                company="Cerba HealthCare Belgium",
                location=row["location"],
                description=row["description"],
                url=row["url"],
                date_published=None,
                contract_type=None,
                language=None,
            )
        )

    metrics = {
        "seen": seen,
        "candidates": candidates,
        "kept": len(kept),
        "non_target": max(0, seen - candidates),
        "rejected_language": rejected_language,
        "rejected_geo": rejected_geo,
        "closed": closed,
        "detail_errors": detail_errors,
    }
    publish_metrics("CERBA", metrics)

    print()
    print("=" * 88)
    print("CERBA HEALTHCARE BELGIUM")
    print("=" * 88)
    for k, v in metrics.items():
        print(f"{k:<20}: {v}")
    for job in kept:
        print("KEEP |", job.title, "|", job.location)

    return kept
