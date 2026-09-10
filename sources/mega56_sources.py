from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from database.models import JobOffer
from sources.batch4_engine import clean, dutch_hard, title_is_target, publish_metrics

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/152 Safari/537.36"
TIMEOUT = 30
MIN_DESCRIPTION = 250

EXTRA_TARGETS = [
    r"\bdata coordinator\b",
    r"\bdata governance\b",
    r"\bpower\s*bi\b",
    r"\bdata management\b",
    r"\bmaster data\b",
    r"\bqa release specialist\b",
]

MANAGEMENT = re.compile(
    r"\b(?:senior|principal|director|head|manager|management|team\s+leader|leader|lead|supervisor)\b",
    re.I,
)

_LAST_DIAG = {}


def _target(title):
    title = clean(title)
    if not title or MANAGEMENT.search(title):
        return False
    if title_is_target(title):
        return True
    return any(re.search(p, title, re.I) for p in EXTRA_TARGETS)


def _session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8",
    })
    return s


def _stable_id(source, url, title=""):
    raw = f"{source}|{clean(url).lower()}|{clean(title).lower()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def _jsonld_jobs(soup):
    out = []
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
            if any(str(x).lower() == "jobposting" for x in types if x):
                out.append(obj)
    return out


def _flatten_location(value):
    parts = []

    def walk(v):
        if isinstance(v, dict):
            for k in (
                "streetAddress",
                "addressLocality",
                "addressRegion",
                "postalCode",
                "addressCountry",
                "name",
            ):
                x = v.get(k)
                if isinstance(x, (str, int, float)) and clean(x):
                    parts.append(clean(x))
            for k in ("address", "jobLocation", "applicantLocationRequirements"):
                if k in v:
                    walk(v[k])
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(value)
    return " | ".join(dict.fromkeys(parts))


def _country_codes(value):
    codes = []

    def walk(v):
        if isinstance(v, dict):
            if "addressCountry" in v:
                x = v.get("addressCountry")
                if isinstance(x, dict):
                    x = x.get("name") or x.get("@id")
                if x:
                    codes.append(clean(x).upper())
            for x in v.values():
                if isinstance(x, (dict, list)):
                    walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(value)
    return codes


def _strict_belgium_from_jsonld(obj):
    if not isinstance(obj, dict):
        return False
    loc = obj.get("jobLocation") or obj.get("applicantLocationRequirements")
    codes = _country_codes(loc)
    return any(
        x in {"BE", "BELGIUM", "BELGIQUE", "BELGIË"}
        or x.endswith("/BE")
        for x in codes
    )


def _detail(url, listing_title=""):
    s = _session()
    r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
    if r.status_code in {404, 410}:
        return None, "closed"
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    page_text = clean(soup.get_text(" ", strip=True))

    obj = next(iter(_jsonld_jobs(soup)), None)
    title = clean((obj or {}).get("title") or (obj or {}).get("name") or listing_title)
    location = _flatten_location(
        (obj or {}).get("jobLocation")
        or (obj or {}).get("applicantLocationRequirements")
    )
    description_html = (obj or {}).get("description") or ""
    description = clean(
        BeautifulSoup(str(description_html), "html.parser").get_text(" ", strip=True)
    )
    if len(description) < MIN_DESCRIPTION:
        description = page_text

    if not title:
        h1 = soup.find("h1")
        if h1:
            title = clean(h1.get_text(" ", strip=True))

    return {
        "url": r.url,
        "title": title,
        "location": location,
        "description": description,
        "strict_belgium": _strict_belgium_from_jsonld(obj),
        "date_posted": clean((obj or {}).get("datePosted")),
    }, None


def _job(source, company, row):
    return JobOffer(
        source=source,
        external_id=clean(row.get("external_id")) or _stable_id(source, row["url"], row["title"]),
        title=clean(row["title"]),
        company=company,
        location=clean(row.get("location")) or "Belgium",
        description=clean(row["description"]),
        url=clean(row["url"]),
        date_published=clean(row.get("date_posted")) or None,
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
    print("=" * 88)
    print(source)
    print("=" * 88)
    for k, v in metrics.items():
        print(f"{k:<20}: {v}")
    for item in jobs:
        print("KEEP |", item.title, "|", item.location)

    return jobs


def get_mega56_diag(source):
    return dict(_LAST_DIAG.get(str(source).upper(), {}))


# ---------------------------------------------------------------------------
# MEDPACE
# ---------------------------------------------------------------------------

def collect_medpace_jobs():
    source = "MEDPACE"
    company = "Medpace"
    listing = "https://careers.medpace.com/jobs/locations/country/Belgium"

    s = _session()
    r = s.get(listing, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    links = {}
    for a in soup.find_all("a", href=True):
        u = urljoin(r.url, a["href"]).split("#", 1)[0]
        m = re.search(r"https?://careers\.medpace\.com/jobs/(\d+)(?:\?.*)?$", u, re.I)
        if m:
            links[m.group(1)] = (u, clean(a.get_text(" ", strip=True)))

    # Serialized links fallback.
    for m in re.finditer(r'https?://careers\.medpace\.com/jobs/(\d+)(?:\?[^"\'\s<>]*)?', r.text, re.I):
        jid = m.group(1)
        links.setdefault(jid, (f"https://careers.medpace.com/jobs/{jid}", ""))

    seen = len(links)
    candidates = 0
    jobs = []
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    errors = 0
    geo_truth = 0

    for jid, (u, listing_title) in sorted(links.items()):
        try:
            row, state = _detail(u, listing_title)
        except Exception:
            errors += 1
            continue

        if state == "closed":
            closed += 1
            continue
        if not row:
            errors += 1
            continue

        if row["strict_belgium"]:
            geo_truth += 1

        if not _target(row["title"]):
            continue
        candidates += 1

        if not row["strict_belgium"]:
            rejected_geo += 1
            continue
        if len(row["description"]) < MIN_DESCRIPTION:
            errors += 1
            continue
        if dutch_hard(row["description"]):
            rejected_language += 1
            continue

        row["external_id"] = jid
        jobs.append(_job(source, company, row))

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
        },
    )


