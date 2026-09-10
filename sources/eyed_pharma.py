from __future__ import annotations

import re

from bs4 import BeautifulSoup
from urllib.parse import urljoin

from sources.batch3_wallonia_engine import clean, fetch_detail, finalize, session

EYED_PHARMA_VERSION = "1.0"
URL = "https://www.eyedpharma.com/careers/"


def collect_eyed_pharma_jobs():
    s = session()
    r = s.get(URL, timeout=30, allow_redirects=True)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    links = {}

    for anchor in soup.find_all("a", href=True):
        href = clean(anchor.get("href"))

        if not href or href.startswith(("mailto:", "tel:")):
            continue

        url = urljoin(r.url, href).split("#", 1)[0]

        if url.rstrip("/") == URL.rstrip("/"):
            continue

        low = url.lower()
        if not (
            "/rd-" in low
            or "/qa-" in low
            or "quality" in low
            or "scientist" in low
            or "technician" in low
            or "manager" in low
        ):
            continue

        title = clean(anchor.get_text(" ", strip=True))
        links[url] = title

    # Current site has also used this direct vacancy page.
    page_text = clean(soup.get_text(" ", strip=True))
    if "R&D QA Manager" in page_text:
        links.setdefault(
            urljoin(r.url, "/rd-qa-manager/"),
            "R&D QA Manager",
        )

    rows = []
    detail_errors = 0
    closed = 0

    for url, listing_title in links.items():
        try:
            detail = fetch_detail(s, url)
        except Exception:
            detail_errors += 1
            continue

        if detail.get("closed"):
            closed += 1
            continue

        slug = re.search(r"/([^/?#]+)/?$", url)

        rows.append(
            {
                "title": clean(detail.get("title")) or listing_title,
                "location": detail.get("location") or "Seraing, Belgium",
                "geo": "BELGIUM",
                "hard_dutch": detail.get("hard_dutch"),
                "description": detail.get("description"),
                "url": url,
                "external_id": slug.group(1) if slug else None,
            }
        )

    return finalize(
        source="EYED_PHARMA",
        company="EyeD Pharma",
        rows=rows,
        detail_errors=detail_errors,
        closed=closed,
    )
