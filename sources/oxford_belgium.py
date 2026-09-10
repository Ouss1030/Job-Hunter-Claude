"""
JOB HUNTER BELGIUM
OXFORD GLOBAL RESOURCES - BELGIUM DIRECT COLLECTOR V1.0

Uses Oxford's dedicated Belgium inventory while preserving the historical
source key OXFORD_GLOBAL. No anti-bot bypass is used.
"""

from __future__ import annotations

import html as html_lib
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from database.models import JobOffer
from sources.batch4_engine import publish_metrics
from sources.belgium_locations import BELGIUM, FOREIGN, classify_belgium_location
from sources.mega65_staffing import (
    GENERIC_PRODUCTION,
    SCIENCE_CONTEXT,
    TITLE_EXCLUDE,
    hard_dutch,
    parse_jsonld,
    strict_geo,
    track_hits,
    years_required,
)

OXFORD_BELGIUM_VERSION = "1.0"
SOURCE_KEY = "OXFORD_GLOBAL"
COMPANY = "Oxford Global Resources"
LIST_URL = "https://jobs.oxfordcorp.com/fr/emplois/europe-belgium"
DETAIL_RE = re.compile(r"/fr/emploi/[^/?#]+-\d+/?$", re.I)
TIMEOUT = 30
DETAIL_DELAY_SECONDS = 0.08
MAX_DETAILS = 120

CLOSED_MARKERS = (
    "this job is no longer available",
    "this vacancy is no longer available",
    "this position is no longer available",
    "cette offre n'est plus disponible",
    "cette offre n’est plus disponible",
    "ce poste n'est plus disponible",
    "ce poste n’est plus disponible",
    "vacature is niet langer beschikbaar",
    "vacature is niet meer beschikbaar",
)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.4",
})


def clean(value) -> str:
    if value is None:
        return ""
    return re.sub(
        r"\s+",
        " ",
        html_lib.unescape(str(value)).replace("\xa0", " "),
    ).strip()


def _strip_html(value) -> str:
    if not value:
        return ""
    return clean(BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True))


def _external_id(url: str) -> str:
    path = urlparse(clean(url)).path.rstrip("/")
    match = re.search(r"-(\d+)$", path)
    if match:
        return match.group(1)
    return path.rsplit("/", 1)[-1] or clean(url)


def _jobposting(soup: BeautifulSoup) -> dict:
    jobs = parse_jsonld(soup)
    return jobs[0] if jobs else {}


def _structured_location(obj: dict) -> str:
    if not isinstance(obj, dict):
        return ""
    values = obj.get("jobLocation") or obj.get("applicantLocationRequirements") or []
    if not isinstance(values, list):
        values = [values]
    labels = []
    for item in values:
        if not isinstance(item, dict):
            continue
        address = item.get("address") or item
        if not isinstance(address, dict):
            continue
        country = address.get("addressCountry")
        if isinstance(country, dict):
            country = country.get("name") or country.get("value") or country.get("@id")
        parts = [
            clean(address.get("addressLocality")),
            clean(address.get("addressRegion")),
            clean(country),
        ]
        label = ", ".join(x for x in parts if x)
        if label and label not in labels:
            labels.append(label)
    return " | ".join(labels)


def _main_text(soup: BeautifulSoup) -> str:
    main = soup.find("main") or soup.find("article") or soup.body or soup
    return clean(main.get_text(" ", strip=True))


def _visible_location(soup: BeautifulSoup, page_text: str) -> str:
    for node in soup.find_all(string=re.compile(r"^\s*(?:Lieu|Location)\s*:?\s*$", re.I)):
        parent = node.parent
        if parent is None:
            continue
        for sibling in list(parent.next_siblings)[:5]:
            if getattr(sibling, "get_text", None):
                text = clean(sibling.get_text(" ", strip=True))
            else:
                text = clean(sibling)
            if text and len(text) <= 160:
                return text

    match = re.search(
        r"(?:Lieu|Location)\s*:?\s*(.{2,160}?)(?=\s+(?:Contact|Type de poste|Job Type|"
        r"Téléphone|Phone|Secteurs d.?activité|Industry|Contact E-mail|Recruiter)\s*:)",
        page_text,
        re.I,
    )
    return clean(match.group(1)) if match else ""


