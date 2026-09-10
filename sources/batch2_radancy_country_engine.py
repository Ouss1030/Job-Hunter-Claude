from __future__ import annotations

import json
import re
import unicodedata
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from database.models import JobOffer
from sources.belgium_locations import BELGIUM, classify_belgium_location

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/152.0.0.0 Safari/537.36"
)

TARGET = [
    r"\bdata analyst\b", r"\bbusiness analyst\b", r"\bbusiness intelligence\b",
    r"\bpower\s*bi\b", r"\bdata quality\b", r"\bdata steward\b", r"\bmaster data\b",
    r"\bquality control\b", r"\bquality assurance\b", r"\bqc\b", r"\bqa\b",
    r"\blaboratory technician\b", r"\blab technician\b", r"\blaboratory analyst\b",
    r"\banalytical scientist\b", r"\banalytical analyst\b", r"\bchemist\b",
    r"\bmicrobiology\b", r"\bsample management\b",
]

EXCLUDE = [
    r"\bsenior\b", r"\bsr\.?\b", r"\bprincipal\b", r"\bdirector\b",
    r"\bhead\b", r"\bmanager\b", r"\bsupervisor\b",
    r"\bintern(?:ship)?\b", r"\btrainee\b", r"\bapprentice\b",
]

DUTCH = [
    r"\bfluent\s+dutch\b", r"\bprofessional\s+dutch\b",
    r"\bdutch\s+(?:is\s+)?required\b",
    r"\bgoede\s+kennis\s+(?:van\s+het\s+)?nederlands\b",
    r"\bnederlands\s+(?:is\s+)?vereist\b",
    r"\bvloeiend\s+nederlands\b", r"\btweetalig\b",
    r"\bma[iî]trise\s+du\s+n[eé]erlandais\b",
    r"\bn[eé]erlandais\s+(?:est\s+)?(?:exig[eé]|requis)\b",
]

OPTIONAL = [
    "asset", "plus", "preferred", "nice to have",
    "atout", "pluspunt", "souhaité", "souhaite",
]

def clean(x):
    return re.sub(r"\s+", " ", str(x or "")).strip()

def norm(x):
    s = unicodedata.normalize("NFKD", clean(x).lower())
    return "".join(c for c in s if not unicodedata.combining(c))

def title_is_target(title):
    t = clean(title)
    return (
        bool(t)
        and not any(re.search(p, t, re.I) for p in EXCLUDE)
        and any(re.search(p, t, re.I) for p in TARGET)
    )

def dutch_hard(text):
    for chunk in re.split(r"(?<=[.!?;:])\s+|[\r\n•●▪◦]+", str(text or "")):
        c = norm(chunk)
        if not c:
            continue
        if any(re.search(p, c, re.I) for p in DUTCH):
            if any(marker in c for marker in OPTIONAL):
                continue
            return True
    return False

def session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8",
    })
    return s

def extract_rows(base, html):
    soup = BeautifulSoup(html or "", "html.parser")
    out = {}
    for a in soup.find_all("a", href=True):
        href = clean(a.get("href"))
        if "/job/" not in href and "/en/job/" not in href:
            continue
        title = clean(a.get_text(" ", strip=True))
        if not title or title.lower() in {"view role", "save job", "save job button"}:
            continue
        out[urljoin(base, href).split("#", 1)[0]] = title
    return [{"url": url, "title": title} for url, title in out.items()]

def parse_job(html):
    soup = BeautifulSoup(html or "", "html.parser")
    title = clean(soup.find("h1").get_text(" ", strip=True)) if soup.find("h1") else ""
    location = ""
    description = ""

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or script.get_text())
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

            if obj.get("@type") == "JobPosting":
                title = clean(obj.get("title")) or title
                description = clean(obj.get("description")) or description

                locs = obj.get("jobLocation")
                locs = locs if isinstance(locs, list) else ([locs] if locs else [])
                found = []

                for loc in locs:
                    addr = loc.get("address", {}) if isinstance(loc, dict) else {}
                    if not isinstance(addr, dict):
                        continue

                    bits = []
                    for key in ["postalCode", "addressLocality", "addressRegion", "addressCountry"]:
                        value = addr.get(key)
                        if isinstance(value, dict):
                            value = value.get("name")
                        value = clean(value)
                        if value:
                            bits.append(value)

                    if bits:
                        found.append(", ".join(bits))

                if found:
                    location = " | ".join(found)

            stack.extend(obj.values())

    if not description:
        candidates = []
        for selector in [
            '[itemprop="description"]',
            ".job-description",
            ".jobDescription",
            ".jobdescription",
            "main",
        ]:
            try:
                for node in soup.select(selector):
                    txt = clean(node.get_text(" ", strip=True))
                    if len(txt) >= 300:
                        candidates.append(txt)
            except Exception:
                pass

        if candidates:
            description = max(candidates, key=len)

    return title, location, description

def _publish_metrics(key, payload):
    try:
        from sources import source_metrics
        store = getattr(source_metrics, "_STORE", None)
        if isinstance(store, dict):
            store[str(key).upper()] = dict(payload)
    except Exception:
        pass

def collect_country_source(key, company, listing_url):
    s = session()
    r = s.get(listing_url, timeout=30, allow_redirects=True)
    r.raise_for_status()

    all_rows = extract_rows(r.url, r.text)
    candidates = [row for row in all_rows if title_is_target(row["title"])]

    jobs = []
    rejected_geo = 0
    rejected_language = 0
    detail_errors = 0

    for row in candidates:
        try:
            d = s.get(row["url"], timeout=30, allow_redirects=True)
            d.raise_for_status()
            title, location, description = parse_job(d.text)
        except Exception:
            detail_errors += 1
            continue

        if classify_belgium_location(location).status != BELGIUM:
            rejected_geo += 1
            continue

        if dutch_hard(description):
            rejected_language += 1
            continue

        if len(description) < 250:
            detail_errors += 1
            continue

        external_id = row["url"].rstrip("/").split("/")[-1]

        jobs.append(
            JobOffer(
                source=key,
                external_id=external_id,
                title=clean(title or row["title"]),
                company=company,
                location=clean(location),
                description=clean(description),
                url=row["url"],
                date_published=None,
                contract_type=None,
                language=None,
            )
        )

    metrics = {
        "seen": len(all_rows),
        "candidates": len(candidates),
        "kept": len(jobs),
        "non_target": max(0, len(all_rows) - len(candidates)),
        "rejected_language": rejected_language,
        "rejected_geo": rejected_geo,
        "closed": 0,
        "detail_errors": detail_errors,
    }

    _publish_metrics(key, metrics)

    print()
    print("=" * 80)
    print(f"{key} - CONNECTOR")
    print("=" * 80)
    for k, v in metrics.items():
        print(f"{k:<20}: {v}")
    for job in jobs:
        print("KEEP |", job.title, "|", job.location)

    return jobs


# JOBHUNTER_UNIFIED_DISCOVERY_DETAIL_V1
from sources.unified_discovery import matches_master_title

_ud_original_title_is_target = title_is_target

def title_is_target(*args, **kwargs):
    if _ud_original_title_is_target(*args, **kwargs):
        return True
    try:
        title = args[0] if args else kwargs.get('title', '')
    except Exception:
        return False
    return matches_master_title(title)
