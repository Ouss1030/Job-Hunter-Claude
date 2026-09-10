from __future__ import annotations

import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from database.models import JobOffer
from sources.belgium_locations import BELGIUM, classify_belgium_location
from sources.source_metrics import publish_source_metrics
from sources.batch2_radancy_country_engine import dutch_hard, title_is_target
from sources.phenom import PhenomClient, phenom_jobs, phenom_total

ROCHE_VERSION = "1.0"


_GEO_RUNTIME_COUNTS = {"BELGIUM": 0, "FOREIGN": 0, "UNKNOWN": 0}


def _geo_status_key(decision):
    status = getattr(decision, "status", "UNKNOWN")
    status = getattr(status, "value", status)
    key = str(status or "UNKNOWN").upper()
    if "." in key:
        key = key.rsplit(".", 1)[-1]
    if key not in _GEO_RUNTIME_COUNTS:
        key = "UNKNOWN"
    return key


def _reset_geo_runtime_counters():
    for key in _GEO_RUNTIME_COUNTS:
        _GEO_RUNTIME_COUNTS[key] = 0


def _geo_runtime_counters():
    return dict(_GEO_RUNTIME_COUNTS)

HOST = "https://careers.roche.com"
LOCALE_PATH = "/global/en"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/152.0.0.0 Safari/537.36"
)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _first(item, *keys):
    if not isinstance(item, dict):
        return ""
    for key in keys:
        value = item.get(key)
        if value not in (None, "", [], {}):
            return clean(value)
    return ""


def _location(item):
    return (
        _first(item, "cityStateCountry", "location", "address")
        or clean(" | ".join(
            x for x in [
                _first(item, "city"),
                _first(item, "state"),
                _first(item, "country"),
            ]
            if x
        ))
    )


def _row(item):
    return {
        "title": _first(item, "title", "jobTitle", "name"),
        "location": _location(item),
        "country": _first(item, "country"),
        "url": _first(item, "applyUrl", "jobUrl", "url"),
        "external_id": _first(item, "jobId", "reqId", "requisitionId", "id"),
        "date_published": _first(item, "postedDate", "dateCreated"),
        "contract_type": _first(item, "type"),
        "teaser": _first(item, "descriptionTeaser"),
    }


def _client():
    return PhenomClient(
        host=HOST,
        locale_path=LOCALE_PATH,
        lang="en_global",
        country="global",
        cache_dir=None,
        timeout=30,
    )


def collect_roche_belgium_rows():
    client = _client()

    ok, error = client.warmup()
    if not ok:
        raise RuntimeError(f"Roche Phenom warmup failed: {error}")

    rows = []
    offset = 0
    size = 50
    reported_total = None

    while True:
        payload, error = client.search(
            keywords="",
            selected_fields={"country": ["Belgium"]},
            offset=offset,
            size=size,
            retries=3,
        )
        if error or payload is None:
            raise RuntimeError(f"Roche Phenom search failed: {error}")

        page = phenom_jobs(payload)
        if reported_total is None:
            reported_total = int(phenom_total(payload) or 0)

        for item in page:
            row = _row(item)
            decision = classify_belgium_location(row["location"])
            _GEO_RUNTIME_COUNTS[_geo_status_key(decision)] += 1
            if decision.status != BELGIUM:
                continue
            rows.append(row)

        offset += len(page)

        if not page:
            break
        if reported_total and offset >= reported_total:
            break
        if len(page) < size:
            break
        if offset >= 2000:
            break

    dedup = {}
    for row in rows:
        key = row["external_id"] or row["url"] or f"{row['title']}|{row['location']}"
        dedup[key] = row

    return list(dedup.values())


def _workday_parts(apply_url):
    parsed = urlparse(apply_url)
    host = f"{parsed.scheme}://{parsed.netloc}"

    # Expected Roche public URL:
    # /roche-ext/job/Brussels/Title_REQ/apply
    match = re.search(r"^/([^/]+)/job/(.+?)(?:/apply)?/?$", parsed.path, flags=re.I)
    if not match:
        raise ValueError(f"Unsupported Roche Workday apply URL: {apply_url}")

    site = match.group(1)
    job_path = match.group(2).strip("/")
    tenant = "roche"

    return host, tenant, site, job_path


