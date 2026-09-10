from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from database.models import JobOffer
from sources.batch4_engine import clean, dutch_hard, title_is_target, publish_metrics
from sources.successfactors import (
    SuccessFactorsClient,
    extract_jobposting_jsonld,
    jsonld_location,
    parse_listing_rows,
    parse_total,
)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/152 Safari/537.36"
TIMEOUT = 30
MIN_DESCRIPTION = 220

_LAST_DIAG = {}

BLOCK_TITLE = re.compile(
    r"\b(?:senior|sr\.?|principal|staff|director|head|manager|management|"
    r"team\s+leader|leader|lead|supervisor|intern(?:ship)?|trainee|apprentice|phd)\b",
    re.I,
)

EXTRA_TARGETS = (
    re.compile(r"\bdata coordinator\b", re.I),
    re.compile(r"\bdata governance\b", re.I),
    re.compile(r"\bpower\s*bi\b", re.I),
    re.compile(r"\bmaster data\b", re.I),
    re.compile(r"\bdata quality\b", re.I),
    re.compile(r"\bdata steward\b", re.I),
    re.compile(r"\bquality assurance\b", re.I),
    re.compile(r"\bquality control\b", re.I),
    re.compile(r"\bvalidation\b", re.I),
    re.compile(r"\blaborantin\b", re.I),
    re.compile(r"\blab(?:oratory)?\s+(?:technician|analyst)\b", re.I),
)


def _target(title):
    title = clean(title)
    if not title or BLOCK_TITLE.search(title):
        return False
    return title_is_target(title) or any(p.search(title) for p in EXTRA_TARGETS)


def _session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.2",
    })
    return s


def _publish(source, seen, candidates, jobs, *,
             rejected_language=0, rejected_geo=0, closed=0,
             detail_errors=0, diag=None):
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
    print("=" * 90)
    print(source)
    print("=" * 90)
    for k, v in metrics.items():
        print(f"{k:<22}: {v}")
    for job in jobs:
        print("KEEP |", job.title, "|", job.location)

    return jobs


def get_mega59_diag(source):
    return dict(_LAST_DIAG.get(str(source).upper(), {}))


def _html_text(value):
    return clean(BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True))


def _job(source, company, external_id, title, location, description, url, date_published=None):
    return JobOffer(
        source=source,
        external_id=clean(external_id),
        title=clean(title),
        company=company,
        location=clean(location) or "Belgium",
        description=clean(description),
        url=clean(url),
        date_published=clean(date_published) or None,
        contract_type=None,
        language=None,
    )


# =============================================================================
# WORKDAY - exact successful Mega 5.5 request: limit=20
# =============================================================================