# ---------------------------------------------------------------------------
# KEYRUS
# ---------------------------------------------------------------------------

def collect_keyrus_jobs():
    source = "KEYRUS"
    company = "Keyrus Belgium"
    listing = "https://jobs.keyrus.be/jobs"

    s = _session()
    r = s.get(listing, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    links = {}
    for a in soup.find_all("a", href=True):
        u = urljoin(r.url, a["href"]).split("#", 1)[0]
        m = re.search(r"/jobs/(\d+)-[^/?#]+$", u, re.I)
        if m:
            links[m.group(1)] = (u, clean(a.get_text(" ", strip=True)))

    seen = len(links)
    candidates = 0
    jobs = []
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    errors = 0
    geo_truth = 0

    for jid, (u, listing_title) in sorted(links.items()):
        try:
            row, state = _detail(u, listing_title)
        except Exception:
            errors += 1
            continue

        if state == "closed":
            closed += 1
            continue
        if not row:
            errors += 1
            continue

        if row["strict_belgium"]:
            geo_truth += 1

        if not _target(row["title"]):
            continue
        candidates += 1

        if not row["strict_belgium"]:
            rejected_geo += 1
            continue
        if dutch_hard(row["description"]):
            rejected_language += 1
            continue
        if len(row["description"]) < MIN_DESCRIPTION:
            errors += 1
            continue

        row["external_id"] = jid
        jobs.append(_job(source, company, row))

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
        },
    )


# ---------------------------------------------------------------------------
# POLYPEPTIDE BELGIUM ONLY
# ---------------------------------------------------------------------------

def collect_polypeptide_jobs():
    source = "POLYPEPTIDE"
    company = "PolyPeptide Belgium"
    listing = "https://careers.polypeptide.com/jobs?location_id=17481"

    s = _session()
    r = s.get(listing, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    links = {}
    for a in soup.find_all("a", href=True):
        u = urljoin(r.url, a["href"]).split("#", 1)[0]
        # Only the main Group career domain; explicitly exclude French/US/Swedish subdomains.
        if urljoin(r.url, a["href"]).lower().startswith("https://careers.polypeptide.com/jobs/"):
            m = re.search(r"/jobs/(\d+)-[^/?#]+$", u, re.I)
            if m:
                links[m.group(1)] = (u, clean(a.get_text(" ", strip=True)))

    seen = len(links)
    candidates = 0
    jobs = []
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    errors = 0
    geo_truth = 0

    for jid, (u, listing_title) in sorted(links.items()):
        try:
            row, state = _detail(u, listing_title)
        except Exception:
            errors += 1
            continue

        if state == "closed":
            closed += 1
            continue
        if not row:
            errors += 1
            continue

        # Braine-l'Alleud location is mandatory. A multi-location job is allowed if BE is included.
        is_braine = "braine" in row["location"].lower()
        if row["strict_belgium"] and is_braine:
            geo_truth += 1

        if not _target(row["title"]):
            continue
        candidates += 1

        if not (row["strict_belgium"] and is_braine):
            rejected_geo += 1
            continue
        if dutch_hard(row["description"]):
            rejected_language += 1
            continue

        row["external_id"] = jid
        jobs.append(_job(source, company, row))

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
            "strict_location": "Braine-l'Alleud",
        },
    )


# ---------------------------------------------------------------------------
# EXPLEO BELGIUM iCIMS
# ---------------------------------------------------------------------------

