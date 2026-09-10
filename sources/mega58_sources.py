from __future__ import annotations

import json
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from database.models import JobOffer
from sources.batch4_engine import clean, dutch_hard, title_is_target, publish_metrics
from sources.workday import (
    WorkdayClient,
    parse_workday_detail,
    posting_date,
    posting_external_path,
    posting_id,
    posting_location,
    posting_rows,
    posting_title,
    posting_total,
)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/152 Safari/537.36"
TIMEOUT = 30

_LAST_DIAG = {}

BLOCK = re.compile(
    r"\b(?:senior|principal|director|head|manager|management|team\s+leader|leader|lead|supervisor)\b",
    re.I,
)

EXTRA_TARGETS = (
    re.compile(r"\bdata coordinator\b", re.I),
    re.compile(r"\bdata governance\b", re.I),
    re.compile(r"\bpower\s*bi\b", re.I),
    re.compile(r"\bmaster data\b", re.I),
)


def _target(title):
    title = clean(title)
    if not title or BLOCK.search(title):
        return False
    return title_is_target(title) or any(p.search(title) for p in EXTRA_TARGETS)


def _publish(source, seen, candidates, jobs, *, rejected_language=0,
             rejected_geo=0, closed=0, detail_errors=0, diag=None):
    metrics = {
        "seen": int(seen),
        "candidates": int(candidates),
        "kept": len(jobs),
        "non_target": max(0, int(seen) - int(candidates)),
        "rejected_language": int(rejected_language),
        "rejected_geo": int(rejected_geo),
        "closed": int(closed),
        "detail_errors": int(detail_errors),
    }
    publish_metrics(source, metrics)
    _LAST_DIAG[source] = dict(diag or {})
    _LAST_DIAG[source]["metrics"] = dict(metrics)

    print()
    print("=" * 88)
    print(source)
    print("=" * 88)
    for k, v in metrics.items():
        print(f"{k:<20}: {v}")
    for job in jobs:
        print("KEEP |", job.title, "|", job.location)

    return jobs


def get_mega58_diag(source):
    return dict(_LAST_DIAG.get(str(source).upper(), {}))


# ---------------------------------------------------------------------------
# MEDPACE
# ---------------------------------------------------------------------------

MEDPACE_FALLBACK_IDS = ("12654", "12414")


def _medpace_detail(jid):
    url = f"https://careers.medpace.com/jobs/{jid}?lang=en-us"
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept-Language": "en-US,en;q=0.9,fr-BE;q=0.8",
    })
    r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
    if r.status_code in {404, 410}:
        return None, "closed"
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    text = clean(soup.get_text(" ", strip=True))

    title = ""
    location = ""
    description = text
    date_posted = ""

    for script in soup.find_all("script", type=lambda x: x and "ld+json" in x.lower()):
        raw = script.string or script.get_text() or ""
        try:
            data = json.loads(raw)
        except Exception:
            continue

        stack = data if isinstance(data, list) else [data]
        while stack:
            obj = stack.pop()
            if isinstance(obj, list):
                stack.extend(obj)
                continue
            if not isinstance(obj, dict):
                continue

            if isinstance(obj.get("@graph"), list):
                stack.extend(obj["@graph"])

            typ = obj.get("@type")
            types = typ if isinstance(typ, list) else [typ]
            if not any(str(x).lower() == "jobposting" for x in types if x):
                continue

            title = clean(obj.get("title") or obj.get("name"))
            location = clean(json.dumps(
                obj.get("jobLocation") or obj.get("applicantLocationRequirements"),
                ensure_ascii=False,
            ))
            date_posted = clean(obj.get("datePosted"))

            html_desc = obj.get("description") or ""
            parsed = clean(BeautifulSoup(str(html_desc), "html.parser").get_text(" ", strip=True))
            if len(parsed) >= 250:
                description = parsed
            break

    if not title:
        h1 = soup.find("h1")
        if h1:
            title = clean(h1.get_text(" ", strip=True))

    return {
        "jid": jid,
        "url": r.url,
        "title": title,
        "location": location,
        "description": description,
        "date_posted": date_posted,
        "belgium": bool(re.search(r"\b(?:Belgium|Leuven)\b", location + " " + text[:2500], re.I)),
    }, None


