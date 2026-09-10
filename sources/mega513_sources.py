from __future__ import annotations

import json
import re
from urllib.parse import urljoin, quote_plus

import requests
from bs4 import BeautifulSoup

from database.models import JobOffer
from sources.batch4_engine import clean, dutch_hard, title_is_target, publish_metrics

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/152 Safari/537.36"
TIMEOUT = 30
MIN_DESC = 220

_LAST_DIAG = {}

BLOCK_TITLE = re.compile(
    r"\b(?:senior|sr\.?|principal|staff|director|head|manager|management|"
    r"team\s+leader|leader|lead|supervisor|intern(?:ship)?|stage|trainee|"
    r"apprentice|phd)\b",
    re.I,
)

EXTRA_TARGETS = (
    re.compile(r"\bdata analyst\b", re.I),
    re.compile(r"\bbusiness analyst\b", re.I),
    re.compile(r"\bbi analyst\b", re.I),
    re.compile(r"\bpower\s*bi\b", re.I),
    re.compile(r"\bdata quality\b", re.I),
    re.compile(r"\bdata steward\b", re.I),
    re.compile(r"\bmaster data\b", re.I),
    re.compile(r"\bquality assurance\b", re.I),
    re.compile(r"\bquality control\b", re.I),
    re.compile(r"\bqualification\b", re.I),
    re.compile(r"\bvalidation\b", re.I),
    re.compile(r"\blaboratory technician\b", re.I),
    re.compile(r"\blab technician\b", re.I),
    re.compile(r"\blaboratory analyst\b", re.I),
    re.compile(r"\blab analyst\b", re.I),
    re.compile(r"\blaborantin\b", re.I),
    re.compile(r"\bmicrobiology\b", re.I),
    re.compile(r"\bmicrobiologie\b", re.I),
)

BELGIUM_HINTS = (
    "belgium", "belgique", "belgië", "wavre", "brussels", "bruxelles",
    "mechelen", "machelen", "zaventem", "leuven", "liège", "liege",
    "charleroi", "gosselies", "nivelles", "seraing",
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
        "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.2",
    })
    return s


def _is_be(value):
    low = clean(value).lower()
    return any(x in low for x in BELGIUM_HINTS)


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
    print("=" * 92)
    print(source)
    print("=" * 92)
    for k, v in metrics.items():
        print(f"{k:<22}: {v}")
    for item in jobs:
        print("KEEP |", item.title, "|", item.location)

    return jobs


def get_mega513_diag(source):
    return dict(_LAST_DIAG.get(str(source).upper(), {}))


# =============================================================================
# ABBVIE
# =============================================================================

ABBVIE_HEALTH_SEEDS = {
    "R00147454": "https://careers.abbvie.com/en/job/public-affairs-and-patient-relations-manager-in-wavre-wallonia-jid-30703",
    "R00145794": "https://careers.abbvie.com/en/job/country-study-start-up-specialist-in-wavre-wallonia-jid-29117",
}


def _abbvie_detail(s, url, listing_title=""):
    r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
    if r.status_code in {404, 410}:
        return None, "closed"
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    text = clean(soup.get_text(" ", strip=True))

    h1 = soup.find("h1")
    title = clean(h1.get_text(" ", strip=True)) if h1 else clean(listing_title)

    location = ""
    for selector in (
        '[class*="location"]',
        '[class*="jobinformation"]',
        '[itemprop="jobLocation"]',
    ):
        for node in soup.select(selector):
            value = clean(node.get_text(" ", strip=True))
            if value and len(value) < 500 and _is_be(value):
                location = value
                break
        if location:
            break

    if not location:
        m = re.search(r"\b(Wavre,\s*(?:Wallonia|WBR)|Belgium)\b", text[:2500], re.I)
        if m:
            location = clean(m.group(1))

    job_id = ""
    m = re.search(r"\bJob ID:\s*([A-Z0-9-]+)", text, re.I)
    if m:
        job_id = clean(m.group(1))

    return {
        "url": r.url,
        "title": title,
        "location": location,
        "description": text,
        "job_id": job_id,
        "belgium": _is_be(location or text[:2500]),
    }, None


