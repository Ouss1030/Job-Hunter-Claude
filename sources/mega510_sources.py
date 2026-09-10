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
MIN_DESC = 220

_LAST_DIAG = {}

BLOCK_TITLE = re.compile(
    r"\b(?:senior|sr\.?|principal|staff|director|head|manager|management|"
    r"team\s+leader|leader|lead|supervisor|intern(?:ship)?|stage|trainee|"
    r"apprentice|alternance|phd)\b",
    re.I,
)

EXTRA_TARGETS = (
    re.compile(r"\bquality assurance\b", re.I),
    re.compile(r"\bquality control\b", re.I),
    re.compile(r"\bvalidation\b", re.I),
    re.compile(r"\bqualification\b", re.I),
    re.compile(r"\bcsv\b", re.I),
    re.compile(r"\bfunctional analyst\b", re.I),
    re.compile(r"\bdata management\b", re.I),
    re.compile(r"\bdata quality\b", re.I),
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


def _stable_id(source, url, title=""):
    raw = f"{source}|{clean(url).lower()}|{clean(title).lower()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def _jsonld_job(soup):
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
                return obj
    return {}


def _flatten_location(value):
    parts = []
    countries = []

    def walk(v):
        if isinstance(v, dict):
            for k in ("streetAddress", "addressLocality", "addressRegion", "postalCode"):
                x = v.get(k)
                if isinstance(x, (str, int, float)) and clean(x):
                    parts.append(clean(x))
            country = v.get("addressCountry")
            if isinstance(country, dict):
                country = country.get("name") or country.get("@id")
            if country:
                country = clean(country)
                countries.append(country.upper())
                parts.append(country)
            for k in ("address", "jobLocation", "applicantLocationRequirements"):
                if k in v:
                    walk(v[k])
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(value)
    return " | ".join(dict.fromkeys(parts)), countries


def _html_text(value):
    return clean(BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True))


def _detail(url, listing_title="", source=""):
    s = _session()
    r = s.get(url, timeout=TIMEOUT, allow_redirects=True)

    if r.status_code in {404, 410}:
        return None, "closed"
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    text = clean(soup.get_text(" ", strip=True))
    obj = _jsonld_job(soup)

    title = clean(obj.get("title") or obj.get("name") or listing_title)
    if not title:
        h1 = soup.find("h1")
        if h1:
            title = clean(h1.get_text(" ", strip=True))

    location, countries = _flatten_location(
        obj.get("jobLocation") or obj.get("applicantLocationRequirements")
    )

    desc = _html_text(obj.get("description"))
    if len(desc) < MIN_DESC:
        desc = text

    date_posted = clean(obj.get("datePosted"))

    # Site-specific location fallbacks.
    if source == "ALTEN":
        m = re.search(
            r"Job info\s+.*?\b(Belgium|Belgique)\b\s+([A-Za-zÀ-ÿ \-']{2,80})",
            text,
            re.I,
        )
        if m:
            location = clean(m.group(1) + " " + m.group(2))
        elif re.search(r"\bBelgium\s+Wallonia\b|\bBelgique\s+Wallon", text, re.I):
            location = "Belgium Wallonia"

    if source == "JOHN_COCKERILL" and not location:
        m = re.search(r"\bLieu:\s*([^|]{2,120})", text, re.I)
        if m:
            location = clean(m.group(1))

    be = (
        any(x in {"BE", "BELGIUM", "BELGIQUE", "BELGIË"} or x.endswith("/BE") for x in countries)
        or bool(re.search(r"\b(?:Belgium|Belgique|België|BE - Belgique|BE - Belgium)\b", location, re.I))
    )

    return {
        "url": r.url,
        "title": title,
        "location": location,
        "description": desc,
        "date_posted": date_posted,
        "belgium": be,
        "text": text,
    }, None


