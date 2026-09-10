from __future__ import annotations

from bs4 import BeautifulSoup
from urllib.parse import urljoin

from sources.batch3_wallonia_engine import clean, fetch_detail, finalize, session

BIOPARK_VERSION = "1.0"
URL = "https://biopark.jobs/fr/emplois-recents"


def collect_biopark_jobs():
    s = session()
    r = s.get(URL, timeout=30, allow_redirects=True)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    links = {}

    for anchor in soup.find_all("a", href=True):
        href = clean(anchor.get("href"))
        if "/fr/job/" not in href:
            continue

        url = urljoin(r.url, href).split("#", 1)[0]
        title = clean(anchor.get_text(" ", strip=True))

        if not title:
            card = anchor.find_parent(["article", "li", "div"])
            title = clean(card.get_text(" ", strip=True)) if card else ""

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

        rows.append(
            {
                "title": clean(detail.get("title")) or listing_title,
                "location": detail.get("location") or "Charleroi, Belgium",
                "geo": "BELGIUM",
                "hard_dutch": detail.get("hard_dutch"),
                "description": detail.get("description"),
                "url": url,
                "company": "BioPark employer",
            }
        )

    return finalize(
        source="BIOPARK",
        company="BioPark employer",
        rows=rows,
        detail_errors=detail_errors,
        closed=closed,
    )
