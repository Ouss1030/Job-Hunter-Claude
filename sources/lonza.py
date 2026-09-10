from __future__ import annotations

import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from database.models import JobOffer
from sources.belgium_locations import BELGIUM, classify_belgium_location
from sources.source_metrics import publish_source_metrics
from sources.batch2_radancy_country_engine import dutch_hard, title_is_target

LONZA_VERSION = "1.1"


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

LISTING_URL = "https://www.lonza.com/careers/job-search.aspx"
BELGIUM_LOCATIONS = ("Belgium, Bornem", "Belgium, Verviers")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/152.0.0.0 Safari/537.36"
)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8",
    })
    return s


def _form_payload(form, location):
    payload = []

    for element in form.find_all(["input", "select", "textarea"]):
        name = clean(element.get("name"))
        if not name or name == "job_location_facet_sm":
            continue

        if element.name == "input":
            typ = clean(element.get("type")).lower()
            if typ in {"submit", "button", "image", "file", "reset"}:
                continue
            if typ in {"checkbox", "radio"} and not element.has_attr("checked"):
                continue
            payload.append((name, clean(element.get("value"))))

        elif element.name == "select":
            selected = element.find_all("option", selected=True)
            if not selected:
                first = element.find("option")
                selected = [first] if first else []
            for option in selected:
                if option is not None:
                    payload.append((name, clean(option.get("value"))))

        elif element.name == "textarea":
            payload.append((name, clean(element.get_text(" ", strip=True))))

    payload.append(("job_location_facet_sm", location))
    return payload


def _search_form(soup):
    # This is the official career search form observed in Batch 2.11.
    form = soup.find("form", id="lonza-search")
    if form is not None and clean(form.get("method") or "get").lower() == "post":
        return form

    # Stable fallback: POST to current page, q field, but not the pagination form.
    for candidate in soup.find_all("form"):
        method = clean(candidate.get("method") or "get").lower()
        action = clean(candidate.get("action"))
        names = {
            clean(x.get("name"))
            for x in candidate.find_all(["input", "select", "textarea"])
            if clean(x.get("name"))
        }
        if method == "post" and action in {"", LISTING_URL} and "q" in names and "pg" not in names:
            return candidate

    return None


def _parse_rows(base_url, html):
    soup = BeautifulSoup(html or "", "html.parser")
    rows = {}

    for anchor in soup.find_all("a", href=True):
        href = clean(anchor.get("href"))
        if not re.search(r"/jobs/R\d+", href, flags=re.I):
            continue

        url = urljoin(base_url, href).split("#", 1)[0]

        # IMPORTANT: the anchor itself is the job card on Lonza.
        classes = {str(x) for x in (anchor.get("class") or [])}
        if "search-result" in classes:
            card = anchor
        else:
            card = anchor.find_parent(class_=lambda value: value and "search-result" in str(value))
            if card is None:
                card = anchor

        title_node = card.select_one(".search-result-title")
        location_node = card.select_one(".search-result-content")

        title = clean(
            title_node.get_text(" ", strip=True)
            if title_node is not None
            else anchor.get_text(" ", strip=True)
        )
        location = clean(
            location_node.get_text(" ", strip=True)
            if location_node is not None
            else ""
        )

        rows[url] = {
            "title": title,
            "location": location,
            "url": url,
        }

    return list(rows.values())



def collect_lonza_listing_rows():
    """Collect Belgium listing rows from Lonza's official location facets."""
    s = _session()

    response = s.get(LISTING_URL, timeout=30, allow_redirects=True)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    form = _search_form(soup)
    if form is None:
        raise RuntimeError("Lonza official career search POST form not found.")

    all_rows = {}

    for location in BELGIUM_LOCATIONS:
        target = urljoin(response.url, clean(form.get("action")) or response.url)

        result = s.post(
            target,
            data=_form_payload(form, location),
            timeout=30,
            allow_redirects=True,
            headers={"Referer": response.url},
        )
        result.raise_for_status()

        for row in _parse_rows(result.url, result.text):
            decision = classify_belgium_location(
                row["location"],
                trusted_belgium_listing=True,
                extra_belgium_markers=("Bornem", "Verviers"),
            )
            _GEO_RUNTIME_COUNTS[_geo_status_key(decision)] += 1
            if decision.status != BELGIUM:
                continue
            all_rows[row["url"]] = row

    return list(all_rows.values())