def _job(source, company, external_id, row):
    return JobOffer(
        source=source,
        external_id=clean(external_id) or _stable_id(source, row["url"], row["title"]),
        title=clean(row["title"]),
        company=company,
        location=clean(row.get("location")) or "Belgium",
        description=clean(row["description"]),
        url=clean(row["url"]),
        date_published=clean(row.get("date_posted")) or None,
        contract_type=None,
        language=None,
    )


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
    print("=" * 90)
    print(source)
    print("=" * 90)
    for k, v in metrics.items():
        print(f"{k:<22}: {v}")
    for job in jobs:
        print("KEEP |", job.title, "|", job.location)

    return jobs


def get_mega510_diag(source):
    return dict(_LAST_DIAG.get(str(source).upper(), {}))


# =============================================================================
# ALTEN BELGIUM
# =============================================================================

ALTEN_LIVE_SEEDS = {
    "1495": "https://www.alten.be/jobs/1495-quality-assurance-engineer-life-sciences-wallonia/",
    "1441": "https://www.alten.be/jobs/1441-qualification-validation-coordinator-life-sciences-wallonia/",
    "1438": "https://www.alten.be/jobs/1438-csv-engineer-life-sciences-wallonia/",
    "1836": "https://www.alten.be/jobs/1836-automation-engineer-life-sciences-wallonia/",
}


def collect_alten_jobs():
    source = "ALTEN"
    company = "ALTEN Belgium"

    s = _session()
    listing_candidates = [
        "https://www.alten.be/your-career/",
        "https://www.alten.be/career/jobs/",
        "https://www.alten.be/fr/carriere/jobs/",
    ]

    links = {}
    listing_status = []

    for page in listing_candidates:
        try:
            r = s.get(page, timeout=TIMEOUT, allow_redirects=True)
            listing_status.append((r.url, r.status_code))
            if r.status_code != 200:
                continue

            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                u = urljoin(r.url, a["href"]).split("#", 1)[0]
                m = re.search(r"/jobs/(\d+)-[^/?#]+/?$", u, re.I)
                if m:
                    links[m.group(1)] = (u, clean(a.get_text(" ", strip=True)))

            for m in re.finditer(
                r'https?://www\.alten\.be/jobs/(\d+)-[^"\'\s<>]+/?',
                r.text,
                re.I,
            ):
                jid = m.group(1)
                links.setdefault(jid, (m.group(0), ""))
        except Exception:
            continue

    dynamic_count = len(links)
    seed_used = False

    if not links:
        seed_used = True
        for jid, url in ALTEN_LIVE_SEEDS.items():
            links[jid] = (url, "")

    seen = len(links)
    candidates = 0
    jobs = []
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    errors = 0
    detail_ok = 0
    geo_truth = 0

    for jid, (u, listing_title) in sorted(links.items()):
        try:
            row, state = _detail(u, listing_title, source=source)
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

        jobs.append(_job(source, company, jid, row))

    return _publish(
        source,
        seen,
        candidates,
        jobs,
        rejected_language=rejected_language,
        rejected_geo=rejected_geo,
        closed=closed,
        detail_errors=errors,
        diag={
            "listing_status": listing_status,
            "dynamic_links": dynamic_count,
            "seed_fallback_used": seed_used,
            "seed_ids": sorted(ALTEN_LIVE_SEEDS),
            "detail_probe_ok": detail_ok,
            "geo_truth_count": geo_truth,
        },
    )


# =============================================================================
# PAREXEL
# =============================================================================

PAREXEL_LIVE_SEED = (
    "88551839856",
    "https://jobs.parexel.com/en/job/united-kingdom/"
    "consultant-advanced-analytics-meta-analysis-hta-statistician/877/88551839856",
)