def fetch_roche_workday_detail(row):
    apply_url = clean(row.get("url"))
    if not apply_url:
        raise ValueError("Roche applyUrl missing.")

    host, tenant, site, job_path = _workday_parts(apply_url)

    endpoint = f"{host}/wday/cxs/{tenant}/{site}/job/{job_path}"

    response = requests.get(
        endpoint,
        timeout=30,
        headers={
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8",
            "Referer": apply_url,
        },
    )

    if response.status_code in {404, 410}:
        return {"closed": True, "http": response.status_code}

    response.raise_for_status()
    payload = response.json()

    info = payload.get("jobPostingInfo") or {}
    if not isinstance(info, dict) or not info:
        raise RuntimeError("Roche Workday jobPostingInfo missing.")

    raw_description = info.get("jobDescription") or ""
    description = clean(
        BeautifulSoup(str(raw_description), "html.parser").get_text(" ", strip=True)
    )

    return {
        "closed": False,
        "http": response.status_code,
        "description": description,
        "title": clean(info.get("title")) or row.get("title") or "",
        "location": clean(info.get("location")) or row.get("location") or "",
        "date_published": clean(info.get("startDate")) or row.get("date_published") or "",
        "contract_type": clean(info.get("timeType")) or row.get("contract_type") or "",
        "endpoint": endpoint,
    }


def probe_roche_belgium():
    rows = collect_roche_belgium_rows()

    detail = None
    if rows:
        detail = fetch_roche_workday_detail(rows[0])

    return {
        "seen": len(rows),
        "unique_ids": len({x["external_id"] for x in rows if x["external_id"]}),
        "all_belgium": all(
            classify_belgium_location(x["location"]).status == BELGIUM
            for x in rows
        ),
        "sample_detail_ok": bool(
            detail
            and not detail.get("closed")
            and len(clean(detail.get("description"))) >= 250
        ),
        "sample_detail_length": len(clean(detail.get("description"))) if detail else 0,
        "rows": rows,
        "detail": detail,
    }


def _publish_metrics(payload):
    publish_source_metrics("ROCHE", payload)


def collect_roche_jobs():
    _reset_geo_runtime_counters()
    rows = collect_roche_belgium_rows()
    candidates = [row for row in rows if title_is_target(row["title"])]

    jobs = []
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    detail_errors = 0

    for row in candidates:
        if classify_belgium_location(row["location"]).status != BELGIUM:
            rejected_geo += 1
            continue

        try:
            detail = fetch_roche_workday_detail(row)
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

        external_id = clean(row.get("external_id"))
        if not external_id:
            external_id = clean(row.get("url")).rstrip("/").split("/")[-2]

        jobs.append(
            JobOffer(
                source="ROCHE",
                external_id=external_id,
                title=clean(detail.get("title") or row["title"]),
                company="Roche",
                location=clean(detail.get("location") or row["location"]),
                description=description,
                url=row["url"],
                date_published=clean(detail.get("date_published")) or None,
                contract_type=clean(detail.get("contract_type")) or None,
                language=None,
            )
        )

    _geo = _geo_runtime_counters()
    metrics = {
        "seen": len(rows),
        "target_title": len(candidates),
        "non_target": max(0, len(rows) - len(candidates)),
        "detail_ok": len(jobs) + rejected_language,
        "detail_failed": detail_errors,
        "geography_accepted": len(rows),
        "geography_rejected": int(_geo.get("FOREIGN", 0)) + rejected_geo,
        "geography_unknown": int(_geo.get("UNKNOWN", 0)),
        "language_rejected": rejected_language,
        "converted": len(jobs),
        "persisted": None,
        "errors": detail_errors,
        "candidates": len(candidates),
        "kept": len(jobs),
        "rejected_language": rejected_language,
        "rejected_geo": rejected_geo,
        "closed": closed,
        "detail_errors": detail_errors,
    }

    _publish_metrics(metrics)

    print()
    print("=" * 88)
    print("ROCHE - PHENOM BELGIUM + WORKDAY DETAIL")
    print("=" * 88)
    for key, value in metrics.items():
        print(f"{key:<20}: {value}")
    for job in jobs:
        print("KEEP |", job.title, "|", job.location)

    return jobs