def _workday_direct20(source, company, board_url, host, tenant, site, public_prefix):
    s = _session()

    board = s.get(board_url, timeout=TIMEOUT, allow_redirects=True)
    board.raise_for_status()

    endpoint = f"{host}/wday/cxs/{tenant}/{site}/jobs"
    payload = {
        "appliedFacets": {},
        "limit": 20,
        "offset": 0,
        "searchText": "Belgium",
    }

    response = s.post(
        endpoint,
        json=payload,
        headers={
            "Content-Type": "application/json",
            "Referer": board.url,
        },
        timeout=TIMEOUT,
    )

    cxs_http = response.status_code
    if cxs_http != 200:
        return _publish(
            source, 0, 0, [],
            detail_errors=1,
            diag={
                "board_http": board.status_code,
                "cxs_http": cxs_http,
                "limit": 20,
                "geo_truth_count": 0,
                "response_preview": clean(response.text)[:500],
            },
        )

    data = response.json()
    rows = data.get("jobPostings") or []
    be_rows = []

    for row in rows:
        if not isinstance(row, dict):
            continue
        blob = clean(row.get("locationsText")) + " " + json.dumps(row, ensure_ascii=False)
        if re.search(r"\bBelgium\b", blob, re.I):
            be_rows.append(row)

    candidates = [row for row in be_rows if _target(row.get("title"))]

    jobs = []
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    errors = 0
    detail_probe_ok = 0

    rows_to_probe = candidates if candidates else be_rows[:1]

    details = {}
    for row in rows_to_probe:
        path = clean(row.get("externalPath"))
        if not path:
            errors += 1
            continue

        detail_url = f"{host}/wday/cxs/{tenant}/{site}{path}"
        try:
            rr = s.get(detail_url, headers={"Referer": board.url}, timeout=TIMEOUT)
            if rr.status_code in {404, 410}:
                details[path] = {"closed": True}
                continue
            rr.raise_for_status()
            details[path] = {"closed": False, "payload": rr.json()}
            detail_probe_ok += 1
        except Exception:
            details[path] = {"error": True}
            errors += 1

    for row in candidates:
        path = clean(row.get("externalPath"))
        if not path:
            continue

        cached = details.get(path)
        if cached is None:
            detail_url = f"{host}/wday/cxs/{tenant}/{site}{path}"
            try:
                rr = s.get(detail_url, headers={"Referer": board.url}, timeout=TIMEOUT)
                if rr.status_code in {404, 410}:
                    closed += 1
                    continue
                rr.raise_for_status()
                cached = {"closed": False, "payload": rr.json()}
                detail_probe_ok += 1
            except Exception:
                errors += 1
                continue

        if cached.get("error"):
            continue
        if cached.get("closed"):
            closed += 1
            continue

        payload_detail = cached.get("payload") or {}
        info = payload_detail.get("jobPostingInfo") or payload_detail

        title = clean(info.get("title") or row.get("title"))
        location = clean(
            info.get("location")
            or info.get("locationText")
            or row.get("locationsText")
        )

        raw_desc = (
            info.get("jobDescription")
            or info.get("description")
            or info.get("externalJobDescription")
            or ""
        )
        description = _html_text(raw_desc)
        if len(description) < MIN_DESCRIPTION:
            description = clean(json.dumps(info, ensure_ascii=False))

        if len(description) < MIN_DESCRIPTION:
            errors += 1
            continue

        geo_blob = location + " " + json.dumps(info, ensure_ascii=False)
        if not re.search(r"\bBelgium\b", geo_blob, re.I):
            rejected_geo += 1
            continue

        if dutch_hard(description):
            rejected_language += 1
            continue

        ext_id = clean(
            info.get("jobReqId")
            or info.get("jobRequisitionId")
            or row.get("bulletFields")
            or path.rsplit("/", 1)[-1]
        )
        public_url = f"{host}/{public_prefix}{path}"

        jobs.append(_job(
            source,
            company,
            ext_id,
            title,
            location,
            description,
            public_url,
            info.get("postedOn") or info.get("startDate"),
        ))

    return _publish(
        source,
        len(be_rows),
        len(candidates),
        jobs,
        rejected_language=rejected_language,
        rejected_geo=rejected_geo,
        closed=closed,
        detail_errors=errors,
        diag={
            "board_http": board.status_code,
            "cxs_http": cxs_http,
            "limit": 20,
            "announced_total": data.get("total"),
            "returned_rows": len(rows),
            "belgium_rows": len(be_rows),
            "geo_truth_count": len(be_rows),
            "detail_probe_ok": detail_probe_ok,
        },
    )


def collect_univercells_tech_jobs():
    return _workday_direct20(
        "UNIVERCELLS_TECH",
        "Donaldson / Univercells Technologies",
        "https://donaldson.wd115.myworkdayjobs.com/en-US/DonaldsonCareers",
        "https://donaldson.wd115.myworkdayjobs.com",
        "donaldson",
        "DonaldsonCareers",
        "en-US/DonaldsonCareers",
    )


def collect_lhoist_jobs():
    return _workday_direct20(
        "LHOIST",
        "Lhoist",
        "https://lhoist.wd3.myworkdayjobs.com/Careers",
        "https://lhoist.wd3.myworkdayjobs.com",
        "lhoist",
        "Careers",
        "Careers",
    )


# =============================================================================
# PAREXEL - Belgium Radancy page, REAL /job/ links only
# =============================================================================

