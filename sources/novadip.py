from __future__ import annotations

import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from sources.batch4_engine import build_jobs, clean, dutch_hard

NOVADIP_VERSION = "1.0"
URL = "https://novadip.com/careers/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/152 Safari/537.36"


def collect_novadip_jobs():
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    r = s.get(URL, timeout=30, allow_redirects=True)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    links = {}

    for a in soup.find_all("a", href=True):
        href = clean(a.get("href"))
        u = urljoin(r.url, href).split("#", 1)[0]
        if "/open-positions/" not in u.lower() or u.rstrip("/") == URL.rstrip("/"):
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
            slug = re.search(r"/open-positions/([^/?#]+)/?", u)
            rows.append(
                {
                    "title": title or listing_title,
                    "location": "Mont-Saint-Guibert, Belgium",
                    "description": text,
                    "hard_dutch": dutch_hard(text),
                    "url": u,
                    "external_id": slug.group(1) if slug else None,
                }
            )
        except Exception:
            detail_errors += 1

    return build_jobs("NOVADIP", "Novadip Biosciences", rows, detail_errors)
