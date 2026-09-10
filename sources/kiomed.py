from __future__ import annotations

import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

from sources.batch4_engine import build_jobs, clean, dutch_hard

KIOMED_VERSION = "1.0"
URL = "https://www.kiomedpharma.com/jobs/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/152 Safari/537.36"


def collect_kiomed_jobs():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en,fr;q=0.8"})
    r = s.get(URL, timeout=30, allow_redirects=True)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    links = {}

    for a in soup.find_all("a", href=True):
        href = clean(a.get("href"))
        if not href or "@" in href or href.startswith(("mailto:", "tel:")):
            continue
        u = urljoin(r.url, href).split("#", 1)[0]
        path = urlparse(u).path.lower()
        if not path.startswith("/jobs/") or path.rstrip("/") == "/jobs":
            continue
        title = clean(a.get_text(" ", strip=True))
        if title:
            links[u] = title

    rows = []
    detail_errors = 0

    for u, listing_title in links.items():
        try:
            rr = s.get(u, timeout=30, allow_redirects=True)
            rr.raise_for_status()
            ss = BeautifulSoup(rr.text, "html.parser")
            text = clean(ss.get_text(" ", strip=True))
            h1 = ss.find("h1")
            title = clean(h1.get_text(" ", strip=True)) if h1 else listing_title
            slug = re.search(r"/jobs/([^/?#]+)/?", u)
            rows.append(
                {
                    "title": title or listing_title,
                    "location": "Herstal, Belgium",
                    "description": text,
                    "hard_dutch": dutch_hard(text),
                    "url": u,
                    "external_id": slug.group(1) if slug else None,
                }
            )
        except Exception:
            detail_errors += 1

    return build_jobs("KIOMED", "KiOmed Pharma", rows, detail_errors)
