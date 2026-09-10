from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

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

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/152 Safari/537.36"
TIMEOUT = 30
MIN_DESCRIPTION = 250

# Extra titles that are relevant but may be absent from older central patterns.
EXTRA_TARGETS = (
    re.compile(r"\bdata insights consultant\b", re.I),
    re.compile(r"\bbioprocess technician\b", re.I),
    re.compile(r"\bqa release specialist\b", re.I),
)

BELGIUM_TOKENS = (
    "belgium", "belgique", "belgië", "brussels", "bruxelles",
    "machelen", "mechelen", "leuven", "nivelles", "wavre",
    "charleroi", "gosselies", "fleurus", "liège", "liege",
    "herstal", "namur", "louvain-la-neuve", "ottignies",
    "grand-rosière", "grand rosiere", "ramillies", "antwerp",
    "antwerpen", "gent", "ghent",
)

_LAST_DIAG = {}


def _is_target(title):
    # MEGA5_MANAGEMENT_GUARD_V1
    title = clean(title)
    if re.search(r"\b(?:manager|management|team\s+leader|leader|lead|supervisor|director|head|principal|senior)\b", title, re.I):
        return False
    return title_is_target(title) or any(p.search(title) for p in EXTRA_TARGETS)


def _session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8",
    })
    return s


def _is_belgium_text(value):
    low = clean(value).lower()
    return any(token in low for token in BELGIUM_TOKENS)


def _stable_id(source, url, title=""):
    raw = f"{source}|{clean(url).lower()}|{clean(title).lower()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def _jsonld_objects(soup):
    out = []

    for script in soup.find_all("script", type=lambda x: x and "ld+json" in x.lower()):
        raw = script.string or script.get_text() or ""
        try:
            data = json.loads(raw)
        except Exception:
            continue

        stack = data if isinstance(data, list) else [data]

        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                out.append(value)
                graph = value.get("@graph")
                if isinstance(graph, list):
                    stack.extend(graph)
            elif isinstance(value, list):
                stack.extend(value)

    return out


def _flatten_location(value):
    parts = []

    def walk(v):
        if isinstance(v, dict):
            for key in (
                "addressLocality", "addressRegion", "addressCountry",
                "streetAddress", "name",
            ):
                x = v.get(key)
                if isinstance(x, (str, int, float)):
                    parts.append(clean(x))
            for key in ("address", "jobLocation", "applicantLocationRequirements"):
                if key in v:
                    walk(v.get(key))
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, (str, int, float)):
            parts.append(clean(v))

    walk(value)
    return " | ".join(dict.fromkeys(x for x in parts if x))