def probe_lonza_listing():
    _reset_geo_runtime_counters()
    rows = collect_lonza_listing_rows()
    return {
        "seen": len(rows),
        "unique_urls": len({x["url"] for x in rows}),
        "unique_titles": len({x["title"] for x in rows}),
        "all_belgium": all(
            classify_belgium_location(
                x["location"],
                trusted_belgium_listing=True,
                extra_belgium_markers=("Bornem", "Verviers"),
            ).status == BELGIUM
            for x in rows
        ),
        "geo": _geo_runtime_counters(),
        "rows": rows,
    }

def _strip_html(value):
    if not value:
        return ""
    try:
        return clean(BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True))
    except Exception:
        return clean(value)


def _parse_detail(html):
    soup = BeautifulSoup(html or "", "html.parser")

    title = ""
    h1 = soup.find("h1")
    if h1 is not None:
        title = clean(h1.get_text(" ", strip=True))

    description = ""
    date_published = ""
    contract_type = ""

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw:
            continue

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

            if obj.get("@type") == "JobPosting":
                title = clean(obj.get("title")) or title
                description = _strip_html(obj.get("description")) or description
                date_published = clean(obj.get("datePosted")) or date_published
                contract_type = clean(obj.get("employmentType")) or contract_type

            stack.extend(obj.values())

    if len(description) < 250:
        candidates = []
        for selector in [
            '[itemprop="description"]',
            ".job-description",
            ".jobDescription",
            ".job-description-content",
            ".job-details",
            "main",
        ]:
            try:
                for node in soup.select(selector):
                    text = clean(node.get_text(" ", strip=True))
                    if len(text) >= 250:
                        candidates.append(text)
            except Exception:
                pass

        if candidates:
            visible = max(candidates, key=len)
            if len(visible) > len(description):
                description = visible

    return {
        "title": title,
        "description": description,
        "date_published": date_published,
        "contract_type": contract_type,
    }


def _publish_metrics(payload):
    publish_source_metrics("LONZA", payload)


def collect_lonza_jobs():
    _reset_geo_runtime_counters()
    rows = collect_lonza_listing_rows()

    candidates = [row for row in rows if title_is_target(row["title"])]

    jobs = []
    rejected_language = 0
    rejected_geo = 0
    closed = 0
    detail_errors = 0

    s = _session()

    for row in candidates:
        if classify_belgium_location(row["location"]).status != BELGIUM:
            rejected_geo += 1
            continue

        try:
            response = s.get(row["url"], timeout=30, allow_redirects=True)

            if response.status_code in {404, 410}:
                closed += 1
                continue

            response.raise_for_status()
            detail = _parse_detail(response.text)
        except Exception:
            detail_errors += 1
            continue

        description = clean(detail.get("description"))
        if len(description) < 250:
            detail_errors += 1
            continue

        if dutch_hard(description):
            rejected_language += 1
            continue

        match = re.search(r"/jobs/(R\d+)", row["url"], flags=re.I)
        external_id = match.group(1).upper() if match else row["url"].rstrip("/").split("/")[-1]

        jobs.append(
            JobOffer(
                source="LONZA",
                external_id=external_id,
                title=clean(detail.get("title") or row["title"]),
                company="Lonza",
                location=row["location"],
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
    print("LONZA - BELGIUM POST FACET")
    print("=" * 88)
    for key, value in metrics.items():
        print(f"{key:<20}: {value}")
    for job in jobs:
        print("KEEP |", job.title, "|", job.location)

    return jobs