def _extract_listing_rows(html: str) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    rows = {}

    for anchor in soup.find_all("a", href=True):
        absolute = urljoin(LIST_URL, clean(anchor.get("href")))
        if not DETAIL_RE.search(urlparse(absolute).path):
            continue

        title = clean(anchor.get_text(" ", strip=True))
        if not title or title.lower() in {
            "en savoir plus",
            "postuler maintenant",
            "apply now",
            "save job",
        }:
            container = anchor.find_parent(["article", "li", "div"])
            if container is not None:
                heading = container.find(["h2", "h3", "h4"])
                if heading is not None:
                    title = clean(heading.get_text(" ", strip=True))

        key = absolute.lower().rstrip("/")
        candidate = {
            "url": absolute,
            "title": title,
            "external_id": _external_id(absolute),
        }

        if key not in rows:
            rows[key] = candidate
        elif title and len(title) > len(rows[key].get("title") or ""):
            rows[key] = candidate

    return list(rows.values())


def collect_oxford_belgium_listing() -> list[dict]:
    response = SESSION.get(LIST_URL, timeout=TIMEOUT, allow_redirects=True)
    response.raise_for_status()
    return _extract_listing_rows(response.text)[:MAX_DETAILS]


def _detail(row: dict) -> dict:
    response = SESSION.get(row["url"], timeout=TIMEOUT, allow_redirects=True)

    if response.status_code in {404, 410}:
        return {
            "closed": True,
            "url": response.url,
            "error": f"HTTP {response.status_code}",
        }

    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    page_text = _main_text(soup)
    low = page_text.lower()

    if any(marker in low for marker in CLOSED_MARKERS):
        return {
            "closed": True,
            "url": response.url,
            "error": "Oxford : offre fermée",
        }

    obj = _jobposting(soup)

    title = clean(obj.get("title") or obj.get("name")) if obj else ""
    if not title:
        h1 = soup.find("h1")
        title = clean(h1.get_text(" ", strip=True)) if h1 else clean(row.get("title"))

    description = _strip_html(obj.get("description")) if obj else ""
    if len(description) < 250:
        description = page_text

    structured_location = _structured_location(obj)
    visible_location = _visible_location(soup, page_text)
    location = structured_location or visible_location

    decision = classify_belgium_location(location) if location else None

    if decision and decision.status == FOREIGN:
        geo = "FOREIGN"
    elif decision and decision.status == BELGIUM:
        geo = "BE"
    else:
        # Explicit foreign evidence in the live detail always overrides
        # the country-scoped Belgium listing.
        legacy_geo, legacy_location = strict_geo(obj, page_text, False)
        if legacy_geo == "FOREIGN":
            geo = "FOREIGN"
            if not location:
                location = legacy_location
        elif legacy_geo == "BE":
            geo = "BE"
            if not location:
                location = legacy_location
        else:
            geo = "BE_TRUSTED_LISTING"
            if not location:
                location = "Belgium (Oxford Belgium listing)"

    tracks = track_hits(title)

    if not tracks and GENERIC_PRODUCTION.search(title):
        if SCIENCE_CONTEXT.search(title + " " + description[:5000]):
            tracks = ["CHEM_LAB"]

    # Bridge for Dutch discovery titles. The full description is checked below,
    # so this broadens recall without letting Dutch-only jobs through.
    if not tracks and re.search(
        r"\b(?:laborant|laboratorium|lab|qc|qa|quality|validation|validatie|"
        r"chemie|chemist|masterdata|data analyst|data steward|cleanroom)\b",
        title,
        re.I,
    ):
        if re.search(
            r"\b(?:laborant|laboratorium|lab|qc|qa|quality|validation|validatie|"
            r"chemie|chemist|cleanroom)\b",
            title,
            re.I,
        ):
            tracks = ["CHEM_LAB"]
        else:
            tracks = ["DATA_BI"]

    years = years_required(description)

    if not tracks:
        fit = "NOT_TARGET"
    elif TITLE_EXCLUDE.search(title):
        fit = "REJECT_SENIORITY"
    elif geo == "FOREIGN":
        fit = "REJECT_GEO"
    elif hard_dutch(description):
        fit = "REJECT_DUTCH"
    elif years is not None and years >= 4:
        fit = "REJECT_EXPERIENCE"
    elif years == 3:
        fit = "STRETCH"
    else:
        fit = "GOOD"

    return {
        "closed": False,
        "title": title,
        "description": description,
        "location": location,
        "geo": geo,
        "tracks": tracks,
        "years": years,
        "fit": fit,
        "url": response.url,
    }