def _extract_detail(url, listing_title="", source="", trust_url_belgium=False):
    s = _session()
    r = s.get(url, timeout=TIMEOUT, allow_redirects=True)

    if r.status_code in {404, 410}:
        return {"closed": True, "http": r.status_code, "url": r.url}

    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    text = clean(soup.get_text(" ", strip=True))

    title = clean(listing_title)
    location = ""
    date_posted = ""
    description = ""

    for obj in _jsonld_objects(soup):
        typ = obj.get("@type")
        types = typ if isinstance(typ, list) else [typ]

        if any(str(x).lower() == "jobposting" for x in types if x):
            title = clean(obj.get("title") or obj.get("name") or title)
            location = _flatten_location(
                obj.get("jobLocation")
                or obj.get("applicantLocationRequirements")
                or obj.get("jobLocationType")
            )
            date_posted = clean(obj.get("datePosted"))
            raw_desc = obj.get("description") or ""
            description = clean(
                BeautifulSoup(str(raw_desc), "html.parser").get_text(" ", strip=True)
            )
            break

    if not title:
        for selector in ("h1", '[class*="job-title"]', '[class*="jobTitle"]'):
            node = soup.select_one(selector)
            if node:
                candidate = clean(node.get_text(" ", strip=True))
                if candidate and candidate.lower() not in {"afficher", "postuler", "apply"}:
                    title = candidate
                    break

    if not location:
        for selector in (
            '[class*="location"]',
            '[id*="location"]',
            '[itemprop="jobLocation"]',
            '[class*="job-location"]',
        ):
            for node in soup.select(selector):
                candidate = clean(node.get("content") or node.get_text(" ", strip=True))
                if 2 < len(candidate) < 500:
                    if _is_belgium_text(candidate):
                        location = candidate
                        break
                    if not location:
                        location = candidate
            if _is_belgium_text(location):
                break

    # Taleo frequently uses generic H1 text. Recover title/location from table labels.
    if source == "SONACA":
        table_text = clean(soup.get_text("\n", strip=True))
        if not title or title.lower() in {"afficher", "postuler"}:
            for pattern in (
                r"(?:Titre du poste|Intitul[eé](?: du poste)?|Job Title)\s*[:\-]\s*([^\n]{3,180})",
                r"(?:Poste)\s*[:\-]\s*([^\n]{3,180})",
            ):
                m = re.search(pattern, table_text, re.I)
                if m:
                    title = clean(m.group(1))
                    break

            if not title or title.lower() in {"afficher", "postuler"}:
                title_tag = soup.find("title")
                if title_tag:
                    candidate = clean(title_tag.get_text(" ", strip=True))
                    candidate = re.sub(r"\s*[-|]\s*Sonaca.*$", "", candidate, flags=re.I)
                    if candidate.lower() not in {"afficher", "postuler"}:
                        title = candidate

        if not location:
            for pattern in (
                r"(?:Lieu|Localisation|Location)\s*[:\-]\s*([^\n]{2,160})",
                r"(?:Pays|Country)\s*[:\-]\s*([^\n]{2,100})",
            ):
                m = re.search(pattern, table_text, re.I)
                if m:
                    location = clean(m.group(1))
                    break

    if not description or len(description) < MIN_DESCRIPTION:
        description = text

    strict_be = _is_belgium_text(location)
    if trust_url_belgium and (
        "-in-belgium-" in r.url.lower()
        or "/belgium" in r.url.lower()
        or "country/belgium" in r.url.lower()
    ):
        strict_be = True
        if not location:
            location = "Belgium"

    return {
        "closed": False,
        "http": r.status_code,
        "url": r.url,
        "title": title,
        "location": location,
        "description": description,
        "date_posted": date_posted,
        "strict_belgium": strict_be,
        "hard_dutch": dutch_hard(description),
    }


def _make_job(source, company, row):
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


