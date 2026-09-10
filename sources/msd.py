from __future__ import annotations

import json
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from database.models import JobOffer
from sources.batch4_engine import clean, dutch_hard, title_is_target, publish_metrics
from sources.phenom import (
    PhenomClient,
    job_external_id,
    job_location,
    job_posted_date,
    job_title,
    phenom_jobs,
    phenom_total,
)

MSD_VERSION = "1.1"
HOST = "https://jobs.msd.com"
CACHE = Path(__file__).resolve().parents[1] / "logs" / "msd_phenom_cache"

CLIENT = PhenomClient(
    host=HOST,
    locale_path="/gb/en",
    lang="en_gb",
    country="gb",
    page_id="page20",
    cache_dir=CACHE,
)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/152 Safari/537.36"


def _belgium_row(row):
    loc = clean(job_location(row)).lower()
    raw = clean(json.dumps(row, ensure_ascii=False)).lower()
    return "belgium" in loc or "belgium" in raw or "belgique" in raw


def _detail(url, title, location):
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en-GB,en;q=0.9,fr-BE;q=0.8"})
    r = s.get(url, timeout=30, allow_redirects=True)
    if r.status_code in {404, 410}:
        return {"closed": True}
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    text = clean(soup.get_text(" ", strip=True))
    h1 = soup.find("h1")
    return {
        "closed": False,
        "title": clean(h1.get_text(" ", strip=True)) if h1 else title,
        "location": location,
        "description": text,
    }


def collect_msd_jobs():
    rows_all = []
    errors = 0
    offset = 0
    total = None

    for _ in range(5):
        payload, error = CLIENT.search(
            keywords="",
            selected_fields={"country": ["Belgium"]},
            offset=offset,
            size=50,
        )
        if not payload:
            errors += 1
            break
        rows = phenom_jobs(payload)
        if total is None:
            total = phenom_total(payload)
        if not rows:
            break
        rows_all.extend(rows)
        offset += len(rows)
        if len(rows) < 50 or (total and offset >= total):
            break

    trusted = [row for row in rows_all if _belgium_row(row)]
    candidates = [row for row in trusted if title_is_target(job_title(row))]

    kept = []
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    detail_errors = errors

    for row in candidates:
        url = CLIENT.public_job_url(row)
        if not url:
            detail_errors += 1
            continue
        try:
            detail = _detail(url, clean(job_title(row)), clean(job_location(row)))
        except Exception:
            detail_errors += 1
            continue
        if detail.get("closed"):
            closed += 1
            continue
        description = clean(detail.get("description"))
        if len(description) < 250:
            detail_errors += 1
            continue
        if dutch_hard(description):
            rejected_language += 1
            continue
        kept.append(
            JobOffer(
                source="MSD",
                external_id=clean(job_external_id(row)),
                title=clean(detail.get("title")),
                company="MSD Belgium",
                location=clean(detail.get("location")) or "Belgium",
                description=description,
                url=url,
                date_published=clean(job_posted_date(row)) or None,
                contract_type=None,
                language=None,
            )
        )

    metrics = {
        "seen": len(trusted),
        "candidates": len(candidates),
        "kept": len(kept),
        "non_target": max(0, len(trusted) - len(candidates)),
        "rejected_language": rejected_language,
        "rejected_geo": rejected_geo,
        "closed": closed,
        "detail_errors": detail_errors,
    }
    publish_metrics("MSD", metrics)

    print()
    print("=" * 88)
    print("MSD BELGIUM - PHENOM")
    print("=" * 88)
    print("Facet total          :", total)
    for k, v in metrics.items():
        print(f"{k:<20}: {v}")
    for job in kept:
        print("KEEP |", job.title, "|", job.location)

    return kept