def collect_abbvie_jobs():
    source = "ABBVIE"
    company = "AbbVie Belgium"
    s = _session()

    links = {}
    pages_ok = 0

    # Search only target-like families + Wavre/Belgium location queries.
    queries = ("quality", "data", "analyst", "laboratory", "validation", "Wavre")
    for query in queries:
        for page in (1, 2):
            url = (
                "https://careers.abbvie.com/en/jobs"
                f"?options=&page={page}&q={quote_plus(query)}"
                "&ln=&la=0&lo=0&lr=100&li=/jobs/"
            )
            try:
                r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
                if r.status_code != 200:
                    continue
            except Exception:
                continue

            pages_ok += 1
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                u = urljoin(r.url, a["href"]).split("#", 1)[0]
                m = re.search(r"/en/job/[^/?#]+-jid-(\d+)$", u, re.I)
                if m:
                    links[m.group(1)] = (u, clean(a.get_text(" ", strip=True)))

    dynamic_links = len(links)

    # Health seeds are live-revalidated; they are never forced into the target pool.
    for seed_id, seed_url in ABBVIE_HEALTH_SEEDS.items():
        links.setdefault(seed_id, (seed_url, ""))

    seen = len(links)
    candidates = 0
    jobs = []
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    errors = 0
    detail_ok = 0
    geo_truth = 0

    # Detail target-like titles first; health seeds always checked.
    ordered = sorted(
        links.items(),
        key=lambda kv: (
            0 if _target(kv[1][1]) else 1,
            0 if kv[0] in ABBVIE_HEALTH_SEEDS else 1,
        ),
    )

    # Bound network load while preserving all target-looking links.
    target_ids = {jid for jid, (_, title) in links.items() if _target(title)}
    must_check = set(ABBVIE_HEALTH_SEEDS) | target_ids
    selected = []
    for item in ordered:
        if item[0] in must_check or len(selected) < 20:
            selected.append(item)

    for jid, (url, listing_title) in selected:
        try:
            row, state = _abbvie_detail(s, url, listing_title)
        except Exception:
            errors += 1
            continue

        if state == "closed":
            closed += 1
            continue
        if not row:
            errors += 1
            continue

        detail_ok += 1
        if row["belgium"]:
            geo_truth += 1

        if not _target(row["title"]):
            continue
        candidates += 1

        if not row["belgium"]:
            rejected_geo += 1
            continue
        if dutch_hard(row["description"]):
            rejected_language += 1
            continue
        if len(row["description"]) < MIN_DESC:
            errors += 1
            continue

        external_id = row["job_id"] or jid
        jobs.append(_job(
            source, company, external_id, row["title"], row["location"],
            row["description"], row["url"],
        ))

    return _publish(
        source, seen, candidates, jobs,
        rejected_language=rejected_language,
        rejected_geo=rejected_geo,
        closed=closed,
        detail_errors=errors,
        diag={
            "pages_ok": pages_ok,
            "dynamic_links": dynamic_links,
            "health_seed_ids": list(ABBVIE_HEALTH_SEEDS),
            "detail_probe_ok": detail_ok,
            "geo_truth_count": geo_truth,
            "engine": "careers.abbvie.com direct search + detail",
        },
    )


# =============================================================================
# CSL - official Workday
# =============================================================================

def collect_csl_jobs():
    source = "CSL"
    company = "CSL Behring Belgium"

    host = "https://csl.wd1.myworkdayjobs.com"
    tenant = "csl"

    # Workday site casing has varied in public URLs. Try official variants.
    site_variants = ("CSL_External", "csl_external")
    s = _session()

    site = ""
    board = None
    data = None
    cxs_http = None

    for candidate_site in site_variants:
        board_url = f"{host}/en-US/{candidate_site}"
        try:
            candidate_board = s.get(board_url, timeout=TIMEOUT, allow_redirects=True)
            if candidate_board.status_code != 200:
                continue
        except Exception:
            continue

        endpoint = f"{host}/wday/cxs/{tenant}/{candidate_site}/jobs"
        try:
            r = s.post(
                endpoint,
                json={
                    "appliedFacets": {},
                    "limit": 20,
                    "offset": 0,
                    "searchText": "Belgium",
                },
                headers={
                    "Content-Type": "application/json",
                    "Referer": candidate_board.url,
                },
                timeout=TIMEOUT,
            )
        except Exception:
            continue

        cxs_http = r.status_code
        if r.status_code == 200:
            site = candidate_site
            board = candidate_board
            data = r.json()
            break

    if not data or not site or board is None:
        return _publish(
            source, 0, 0, [],
            detail_errors=1,
            diag={
                "site_variants": list(site_variants),
                "cxs_http": cxs_http,
                "geo_truth_count": 0,
            },
        )

    rows = data.get("jobPostings") or []
    be_rows = []

    for row in rows:
        if not isinstance(row, dict):
            continue
        blob = clean(row.get("locationsText")) + " " + json.dumps(row, ensure_ascii=False)
        if _is_be(blob):
            be_rows.append(row)

    candidates = [row for row in be_rows if _target(row.get("title"))]

    jobs = []
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    errors = 0
    detail_ok = 0

    rows_to_probe = candidates if candidates else be_rows[:1]

    cache = {}
    for row in rows_to_probe:
        path = clean(row.get("externalPath"))
        if not path:
            errors += 1
            continue

        try:
            rr = s.get(
                f"{host}/wday/cxs/{tenant}/{site}{path}",
                headers={"Referer": board.url},
                timeout=TIMEOUT,
            )
            if rr.status_code in {404, 410}:
                cache[path] = {"closed": True}
                continue
            rr.raise_for_status()
            cache[path] = {"payload": rr.json()}
            detail_ok += 1
        except Exception:
            errors += 1
            cache[path] = {"error": True}

    for row in candidates:
        path = clean(row.get("externalPath"))
        if not path:
            continue

        cached = cache.get(path)
        if cached is None:
            try:
                rr = s.get(
                    f"{host}/wday/cxs/{tenant}/{site}{path}",
                    headers={"Referer": board.url},
                    timeout=TIMEOUT,
                )
                if rr.status_code in {404, 410}:
                    closed += 1
                    continue
                rr.raise_for_status()
                cached = {"payload": rr.json()}
                detail_ok += 1
            except Exception:
                errors += 1
                continue

        if cached.get("error"):
            continue
        if cached.get("closed"):
            closed += 1
            continue

        payload = cached.get("payload") or {}
        info = payload.get("jobPostingInfo") or payload

        title = clean(info.get("title") or row.get("title"))
        location = clean(info.get("location") or info.get("locationText") or row.get("locationsText"))

        desc_html = (
            info.get("jobDescription")
            or info.get("description")
            or info.get("externalJobDescription")
            or ""
        )
        description = _html_text(desc_html)
        if len(description) < MIN_DESC:
            description = clean(json.dumps(info, ensure_ascii=False))

        if len(description) < MIN_DESC:
            errors += 1
            continue

        if not _is_be(location + " " + json.dumps(info, ensure_ascii=False)):
            rejected_geo += 1
            continue

        if dutch_hard(description):
            rejected_language += 1
            continue

        external_id = clean(
            info.get("jobReqId")
            or info.get("jobRequisitionId")
            or path.rsplit("/", 1)[-1]
        )

        jobs.append(_job(
            source, company, external_id, title, location,
            description,
            f"{host}/en-US/{site}{path}",
            info.get("postedOn") or info.get("startDate"),
        ))

    return _publish(
        source, len(be_rows), len(candidates), jobs,
        rejected_language=rejected_language,
        rejected_geo=rejected_geo,
        closed=closed,
        detail_errors=errors,
        diag={
            "site": site,
            "board_http": board.status_code,
            "cxs_http": 200,
            "announced_total": data.get("total"),
            "returned_rows": len(rows),
            "belgium_rows": len(be_rows),
            "geo_truth_count": len(be_rows),
            "detail_probe_ok": detail_ok,
            "engine": "CSL official Workday CXS limit=20",
        },
    )