def _publish(source, *, seen, candidates, jobs, rejected_language=0,
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


def get_mega5_diag(source):
    return dict(_LAST_DIAG.get(str(source).upper(), {}))


def _html_listing_source(
    *,
    source,
    company,
    listing_url,
    link_regex,
    trust_url_belgium=False,
    max_detail_candidates=40,
):
    s = _session()
    r = s.get(listing_url, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    links = {}

    for a in soup.find_all("a", href=True):
        href = clean(a.get("href"))
        if not href:
            continue
        url = urljoin(r.url, href).split("#", 1)[0]
        if not re.search(link_regex, url, re.I):
            continue
        title = clean(a.get_text(" ", strip=True))
        links[url] = title

    # Raw HTML fallback.
    absolute_pattern = re.compile(
        rf'https?://[^"\'\s<>]+',
        re.I,
    )
    for m in absolute_pattern.finditer(r.text or ""):
        url = m.group(0).rstrip("\\/")
        if re.search(link_regex, url, re.I):
            links.setdefault(url, "")

    seen = len(links)
    candidate_links = [
        (url, title)
        for url, title in links.items()
        if _is_target(title)
    ]

    # If the listing anchor text is generic, inspect a limited number of detail pages.
    if not candidate_links and source in {"SONACA", "QBD_GROUP", "TMC"}:
        candidate_links = list(links.items())[:max_detail_candidates]

    jobs = []
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    detail_errors = 0
    true_candidates = 0
    geo_truth = 0
    sample_checked = 0

    for idx, (url, listing_title) in enumerate(candidate_links[:max_detail_candidates]):
        if idx:
            time.sleep(0.12)

        try:
            row = _extract_detail(
                url,
                listing_title=listing_title,
                source=source,
                trust_url_belgium=trust_url_belgium,
            )
        except requests.HTTPError as exc:
            # One transient rate-limit must not poison a large source.
            status = getattr(exc.response, "status_code", None)
            if status == 429:
                time.sleep(1.0)
                try:
                    row = _extract_detail(
                        url,
                        listing_title=listing_title,
                        source=source,
                        trust_url_belgium=trust_url_belgium,
                    )
                except Exception:
                    detail_errors += 1
                    continue
            else:
                detail_errors += 1
                continue
        except Exception:
            detail_errors += 1
            continue

        sample_checked += 1

        if row.get("closed"):
            closed += 1
            continue

        if row.get("location"):
            geo_truth += 1

        if not _is_target(row.get("title")):
            continue

        true_candidates += 1

        if not row.get("strict_belgium"):
            rejected_geo += 1
            continue

        if len(clean(row.get("description"))) < MIN_DESCRIPTION:
            detail_errors += 1
            continue

        if row.get("hard_dutch"):
            rejected_language += 1
            continue

        jobs.append(_make_job(source, company, row))

    # Healthy-empty transport proof: inspect one detail if no candidate was checked.
    if seen and sample_checked == 0:
        url, listing_title = next(iter(links.items()))
        try:
            probe = _extract_detail(
                url,
                listing_title=listing_title,
                source=source,
                trust_url_belgium=trust_url_belgium,
            )
            sample_checked += 1
            if probe.get("location"):
                geo_truth += 1
            if probe.get("closed"):
                closed += 1
        except Exception:
            detail_errors += 1

    return _publish(
        source,
        seen=seen,
        candidates=true_candidates,
        jobs=jobs,
        rejected_language=rejected_language,
        rejected_geo=rejected_geo,
        closed=closed,
        detail_errors=detail_errors,
        diag={
            "listing_http": r.status_code,
            "listing_links": seen,
            "sample_checked": sample_checked,
            "geo_truth_count": geo_truth,
            "trusted_belgium_url": bool(trust_url_belgium),
        },
    )


def collect_pauwels_jobs():
    return _html_listing_source(
        source="PAUWELS",
        company="Pauwels Consulting",
        listing_url="https://www.pauwelsconsulting.com/jobs/",
        link_regex=r"/job/[0-9a-f-]{20,}/[^/?#]+$",
        trust_url_belgium=False,
        max_detail_candidates=30,
    )


def collect_icon_jobs():
    return _html_listing_source(
        source="ICON",
        company="ICON plc",
        listing_url="https://careers.iconplc.com/jobs-in-belgium",
        link_regex=r"/job/[^/?#]+-in-belgium-[^/?#]+-jid-\d+$",
        trust_url_belgium=True,
        max_detail_candidates=30,
    )


def collect_odoo_jobs():
    # Strict JSON-LD/location parsing avoids the old Philippines=>Belgium false positive.
    return _html_listing_source(
        source="ODOO",
        company="Odoo",
        listing_url="https://www.odoo.com/fr_FR/jobs",
        link_regex=r"/(?:fr_FR|en_US)/jobs/[^/?#]+-\d+$",
        trust_url_belgium=False,
        max_detail_candidates=30,
    )


def collect_parexel_jobs():
    return _html_listing_source(
        source="PAREXEL",
        company="Parexel",
        listing_url="https://jobs.parexel.com/en/location/belgium-jobs/877/2802361/2",
        link_regex=r"/en/job/[^/?#]+/\d+/\d+$",
        trust_url_belgium=False,
        max_detail_candidates=25,
    )


def collect_sopra_steria_jobs():
    # Only explicit Belgian job URLs are eligible.
    return _html_listing_source(
        source="SOPRA_STERIA",
        company="Sopra Steria Belgium",
        listing_url="https://careers.soprasteria.com/",
        link_regex=r"/job/[^/?#]+-in-[^/?#]*belgium-jid-\d+$",
        trust_url_belgium=True,
        max_detail_candidates=30,
    )


def collect_tmc_jobs():
    return _html_listing_source(
        source="TMC",
        company="The Member Company / TMC",
        listing_url="https://www.themembercompany.com/careers/",
        link_regex=r"/careers/(?!page/|corporate-vacancies/?$)[A-Za-z0-9._-]+$",
        trust_url_belgium=False,
        max_detail_candidates=30,
    )


def collect_qbd_group_jobs():
    return _html_listing_source(
        source="QBD_GROUP",
        company="QbD Group",
        listing_url="https://careers.qbdgroup.com/jobs",
        link_regex=r"/(?:[a-z]{2}/)?jobs/\d+-[^/?#]+$",
        trust_url_belgium=False,
        max_detail_candidates=35,
    )


def collect_sonaca_jobs():
    # Use viewRequisition only, never applyRequisition.
    return _html_listing_source(
        source="SONACA",
        company="Sonaca",
        listing_url="https://lde.tbe.taleo.net/lde01/ats/careers/v2/searchResults?org=SONACA&cws=38",
        link_regex=r"/ats/careers/v2/viewRequisition\?[^#]*\brid=\d+",
        trust_url_belgium=False,
        max_detail_candidates=40,
    )


def _collect_phenom_source(
    *,
    source,
    company,
    host,
    locale_path,
    lang,
    country,
    ref_num,
    page_id,
):
    cache = Path(__file__).resolve().parents[1] / "logs" / f"{source.lower()}_phenom_cache"

    client = PhenomClient(
        host=host,
        locale_path=locale_path,
        lang=lang,
        country=country,
        ref_num=ref_num,
        page_id=page_id,
        cache_dir=cache,
    )

    rows_all = []
    errors = 0
    offset = 0
    total = None

    for _ in range(8):
        payload, error = client.search(
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

    # Do not trust facet alone: require an explicit Belgium signal in each row.
    be_rows = []
    for row in rows_all:
        loc = clean(job_location(row))
        raw = clean(json.dumps(row, ensure_ascii=False))
        if _is_belgium_text(loc) or _is_belgium_text(raw):
            be_rows.append(row)

    candidate_rows = [row for row in be_rows if _is_target(job_title(row))]

    jobs = []
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    detail_errors = errors
    geo_truth = len(be_rows)

    for row in candidate_rows:
        url = client.public_job_url(row)
        if not url:
            detail_errors += 1
            continue

        try:
            detail = _extract_detail(
                url,
                listing_title=clean(job_title(row)),
                source=source,
                trust_url_belgium=False,
            )
        except Exception:
            detail_errors += 1
            continue

        if detail.get("closed"):
            closed += 1
            continue

        # Listing row has already proved explicit Belgium. Detail may omit it.
        detail["strict_belgium"] = True
        if not detail.get("location"):
            detail["location"] = clean(job_location(row)) or "Belgium"
        detail["external_id"] = clean(job_external_id(row))
        detail["date_posted"] = clean(job_posted_date(row))

        if len(clean(detail.get("description"))) < MIN_DESCRIPTION:
            detail_errors += 1
            continue

        if detail.get("hard_dutch"):
            rejected_language += 1
            continue

        jobs.append(_make_job(source, company, detail))

    # Healthy-empty proof: facet call itself is valid if explicit BE rows exist.
    return _publish(
        source,
        seen=len(be_rows),
        candidates=len(candidate_rows),
        jobs=jobs,
        rejected_language=rejected_language,
        rejected_geo=rejected_geo,
        closed=closed,
        detail_errors=detail_errors,
        diag={
            "facet_total": total,
            "facet_rows": len(rows_all),
            "explicit_belgium_rows": len(be_rows),
            "geo_truth_count": geo_truth,
            "trusted_belgium_url": False,
        },
    )


def collect_lilly_jobs():
    return _collect_phenom_source(
        source="LILLY",
        company="Eli Lilly Belgium",
        host="https://careers.lilly.com",
        locale_path="/us/en",
        lang="en_us",
        country="us",
        ref_num="LILLUS",
        page_id="page11",
    )


def collect_thales_jobs():
    return _collect_phenom_source(
        source="THALES",
        company="Thales Belgium",
        host="https://careers.thalesgroup.com",
        locale_path="/global/en",
        lang="en_global",
        country="global",
        ref_num="TGPTGWGLOBAL",
        page_id="page18",
    )