def collect_expleo_jobs():
    source = "EXPLEO"
    company = "Expleo Belgium"
    listing = "https://expleo-jobs-be-en.icims.com/jobs/search?ss=1"

    s = _session()
    links = {}

    for page in range(0, 5):
        url = listing + ("&pr=" + str(page) if page else "")
        r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        before = len(links)
        for a in soup.find_all("a", href=True):
            u = urljoin(r.url, a["href"]).split("#", 1)[0]
            m = re.search(
                r"https?://expleo-jobs-be-en\.icims\.com/jobs/(\d+)/[^/?#]+/job/?$",
                u,
                re.I,
            )
            if m:
                links[m.group(1)] = (u, clean(a.get_text(" ", strip=True)))

        # iCIMS may serialize detail hrefs.
        for m in re.finditer(
            r'https?://expleo-jobs-be-en\.icims\.com/jobs/(\d+)/[^"\'\s<>]+/job/?',
            r.text,
            re.I,
        ):
            jid = m.group(1)
            links.setdefault(jid, (m.group(0), ""))

        if page > 0 and len(links) == before:
            break

    seen = len(links)
    candidates = 0
    jobs = []
    rejected_language = 0
    closed = 0
    errors = 0
    geo_truth = 0

    for jid, (u, listing_title) in sorted(links.items()):
        try:
            row, state = _detail(u, listing_title)
        except Exception:
            errors += 1
            continue

        if state == "closed":
            closed += 1
            continue
        if not row:
            errors += 1
            continue

        # Tenant itself is Belgium-only; JSON-LD normally confirms it.
        if row["strict_belgium"]:
            geo_truth += 1

        if not _target(row["title"]):
            continue
        candidates += 1

        if dutch_hard(row["description"]):
            rejected_language += 1
            continue

        row["external_id"] = jid
        row["location"] = row["location"] or "Belgium"
        jobs.append(_job(source, company, row))

    return _publish(
        source, seen, candidates, jobs,
        rejected_language=rejected_language,
        closed=closed,
        detail_errors=errors,
        diag={
            "listing_links": seen,
            "geo_truth_count": geo_truth,
            "trusted_tenant": "expleo-jobs-be-en.icims.com",
        },
    )


# ---------------------------------------------------------------------------
# DIRECT WORKDAY CXS
# ---------------------------------------------------------------------------

def _collect_workday(source, company, host, tenant, site, public_path):
    s = _session()
    endpoint = f"{host}/wday/cxs/{tenant}/{site}/jobs"

    r = s.post(
        endpoint,
        json={
            "appliedFacets": {},
            "limit": 50,
            "offset": 0,
            "searchText": "Belgium",
        },
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Referer": f"{host}/{public_path}",
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    data = r.json()
    rows = data.get("jobPostings") or []

    be_rows = []
    for row in rows:
        loc = clean(row.get("locationsText"))
        raw = json.dumps(row, ensure_ascii=False)
        if re.search(r"\bBelgium\b", loc + " " + raw, re.I):
            be_rows.append(row)

    candidates = [row for row in be_rows if _target(row.get("title"))]
    jobs = []
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    errors = 0
    geo_truth = len(be_rows)

    for row in candidates:
        path = clean(row.get("externalPath"))
        if not path:
            errors += 1
            continue

        detail_url = f"{host}/wday/cxs/{tenant}/{site}{path}"
        try:
            rr = s.get(
                detail_url,
                headers={"Referer": f"{host}/{public_path}"},
                timeout=TIMEOUT,
            )
            if rr.status_code in {404, 410}:
                closed += 1
                continue
            rr.raise_for_status()
            payload = rr.json()
        except Exception:
            errors += 1
            continue

        info = payload.get("jobPostingInfo") or payload
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
        description = clean(
            BeautifulSoup(str(raw_desc), "html.parser").get_text(" ", strip=True)
        )

        if len(description) < MIN_DESCRIPTION:
            # Last-resort flattening of public JSON.
            description = clean(json.dumps(info, ensure_ascii=False))

        if len(description) < MIN_DESCRIPTION:
            errors += 1
            continue

        if not re.search(r"\bBelgium\b", location + " " + json.dumps(info, ensure_ascii=False), re.I):
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

        public_url = f"{host}/{public_path}{path}"

        jobs.append(
            JobOffer(
                source=source,
                external_id=ext_id,
                title=title,
                company=company,
                location=location or "Belgium",
                description=description,
                url=public_url,
                date_published=clean(info.get("postedOn") or info.get("startDate")) or None,
                contract_type=None,
                language=None,
            )
        )

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
            "board_total": data.get("total"),
            "belgium_rows": len(be_rows),
            "geo_truth_count": geo_truth,
            "tenant": tenant,
            "site": site,
        },
    )


def collect_univercells_tech_jobs():
    return _collect_workday(
        "UNIVERCELLS_TECH",
        "Donaldson / Univercells Technologies",
        "https://donaldson.wd115.myworkdayjobs.com",
        "donaldson",
        "DonaldsonCareers",
        "en-US/DonaldsonCareers",
    )


def collect_lhoist_jobs():
    return _collect_workday(
        "LHOIST",
        "Lhoist",
        "https://lhoist.wd3.myworkdayjobs.com",
        "lhoist",
        "Careers",
        "Careers",
    )