def collect_parexel_jobs():
    source = "PAREXEL"
    company = "Parexel"
    listing = "https://jobs.parexel.com/en/location/belgium-jobs/877/2802361/2/search-jobs"

    s = _session()
    r = s.get(listing, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()

    links = {}
    raw = r.text or ""
    soup = BeautifulSoup(raw, "html.parser")

    for a in soup.find_all("a", href=True):
        u = urljoin(r.url, a["href"]).split("#", 1)[0]
        m = re.search(r"/en/job/[^/?#]+/\d+/(\d+)$", u, re.I)
        if m:
            links[m.group(1)] = (u, clean(a.get_text(" ", strip=True)))

    for m in re.finditer(
        r'(?:"|\')((?:https?://jobs\.parexel\.com)?/en/job/[^"\']+?/\d+/(\d+))(?:"|\')',
        raw,
        re.I,
    ):
        u = urljoin(r.url, m.group(1))
        links.setdefault(m.group(2), (u, ""))

    seed_used = False
    if not links:
        seed_used = True
        jid, u = PAREXEL_LIVE_SEED
        links[jid] = (u, "")

    seen = len(links)
    candidates = 0
    jobs = []
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    errors = 0
    detail_ok = 0
    geo_truth = 0

    for jid, (u, listing_title) in sorted(links.items()):
        try:
            row, state = _detail(u, listing_title, source=source)
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

        # Multi-location job: JSON-LD or page text must explicitly contain Belgium.
        is_be = row["belgium"] or bool(
            re.search(r'\bBelgium\b', row["location"] + " " + row["text"][:5000], re.I)
        )
        if is_be:
            geo_truth += 1

        if not _target(row["title"]):
            continue
        candidates += 1

        if not is_be:
            rejected_geo += 1
            continue

        if dutch_hard(row["description"]):
            rejected_language += 1
            continue

        jobs.append(_job(source, company, jid, row))

    return _publish(
        source,
        seen,
        candidates,
        jobs,
        rejected_language=rejected_language,
        rejected_geo=rejected_geo,
        closed=closed,
        detail_errors=errors,
        diag={
            "listing_http": r.status_code,
            "listing_links": len(links),
            "seed_fallback_used": seed_used,
            "detail_probe_ok": detail_ok,
            "geo_truth_count": geo_truth,
        },
    )


# =============================================================================
# POLYPEPTIDE - Teamtailor, Belgium only
# =============================================================================

def collect_polypeptide_jobs():
    source = "POLYPEPTIDE"
    company = "PolyPeptide Belgium"

    pages = [
        "https://careers.polypeptide.com/locations/braine-l-alleud",
        "https://careers.polypeptide.com/jobs",
        "https://polypeptidebelgium.teamtailor.com/jobs",
    ]

    s = _session()
    links = {}
    page_status = []

    for page in pages:
        try:
            r = s.get(page, timeout=TIMEOUT, allow_redirects=True)
            page_status.append((r.url, r.status_code))
            if r.status_code != 200:
                continue

            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                u = urljoin(r.url, a["href"]).split("#", 1)[0]
                m = re.search(r"/jobs/(\d+)-[^/?#]+$", u, re.I)
                if m:
                    links[m.group(1)] = (u, clean(a.get_text(" ", strip=True)))

            for m in re.finditer(
                r'(?:"|\')((?:https?://[^"\']+)?/jobs/(\d+)-[^"\']+)(?:"|\')',
                r.text,
                re.I,
            ):
                u = urljoin(r.url, m.group(1))
                links.setdefault(m.group(2), (u, ""))
        except Exception:
            continue

    seen = len(links)
    candidates = 0
    jobs = []
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    errors = 0
    detail_ok = 0
    geo_truth = 0

    for jid, (u, listing_title) in sorted(links.items()):
        try:
            row, state = _detail(u, listing_title, source=source)
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

        strict_be = bool(
            re.search(r"\b(?:BE|Belgium|Belgique|België)\b", row["location"], re.I)
            and re.search(r"Braine", row["location"] + " " + row["text"][:1800], re.I)
        )

        if strict_be:
            geo_truth += 1

        if not _target(row["title"]):
            continue
        candidates += 1

        if not strict_be:
            rejected_geo += 1
            continue

        if dutch_hard(row["description"]):
            rejected_language += 1
            continue

        jobs.append(_job(source, company, jid, row))

    return _publish(
        source,
        seen,
        candidates,
        jobs,
        rejected_language=rejected_language,
        rejected_geo=rejected_geo,
        closed=closed,
        detail_errors=errors,
        diag={
            "page_status": page_status,
            "listing_links": seen,
            "detail_probe_ok": detail_ok,
            "geo_truth_count": geo_truth,
            "strict_location": "Braine-l'Alleud, Belgium",
        },
    )


# =============================================================================
# JOHN COCKERILL - direct SuccessFactors public table
# =============================================================================

def collect_john_cockerill_jobs():
    source = "JOHN_COCKERILL"
    company = "John Cockerill"
    base = "https://careers.johncockerill.com/go/All/8775301/"

    s = _session()
    links = {}
    pages_ok = 0

    for startrow in (0, 50, 100, 150, 200):
        url = base + (
            "?q=&sortColumn=sort_location&sortDirection=desc"
            + (f"&startrow={startrow}" if startrow else "")
        )

        try:
            r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
        except Exception:
            break

        if r.status_code != 200:
            break

        pages_ok += 1
        soup = BeautifulSoup(r.text, "html.parser")
        before = len(links)

        for a in soup.find_all("a", href=True):
            u = urljoin(r.url, a["href"]).split("#", 1)[0]
            m = re.search(r"/job/[^/?#]+/(\d+)/?$", u, re.I)
            if not m:
                continue

            title = clean(a.get_text(" ", strip=True))
            context = ""
            tr = a.find_parent("tr")
            if tr:
                context = clean(tr.get_text(" | ", strip=True))
            else:
                parent = a.parent
                if parent:
                    context = clean(parent.get_text(" | ", strip=True))

            links[m.group(1)] = (u, title, context)

        if startrow and len(links) == before:
            break

    seen_be = 0
    candidates = 0
    jobs = []
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    errors = 0
    detail_ok = 0
    geo_truth = 0

    for jid, (u, listing_title, context) in sorted(links.items()):
        context_be = bool(
            re.search(r"\bBE\s*-\s*(?:Belgium|Belgique)\b|\bSeraing\b|\bNamur\b|\bLi[eè]ge\b", context, re.I)
        )
        if not context_be:
            continue

        seen_be += 1

        # Probe at least one Belgium detail even when there is no target.
        must_probe = _target(listing_title) or detail_ok == 0
        if not must_probe:
            continue

        try:
            row, state = _detail(u, listing_title, source=source)
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

        is_be = context_be or row["belgium"]
        if is_be:
            geo_truth += 1

        if not _target(row["title"]):
            continue
        candidates += 1

        # Description seniority guard. Example current SAP role says Senior + 8 years.
        if re.search(
            r"\bminimum\s+[6-9]\+?\s+years?\b|\bminimum\s+(?:six|seven|eight|nine)\s+years?\b|"
            r"\b(?:senior|referent)\s+(?:role|mindset|functional analyst)\b",
            row["description"],
            re.I,
        ):
            continue

        if not is_be:
            rejected_geo += 1
            continue

        if dutch_hard(row["description"]):
            rejected_language += 1
            continue

        jobs.append(_job(source, company, jid, row))

    return _publish(
        source,
        seen_be,
        candidates,
        jobs,
        rejected_language=rejected_language,
        rejected_geo=rejected_geo,
        closed=closed,
        detail_errors=errors,
        diag={
            "pages_ok": pages_ok,
            "all_job_links": len(links),
            "belgium_rows": seen_be,
            "detail_probe_ok": detail_ok,
            "geo_truth_count": geo_truth,
            "engine": "direct SuccessFactors public HTML table",
        },
    )
