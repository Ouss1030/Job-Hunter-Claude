from __future__ import annotations

import re

from bs4 import BeautifulSoup
from urllib.parse import urljoin

from sources.batch3_wallonia_engine import clean, fetch_detail, finalize, session

QUANTOOM_VERSION = "1.0"
URL = "https://quantoom.com/job-application/"


def collect_quantoom_jobs():
    s = session()
    r = s.get(URL, timeout=30, allow_redirects=True)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    links = {}

    for anchor in soup.find_all("a", href=True):
        href = clean(anchor.get("href"))
        if "/job/" not in href:
            continue

        url = urljoin(r.url, href).split("#", 1)[0]

        if url.rstrip("/") == URL.rstrip("/"):
            continue

        title = clean(anchor.get_text(" ", strip=True))
        if title:
            links[url] = title

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

        slug = re.search(r"/job/([^/?#]+)/?", url)

        rows.append(
            {
                "title": clean(detail.get("title")) or listing_title,
                "location": detail.get("location"),
                "geo": detail.get("geo"),
                "hard_dutch": detail.get("hard_dutch"),
                "description": detail.get("description"),
                "url": url,
                "external_id": slug.group(1) if slug else None,
            }
        )

    return finalize(
        source="QUANTOOM",
        company="Quantoom Biosciences",
        rows=rows,
        detail_errors=detail_errors,
        closed=closed,
    )
