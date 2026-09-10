from __future__ import annotations

from bs4 import BeautifulSoup
from urllib.parse import urljoin

from sources.batch3_wallonia_engine import (
    clean,
    fetch_detail,
    finalize,
    session,
)

BIOWIN_VERSION = "1.0"
URL = "https://www.biowin.org/jobs/"


def _listing_title(anchor):
    card = anchor.find_parent(["article", "li", "div"])

    if card:
        for node in card.find_all(["h2", "h3", "h4", "h5", "strong"], limit=10):
            title = clean(node.get_text(" ", strip=True))
            if title and title.lower() not in {"learn more", "read more"}:
                return title

    title = clean(anchor.get_text(" ", strip=True))
    if title.lower() in {"learn more", "read more"}:
        return ""
    return title


def collect_biowin_jobs():
    s = session()
    r = s.get(URL, timeout=30, allow_redirects=True)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    links = {}

    for anchor in soup.find_all("a", href=True):
        href = clean(anchor.get("href"))
        if "/jobs/" not in href:
            continue

        url = urljoin(r.url, href).split("#", 1)[0]

        if url.rstrip("/") == URL.rstrip("/"):
            continue

        title = _listing_title(anchor)
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

        detail_title = clean(detail.get("title"))
        if not detail_title or detail_title.lower() in {"learn more", "read more"}:
            detail_title = listing_title

        rows.append(
            {
                "title": detail_title,
                "location": detail.get("location"),
                "geo": detail.get("geo"),
                "hard_dutch": detail.get("hard_dutch"),
                "description": detail.get("description"),
                "url": url,
                "company": "BioWin member employer",
            }
        )

    return finalize(
        source="BIOWIN",
        company="BioWin member employer",
        rows=rows,
        detail_errors=detail_errors,
        closed=closed,
    )