# =============================================================================
# BOEHRINGER INGELHEIM - official public SuccessFactors job board
# =============================================================================

def collect_boehringer_jobs():
    source = "BOEHRINGER"
    company = "Boehringer Ingelheim Belgium"
    s = _session()

    links = {}
    pages_ok = 0

    for startrow in (0, 25, 50, 75):
        url = "https://jobs.boehringer-ingelheim.com/search/?q=&locationsearch=Belgium"
        if startrow:
            url += f"&startrow={startrow}"

        try:
            r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code != 200:
                break
        except Exception:
            break

        pages_ok += 1
        soup = BeautifulSoup(r.text, "html.parser")
        before = len(links)

        for a in soup.find_all("a", href=True):
            u = urljoin(r.url, a["href"]).split("#", 1)[0]
            m = re.search(r"/job/[^/?#]+/(\d+)/?$", u, re.I)
            if m:
                links[m.group(1)] = (u, clean(a.get_text(" ", strip=True)))

        if startrow and len(links) == before:
            break

    seen = len(links)
    candidates = 0
    jobs = []
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    errors = 0
    detail_ok = 0
    geo_truth = 0

    for jid, (url, listing_title) in sorted(links.items()):
        # Probe every Belgian result; search page is already Belgium-scoped.
        try:
            r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code in {404, 410}:
                closed += 1
                continue
            r.raise_for_status()
        except Exception:
            errors += 1
            continue

        detail_ok += 1
        soup = BeautifulSoup(r.text, "html.parser")
        text = clean(soup.get_text(" ", strip=True))
        h1 = soup.find("h1")
        title = clean(h1.get_text(" ", strip=True)) if h1 else listing_title

        is_be = _is_be(text[:3000])
        if is_be:
            geo_truth += 1

        if not _target(title):
            continue
        candidates += 1

        if not is_be:
            rejected_geo += 1
            continue

        if dutch_hard(text):
            rejected_language += 1
            continue

        if len(text) < MIN_DESC:
            errors += 1
            continue

        location = "Belgium"
        m = re.search(
            r"\b(Brussels(?: Capital Region)?|Belgium|Mechelen|Wavre)[^|]{0,80}\b",
            text[:2500],
            re.I,
        )
        if m:
            location = clean(m.group(0))

        jobs.append(_job(
            source, company, jid, title, location, text, r.url
        ))

    return _publish(
        source, seen, candidates, jobs,
        rejected_language=rejected_language,
        rejected_geo=rejected_geo,
        closed=closed,
        detail_errors=errors,
        diag={
            "pages_ok": pages_ok,
            "listing_links": seen,
            "detail_probe_ok": detail_ok,
            "geo_truth_count": geo_truth,
            "engine": "jobs.boehringer-ingelheim.com public job board",
        },
    )