def collect_medpace_jobs():
    source = "MEDPACE"
    company = "Medpace"

    ids = set()
    discovery_pages = [
        "https://careers.medpace.com/jobs/locations/country/Belgium",
        "https://careers.medpace.com/jobs/locations/city/Leuven",
    ]

    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})

    listing_http = []
    for page in discovery_pages:
        try:
            r = s.get(page, timeout=TIMEOUT, allow_redirects=True)
            listing_http.append((r.url, r.status_code))
            if r.status_code != 200:
                continue
            raw = r.text or ""
            for pattern in (
                r'/jobs/(\d+)(?:\?[^"\'\s<>]*)?',
                r'"jobId"\s*:\s*"?(\d+)"?',
                r'"reqId"\s*:\s*"?(\d+)"?',
            ):
                ids.update(re.findall(pattern, raw, re.I))
        except Exception:
            pass

    # Stable safety fallback: these two Leuven data jobs were live-validated
    # during Mega Batch 5.5 and are revalidated on every run before use.
    ids.update(MEDPACE_FALLBACK_IDS)

    jobs = []
    candidates = 0
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    errors = 0
    geo_truth = 0

    for jid in sorted(ids):
        try:
            row, state = _medpace_detail(jid)
        except Exception:
            errors += 1
            continue

        if state == "closed":
            closed += 1
            continue
        if not row:
            errors += 1
            continue

        if not row["belgium"]:
            continue

        geo_truth += 1

        if not _target(row["title"]):
            continue

        candidates += 1

        if len(row["description"]) < 250:
            errors += 1
            continue

        if dutch_hard(row["description"]):
            rejected_language += 1
            continue

        jobs.append(
            JobOffer(
                source=source,
                external_id=jid,
                title=row["title"],
                company=company,
                location=row["location"] or "Leuven, Belgium",
                description=row["description"],
                url=row["url"],
                date_published=row["date_posted"] or None,
                contract_type=None,
                language=None,
            )
        )

    return _publish(
        source,
        len(ids),
        candidates,
        jobs,
        rejected_language=rejected_language,
        rejected_geo=rejected_geo,
        closed=closed,
        detail_errors=errors,
        diag={
            "listing_http": listing_http,
            "discovered_plus_fallback_ids": sorted(ids),
            "geo_truth_count": geo_truth,
            "fallback_ids": list(MEDPACE_FALLBACK_IDS),
        },
    )


# ---------------------------------------------------------------------------
# NATIVE WORKDAY HELPER
# ---------------------------------------------------------------------------

def _workday_collect(source, company, host, tenant, site, public_locale):
    cache = Path(__file__).resolve().parents[1] / "logs" / f"{source.lower()}_workday_cache"

    client = WorkdayClient(
        host=host,
        tenant=tenant,
        site=site,
        public_locale=public_locale,
        cache_dir=cache,
    )

    payload, from_cache, error = client.search(
        search_text="Belgium",
        applied_facets=None,
        offset=0,
        limit=50,
        use_cache=False,
    )

    if not payload:
        return _publish(
            source, 0, 0, [],
            detail_errors=1,
            diag={"transport_error": error, "geo_truth_count": 0},
        )

    rows = posting_rows(payload)
    total = posting_total(payload)

    belgium_rows = []
    for row in rows:
        loc = clean(posting_location(row))
        raw = json.dumps(row, ensure_ascii=False)
        if re.search(r"\bBelgium\b", loc + " " + raw, re.I):
            belgium_rows.append(row)

    candidates = [row for row in belgium_rows if _target(posting_title(row))]

    jobs = []
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    errors = 0

    for row in candidates:
        path = posting_external_path(row)
        if not path:
            errors += 1
            continue

        detail_payload, _, detail_error = client.detail(path, use_cache=False)
        if not detail_payload:
            errors += 1
            continue

        parsed = parse_workday_detail(detail_payload)
        if not isinstance(parsed, dict):
            parsed = {}

        title = clean(parsed.get("title") or posting_title(row))
        location = clean(parsed.get("location") or posting_location(row))
        description = clean(
            parsed.get("description")
            or parsed.get("job_description")
            or parsed.get("matching_text")
        )

        if not description:
            # Generic Workday parser shape differs between versions;
            # public JSON is still safe text fallback.
            description = clean(json.dumps(detail_payload, ensure_ascii=False))

        if len(description) < 250:
            errors += 1
            continue

        if not re.search(r"\bBelgium\b", location + " " + json.dumps(detail_payload, ensure_ascii=False), re.I):
            rejected_geo += 1
            continue

        if dutch_hard(description):
            rejected_language += 1
            continue

        ext_id = clean(posting_id(row))
        jobs.append(
            JobOffer(
                source=source,
                external_id=ext_id or path.rsplit("/", 1)[-1],
                title=title,
                company=company,
                location=location or "Belgium",
                description=description,
                url=client.public_url(path),
                date_published=clean(posting_date(row)) or None,
                contract_type=None,
                language=None,
            )
        )

    return _publish(
        source,
        len(belgium_rows),
        len(candidates),
        jobs,
        rejected_language=rejected_language,
        rejected_geo=rejected_geo,
        closed=closed,
        detail_errors=errors,
        diag={
            "search_total": total,
            "search_rows": len(rows),
            "belgium_rows": len(belgium_rows),
            "geo_truth_count": len(belgium_rows),
            "from_cache": from_cache,
            "transport_error": error,
            "native_helper": "sources.workday.WorkdayClient",
        },
    )


def collect_univercells_tech_jobs():
    return _workday_collect(
        "UNIVERCELLS_TECH",
        "Donaldson / Univercells Technologies",
        "https://donaldson.wd115.myworkdayjobs.com",
        "donaldson",
        "DonaldsonCareers",
        "en-US",
    )


def collect_lhoist_jobs():
    return _workday_collect(
        "LHOIST",
        "Lhoist",
        "https://lhoist.wd3.myworkdayjobs.com",
        "lhoist",
        "Careers",
        "en-US",
    )
