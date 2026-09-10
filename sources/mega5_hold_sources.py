from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

from database.models import JobOffer
from sources.batch4_engine import clean, dutch_hard, title_is_target, publish_metrics

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/152 Safari/537.36"
TIMEOUT = 30
MIN_DESCRIPTION = 250

MANAGEMENT_BLOCK = re.compile(
    r"\b(?:senior|principal|director|head|manager|management|team\s+leader|leader|lead|supervisor)\b",
    re.I,
)

EXTRA_TARGETS = (
    re.compile(r"\bdata coordinator\b", re.I),
    re.compile(r"\bdata consultant\b", re.I),
    re.compile(r"\banalytics consultant\b", re.I),
    re.compile(r"\bdata insights consultant\b", re.I),
    re.compile(r"\bfunctional analyst\b", re.I),
    re.compile(r"\bqa release specialist\b", re.I),
)

_LAST_DIAG = {}


def _target(title):
    title = clean(title)
    if not title or MANAGEMENT_BLOCK.search(title):
        return False
    return title_is_target(title) or any(p.search(title) for p in EXTRA_TARGETS)


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


def _job(source, company, row):
    return JobOffer(
        source=source,
        external_id=clean(row.get("external_id")) or _stable_id(source, row["url"], row["title"]),
        title=clean(row["title"]),
        company=company,
        location=clean(row.get("location")) or "Belgium",
        description=clean(row.get("description")),
        url=clean(row.get("url")),
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


def get_hold_diag(source):
    return dict(_LAST_DIAG.get(str(source).upper(), {}))


def _text_detail(url):
    s = _session()
    r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
    if r.status_code in {404, 410}:
        return None, "closed"

    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    text = clean(soup.get_text(" ", strip=True))

    h1 = soup.find("h1")
    title = clean(h1.get_text(" ", strip=True)) if h1 else ""

    return {
        "url": r.url,
        "title": title,
        "description": text,
        "html": r.text,
        "soup": soup,
    }, None


def _extract_location_text(text):
    # Strict localities/country; do not accept generic footer occurrences.
    patterns = [
        r"(?:Location|Lieu|Localisation)\s*[:\-]?\s*([A-Za-zÀ-ÿ0-9 ,.'’()/\-]{2,140}(?:Belgium|Belgique|België))",
        r"([A-Za-zÀ-ÿ0-9 ,.'’()/\-]{2,120},\s*(?:Belgium|Belgique|België))",
        r"(Leuven,\s*Belgium)",
        r"(Ottignies-Louvain-la-Neuve,\s*(?:Belgium|Belgique))",
        r"(Grand-Rosière[^,]*,\s*(?:Belgium|Belgique))",
        r"(Machelen,\s*Belgium)",
        r"(Mechelen,\s*Belgium)",
        r"(Brussels,\s*Belgium)",
        r"(Bruxelles,\s*Belgique)",
        r"(Tubize,\s*Belgium)",
        r"(Charleroi,\s*Belgium)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return clean(m.group(1))
    return ""


def _extract_jobposting(soup):
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
    return None


def _jsonld_location(obj):
    if not isinstance(obj, dict):
        return ""
    loc = obj.get("jobLocation") or obj.get("applicantLocationRequirements")
    parts = []

    def walk(v):
        if isinstance(v, dict):
            for k in ("addressLocality", "addressRegion", "addressCountry", "streetAddress", "name"):
                x = v.get(k)
                if isinstance(x, str) and clean(x):
                    parts.append(clean(x))
            if "address" in v:
                walk(v["address"])
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(loc)
    return " | ".join(dict.fromkeys(parts))


def collect_odoo_hold_jobs():
    source = "ODOO"
    company = "Odoo"
    listing = "https://www.odoo.com/fr_FR/jobs?country_id=20"

    s = _session()
    r = s.get(listing, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    links = {}
    for a in soup.find_all("a", href=True):
        u = urljoin(r.url, a["href"]).split("#", 1)[0]
        if re.search(r"/(?:fr_FR|en_US)/jobs/[^/?#]+-\d+$", u, re.I):
            links[u] = clean(a.get_text(" ", strip=True))

    jobs = []
    cand = 0
    rejected_geo = 0
    rejected_language = 0
    errors = 0

    for u, listing_title in links.items():
        if not _target(listing_title):
            continue
        cand += 1
        try:
            detail, state = _text_detail(u)
        except Exception:
            errors += 1
            continue
        if not detail:
            continue

        obj = _extract_jobposting(detail["soup"])
        title = clean((obj or {}).get("title")) or detail["title"] or listing_title
        location = _jsonld_location(obj) or _extract_location_text(detail["description"])

        # Odoo application summary is a reliable fallback when the main page omits structured location.
        if not location:
            apply_url = u.replace("/jobs/", "/jobs/apply/", 1)
            try:
                app, _ = _text_detail(apply_url)
                if app:
                    location = _extract_location_text(app["description"])
            except Exception:
                pass

        if not re.search(r"\b(?:Belgium|Belgique|België)\b", location, re.I):
            rejected_geo += 1
            continue

        if dutch_hard(detail["description"]):
            rejected_language += 1
            continue

        row = {
            "title": title,
            "location": location,
            "description": detail["description"],
            "url": detail["url"],
        }
        jobs.append(_job(source, company, row))

    return _publish(
        source, len(links), cand, jobs,
        rejected_language=rejected_language,
        rejected_geo=rejected_geo,
        detail_errors=errors,
        diag={"listing_http": r.status_code, "listing_links": len(links), "geo_truth_count": len(jobs)},
    )


def _icims_search(source, company, listing_url, location_prefixes=()):
    s = _session()
    links = {}

    for page in range(0, 4):
        url = listing_url + ("&pr=" + str(page) if "?" in listing_url else "?pr=" + str(page))
        r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code != 200:
            if page == 0:
                r.raise_for_status()
            break
        soup = BeautifulSoup(r.text, "html.parser")

        for a in soup.find_all("a", href=True):
            href = clean(a.get("href"))
            u = urljoin(r.url, href).split("#", 1)[0]
            if re.search(r"/jobs/\d+/[^/?#]+/(?:job|overview)?/?$", u, re.I):
                title = clean(a.get_text(" ", strip=True))
                links[u] = title

        # standard iCIMS often exposes job links without absolute scheme
        for m in re.finditer(r'href=["\']([^"\']*/jobs/\d+/[^"\']+)["\']', r.text, re.I):
            u = urljoin(r.url, m.group(1)).split("#", 1)[0]
            links.setdefault(u, "")

        if "Search results page" in clean(soup.get_text(" ", strip=True)):
            # Continue through a few pages; otherwise first page is enough.
            pass
        elif page > 0:
            break

    jobs = []
    cand = 0
    rejected_geo = 0
    rejected_language = 0
    closed = 0
    errors = 0
    geo_truth = 0

    for u, listing_title in links.items():
        try:
            detail, state = _text_detail(u)
        except Exception:
            errors += 1
            continue
        if state == "closed":
            closed += 1
            continue
        if not detail:
            continue

        title = detail["title"] or listing_title
        text = detail["description"]
        location = _extract_location_text(text)
        if location:
            geo_truth += 1

        if not _target(title):
            continue

        cand += 1

        if not location or not re.search(r"\b(?:Belgium|Belgique|België)\b", location, re.I):
            # iCIMS Belgium tenant itself can be trusted for Expleo only.
            if source == "EXPLEO" and "expleo-jobs-be-en.icims.com" in urlparse(u).netloc.lower():
                location = location or "Belgium"
                geo_truth += 1
            else:
                rejected_geo += 1
                continue

        if dutch_hard(text):
            rejected_language += 1
            continue

        jobs.append(_job(source, company, {
            "title": title,
            "location": location,
            "description": text,
            "url": detail["url"],
        }))

    return _publish(
        source, len(links), cand, jobs,
        rejected_language=rejected_language,
        rejected_geo=rejected_geo,
        closed=closed,
        detail_errors=errors,
        diag={"listing_links": len(links), "geo_truth_count": geo_truth},
    )


def collect_expleo_jobs():
    return _icims_search(
        "EXPLEO",
        "Expleo Belgium",
        "https://expleo-jobs-be-en.icims.com/jobs/search?ss=1",
    )


def collect_medpace_jobs():
    return _icims_search(
        "MEDPACE",
        "Medpace",
        "https://international-medpace.icims.com/jobs/search?ss=1",
    )


def collect_delaware_jobs():
    source = "DELAWARE"
    company = "delaware Belgium"
    listing = "https://www.delaware.pro/en-be/careers/jobs"

    s = _session()
    r = s.get(listing, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    links = {}
    for a in soup.find_all("a", href=True):
        u = urljoin(r.url, a["href"]).split("#", 1)[0]
        if re.search(r"/en-be/careers/jobs/[^/?#]+$", u, re.I):
            links[u] = clean(a.get_text(" ", strip=True))

    jobs = []
    cand = 0
    rejected_language = 0
    rejected_geo = 0
    errors = 0

    for u, listing_title in links.items():
        try:
            detail, state = _text_detail(u)
        except Exception:
            errors += 1
            continue
        if not detail:
            continue

        title = detail["title"] or listing_title
        if not _target(title):
            continue
        cand += 1

        text = detail["description"]
        # Site is explicitly Belgium-scoped; still require explicit Belgium in job content.
        location = _extract_location_text(text)
        if not location and re.search(r"\bBelgium\b", text, re.I):
            location = "Belgium"

        if not location:
            rejected_geo += 1
            continue

        if dutch_hard(text):
            rejected_language += 1
            continue

        jobs.append(_job(source, company, {
            "title": title,
            "location": location,
            "description": text,
            "url": detail["url"],
        }))

    return _publish(
        source, len(links), cand, jobs,
        rejected_language=rejected_language,
        rejected_geo=rejected_geo,
        detail_errors=errors,
        diag={"listing_http": r.status_code, "listing_links": len(links), "geo_truth_count": len(jobs)},
    )


def collect_parexel_hold_jobs():
    source = "PAREXEL"
    company = "Parexel"
    listing = "https://jobs.parexel.com/en/location/belgium-jobs/877/2802361/2/search-jobs"

    s = _session()
    r = s.get(listing, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    links = {}
    for a in soup.find_all("a", href=True):
        u = urljoin(r.url, a["href"]).split("#", 1)[0]
        if re.search(r"/en/job/[^/?#]+/\d+/\d+$", u, re.I):
            links[u] = clean(a.get_text(" ", strip=True))

    jobs = []
    cand = 0
    errors = 0
    rejected_language = 0

    for u, listing_title in links.items():
        if not _target(listing_title):
            continue
        cand += 1
        try:
            detail, _ = _text_detail(u)
        except Exception:
            errors += 1
            continue
        if not detail:
            continue
        if dutch_hard(detail["description"]):
            rejected_language += 1
            continue
        jobs.append(_job(source, company, {
            "title": detail["title"] or listing_title,
            "location": _extract_location_text(detail["description"]) or "Belgium",
            "description": detail["description"],
            "url": detail["url"],
        }))

    return _publish(
        source, len(links), cand, jobs,
        rejected_language=rejected_language,
        detail_errors=errors,
        diag={"listing_http": r.status_code, "listing_links": len(links), "geo_truth_count": len(links)},
    )


def collect_sonaca_hold_jobs():
    source = "SONACA"
    company = "Sonaca"
    listing = "https://lde.tbe.taleo.net/lde01/ats/careers/v2/searchResults?org=SONACA&cws=38"

    s = _session()
    r = s.get(listing, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    rows = []
    seen_rids = set()

    for a in soup.find_all("a", href=True):
        href = clean(a["href"])
        m = re.search(r"\brid=(\d+)", href)
        if not m or "viewRequisition" not in href:
            continue
        rid = m.group(1)
        if rid in seen_rids:
            continue
        seen_rids.add(rid)

        container = a
        for _ in range(5):
            if container.parent:
                container = container.parent
        context = clean(container.get_text(" | ", strip=True))
        rows.append((rid, urljoin(r.url, href), context))

    jobs = []
    cand = 0
    rejected_geo = 0
    rejected_language = 0
    errors = 0

    for rid, u, context in rows:
        try:
            detail, _ = _text_detail(u)
        except Exception:
            errors += 1
            continue
        if not detail:
            continue

        text = detail["description"]
        title = ""

        # Prefer a substantive title from listing context.
        for part in [clean(x) for x in context.split("|")]:
            if not part or part.lower() in {"afficher", "postuler", "view", "apply"}:
                continue
            if len(part) > 180:
                continue
            if re.search(r"[A-Za-zÀ-ÿ]{3}", part):
                title = part
                break

        if not title or title.lower() in {"afficher", "postuler"}:
            title = detail["title"]

        if not _target(title):
            continue
        cand += 1

        location = _extract_location_text(text)
        # Sonaca's cws=38 is the Belgium career centre; still require a Belgian keyword.
        if not location:
            if re.search(r"\b(?:Belgique|Belgium|Gosselies|Charleroi|Liège|Liege|Bruxelles|Brussels)\b", text, re.I):
                location = "Belgium"
            else:
                rejected_geo += 1
                continue

        if dutch_hard(text):
            rejected_language += 1
            continue

        jobs.append(_job(source, company, {
            "external_id": rid,
            "title": title,
            "location": location,
            "description": text,
            "url": detail["url"],
        }))

    return _publish(
        source, len(rows), cand, jobs,
        rejected_language=rejected_language,
        rejected_geo=rejected_geo,
        detail_errors=errors,
        diag={"listing_http": r.status_code, "listing_rows": len(rows), "geo_truth_count": len(jobs)},
    )


def _discovery_only(source, url):
    s = _session()
    r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    links = []
    for a in soup.find_all("a", href=True):
        u = urljoin(r.url, a["href"]).split("#", 1)[0]
        text = clean(a.get_text(" ", strip=True))
        if any(x in (u + " " + text).lower() for x in ("job", "career", "vacan", "offre", "position")):
            links.append((u, text))

    _LAST_DIAG[source] = {
        "listing_http": r.status_code,
        "candidate_links": len(links),
        "sample_links": links[:30],
        "metrics": {
            "seen": 0, "candidates": 0, "kept": 0, "non_target": 0,
            "rejected_language": 0, "rejected_geo": 0, "closed": 0, "detail_errors": 0,
        },
    }
    publish_metrics(source, _LAST_DIAG[source]["metrics"])
    return []


def collect_oncodna_hold_jobs():
    return _discovery_only("ONCODNA", "https://oncodna.com/careers/")


def collect_agap2_hold_jobs():
    return _discovery_only("AGAP2", "https://agap2.com/belgium/en/career/")


def collect_capgemini_eng_hold_jobs():
    return _discovery_only(
        "CAPGEMINI_ENG",
        "https://www.capgemini.com/be-en/careers/join-capgemini/job-search/",
    )