def _make_job(row: dict, detail: dict) -> JobOffer:
    job = JobOffer(
        source=SOURCE_KEY,
        external_id=clean(row.get("external_id")) or _external_id(detail.get("url") or row["url"]),
        title=clean(detail.get("title") or row.get("title")) or "Offre Oxford",
        company=COMPANY,
        location=clean(detail.get("location")) or "Belgium",
        description=clean(detail.get("description")),
        url=clean(detail.get("url") or row["url"]),
        date_published=None,
        contract_type=None,
        language=None,
        salary=None,
    )
    job.collection_channel = SOURCE_KEY
    job.origin_source = SOURCE_KEY
    job.oxford_belgium_direct = True
    return job


def collect_oxford_global_jobs() -> list[JobOffer]:
    print("OXFORD - collecte directe via portail Belgique jobs.oxfordcorp.com")

    rows = collect_oxford_belgium_listing()
    print(f"OXFORD - BELGIUM LISTING : {len(rows)} offre(s) détectée(s)")

    jobs = []
    candidates = 0
    non_target = 0
    rejected_language = 0
    rejected_geo = 0
    rejected_seniority = 0
    rejected_experience = 0
    closed = 0
    detail_errors = 0
    geography_unknown_trusted = 0

    for index, row in enumerate(rows, 1):
        try:
            detail = _detail(row)
        except Exception as exc:
            detail_errors += 1
            print(
                f"[{index:02d}/{len(rows):02d}] ⚠ DETAIL | "
                f"{clean(row.get('title'))} | {type(exc).__name__}: {exc}"
            )
            continue

        if detail.get("closed"):
            closed += 1
            print(f"[{index:02d}/{len(rows):02d}] 💤 CLOSED | {clean(row.get('title'))}")
            continue

        if detail.get("geo") == "BE_TRUSTED_LISTING":
            geography_unknown_trusted += 1

        if not detail.get("tracks"):
            non_target += 1
            print(f"[{index:02d}/{len(rows):02d}] — NON_TARGET | {detail.get('title','')}")
            continue

        candidates += 1
        fit = detail.get("fit")

        if fit == "REJECT_GEO":
            rejected_geo += 1
            print(
                f"[{index:02d}/{len(rows):02d}] ⛔ GEO    | "
                f"{detail.get('title','')} | {detail.get('location','')}"
            )
            continue

        if fit == "REJECT_DUTCH":
            rejected_language += 1
            print(
                f"[{index:02d}/{len(rows):02d}] ⛔ NL     | "
                f"{detail.get('title','')} | {detail.get('location','')}"
            )
            continue

        if fit == "REJECT_SENIORITY":
            rejected_seniority += 1
            print(f"[{index:02d}/{len(rows):02d}] ⛔ SENIOR | {detail.get('title','')}")
            continue

        if fit == "REJECT_EXPERIENCE":
            rejected_experience += 1
            print(
                f"[{index:02d}/{len(rows):02d}] ⛔ EXP    | "
                f"{detail.get('title','')} | years={detail.get('years')}"
            )
            continue

        if fit not in {"GOOD", "STRETCH"}:
            print(f"[{index:02d}/{len(rows):02d}] ⚠ FIT={fit} | {detail.get('title','')}")
            continue

        job = _make_job(row, detail)
        jobs.append(job)

        print(
            f"[{index:02d}/{len(rows):02d}] ✅ {fit:<7} | "
            f"{job.title} | {job.location}"
        )

        if DETAIL_DELAY_SECONDS:
            time.sleep(DETAIL_DELAY_SECONDS)

    metrics = {
        "seen": len(rows),
        "candidates": candidates,
        "kept": len(jobs),
        "non_target": non_target,
        "rejected_language": rejected_language,
        "rejected_geo": rejected_geo,
        "rejected_seniority": rejected_seniority,
        "rejected_experience": rejected_experience,
        "closed": closed,
        "detail_errors": detail_errors,
        "geography_unknown_trusted": geography_unknown_trusted,
    }

    publish_metrics(SOURCE_KEY, metrics)

    print()
    print("=" * 94)
    print("OXFORD_GLOBAL - BELGIUM DIRECT V1.0")
    print("=" * 94)
    for key, value in metrics.items():
        print(f"{key:<28}: {value}")

    for job in jobs:
        print("KEEP |", job.title, "|", job.location)

    return jobs


if __name__ == "__main__":
    collect_oxford_global_jobs()