def collect_parexel_jobs():
    source = "PAREXEL"
    company = "Parexel"
    listing = "https://jobs.parexel.com/en/location/belgium-jobs/877/2802361/2"

    s = _session()
    r = s.get(listing, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    links = {}

    for a in soup.find_all("a", href=True):
        u = urljoin(r.url, a["href"]).split("#", 1)[0]
        m = re.search(r"/en/job/[^/?#]+/\d+/(\d+)$", u, re.I)
        if not m:
            continue
        links[m.group(1)] = (u, clean(a.get_text(" ", strip=True)))

    seen = len(links)
    candidates = 0
    jobs = []
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    errors = 0
    geo_truth = 0
    detail_probe_ok = 0

    for jid, (u, listing_title) in sorted(links.items()):
        try:
            rr = s.get(u, timeout=TIMEOUT, allow_redirects=True)
            if rr.status_code in {404, 410}:
                closed += 1
                continue
            rr.raise_for_status()
        except Exception:
            errors += 1
            continue

        detail_probe_ok += 1
        dsoup = BeautifulSoup(rr.text, "html.parser")
        full_text = clean(dsoup.get_text(" ", strip=True))

        obj = extract_jobposting_jsonld(dsoup)
        title = clean(obj.get("title") or listing_title)
        location = jsonld_location(obj)
        desc = _html_text(obj.get("description"))
        if len(desc) < MIN_DESCRIPTION:
            desc = full_text

        # A Belgium result may be multi-location. Require explicit Belgium in JSON-LD/text.
        geo_blob = location + " " + json.dumps(
            obj.get("jobLocation") or {},
            ensure_ascii=False,
        )
        is_be = bool(re.search(r"\b(?:Belgium|Belgique|België)\b", geo_blob, re.I))
        if is_be:
            geo_truth += 1

        if not _target(title):
            continue
        candidates += 1

        if not is_be:
            rejected_geo += 1
            continue
        if dutch_hard(desc):
            rejected_language += 1
            continue

        jobs.append(_job(
            source, company, jid, title, location or "Belgium",
            desc, rr.url, obj.get("datePosted"),
        ))

    return _publish(
        source, seen, candidates, jobs,
        rejected_language=rejected_language,
        rejected_geo=rejected_geo,
        closed=closed,
        detail_errors=errors,
        diag={
            "listing_http": r.status_code,
            "listing_links": seen,
            "geo_truth_count": geo_truth,
            "detail_probe_ok": detail_probe_ok,
        },
    )


# =============================================================================
# POLYPEPTIDE - Braine-l'Alleud location page + strict detail geo
# =============================================================================

def collect_polypeptide_jobs():
    source = "POLYPEPTIDE"
    company = "PolyPeptide Belgium"
    listing = "https://careers.polypeptide.com/locations/braine-l-alleud"

    s = _session()
    r = s.get(listing, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    links = {}

    for a in soup.find_all("a", href=True):
        u = urljoin(r.url, a["href"]).split("#", 1)[0]
        m = re.search(r"^https://careers\.polypeptide\.com/jobs/(\d+)-[^/?#]+$", u, re.I)
        if not m:
            continue
        links[m.group(1)] = (u, clean(a.get_text(" ", strip=True)))

    seen = len(links)
    candidates = 0
    jobs = []
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    errors = 0
    geo_truth = 0
    detail_probe_ok = 0

    for jid, (u, listing_title) in sorted(links.items()):
        try:
            rr = s.get(u, timeout=TIMEOUT, allow_redirects=True)
            if rr.status_code in {404, 410}:
                closed += 1
                continue
            rr.raise_for_status()
        except Exception:
            errors += 1
            continue

        detail_probe_ok += 1
        dsoup = BeautifulSoup(rr.text, "html.parser")
        full_text = clean(dsoup.get_text(" ", strip=True))

        obj = extract_jobposting_jsonld(dsoup)
        title = clean(obj.get("title") or listing_title)
        location = jsonld_location(obj)
        raw_loc = json.dumps(obj.get("jobLocation") or {}, ensure_ascii=False)

        is_be = bool(
            re.search(r"\b(?:BE|Belgium|Belgique|België)\b", raw_loc, re.I)
            and re.search(r"Braine", location + " " + raw_loc, re.I)
        )

        if is_be:
            geo_truth += 1

        desc = _html_text(obj.get("description"))
        if len(desc) < MIN_DESCRIPTION:
            desc = full_text

        if not _target(title):
            continue
        candidates += 1

        if not is_be:
            rejected_geo += 1
            continue
        if dutch_hard(desc):
            rejected_language += 1
            continue

        jobs.append(_job(
            source, company, jid, title, location or "Braine-l'Alleud, Belgium",
            desc, rr.url, obj.get("datePosted"),
        ))

    return _publish(
        source, seen, candidates, jobs,
        rejected_language=rejected_language,
        rejected_geo=rejected_geo,
        closed=closed,
        detail_errors=errors,
        diag={
            "listing_http": r.status_code,
            "listing_links": seen,
            "geo_truth_count": geo_truth,
            "detail_probe_ok": detail_probe_ok,
            "strict_location": "Braine-l'Alleud, Belgium",
        },
    )


# =============================================================================
# JOHN COCKERILL - existing SuccessFactors engine
# =============================================================================

def collect_john_cockerill_jobs():
    source = "JOHN_COCKERILL"
    company = "John Cockerill"

    client = SuccessFactorsClient(
        base_url="https://careers.johncockerill.com",
        all_jobs_path="/viewalljobs/",
        cache_dir=Path(__file__).resolve().parents[1] / "logs" / "john_cockerill_sf_cache",
        page_size=50,
    )

    all_rows = {}
    pages = 0
    errors = 0
    announced_total = None

    for offset in (0, 50, 100, 150, 200, 250):
        html, from_cache, error = client.listing_html(offset=offset, use_cache=False)
        if not html:
            if error:
                errors += 1
            break

        rows = parse_listing_rows(html, client.base_url)
        if announced_total is None:
            announced_total = parse_total(html)

        pages += 1
        for row in rows:
            ext = clean(row.get("external_id"))
            if ext:
                all_rows[ext] = row

        if len(rows) < 50:
            break
        if announced_total and len(all_rows) >= announced_total:
            break

    # Belgian industrial sites/locations.
    be_markers = (
        "belgium", "belgique", ", be", "sprimont", "seraing", "liège", "liege",
        "ans", "herstal", "charleroi", "brussels", "bruxelles",
    )

    be_rows = []
    for row in all_rows.values():
        blob = clean(row.get("location")) + " " + clean(row.get("url"))
        if any(x in blob.lower() for x in be_markers):
            be_rows.append(row)

    candidates = [row for row in be_rows if _target(row.get("title"))]

    jobs = []
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    detail_errors = errors
    detail_probe_ok = 0

    rows_to_probe = candidates if candidates else be_rows[:1]

    details = {}
    for row in rows_to_probe:
        ext = clean(row.get("external_id"))
        try:
            html, from_cache, error = client.detail_html(
                row.get("url"),
                external_id=ext,
                use_cache=False,
            )
        except Exception:
            html = None
            error = "detail exception"

        if not html:
            detail_errors += 1
            details[ext] = None
            continue

        details[ext] = html
        detail_probe_ok += 1

    for row in candidates:
        ext = clean(row.get("external_id"))
        html = details.get(ext)

        if html is None and ext not in details:
            html, _, error = client.detail_html(
                row.get("url"),
                external_id=ext,
                use_cache=False,
            )
            if not html:
                detail_errors += 1
                continue
            detail_probe_ok += 1

        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")
        full_text = clean(soup.get_text(" ", strip=True))
        low = full_text.lower()

        if any(x in low for x in (
            "job is no longer available",
            "position is no longer available",
            "this job has been filled",
        )):
            closed += 1
            continue

        obj = extract_jobposting_jsonld(soup)
        title = clean(obj.get("title") or row.get("title"))
        location = jsonld_location(obj) or clean(row.get("location"))
        desc = _html_text(obj.get("description"))
        if len(desc) < MIN_DESCRIPTION:
            desc = full_text

        geo_blob = location + " " + full_text[:1800]
        if not any(x in geo_blob.lower() for x in be_markers):
            rejected_geo += 1
            continue

        if dutch_hard(desc):
            rejected_language += 1
            continue

        jobs.append(_job(
            source, company, ext, title, location,
            desc, row.get("url"), obj.get("datePosted"),
        ))

    return _publish(
        source, len(be_rows), len(candidates), jobs,
        rejected_language=rejected_language,
        rejected_geo=rejected_geo,
        closed=closed,
        detail_errors=detail_errors,
        diag={
            "pages": pages,
            "all_rows": len(all_rows),
            "announced_total": announced_total,
            "belgium_rows": len(be_rows),
            "geo_truth_count": len(be_rows),
            "detail_probe_ok": detail_probe_ok,
            "engine": "sources.successfactors.SuccessFactorsClient",
        },
    )
