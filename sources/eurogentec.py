from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from sources.batch3_wallonia_engine import clean, fetch_detail, finalize, session

EUROGENTEC_VERSION = "1.1"
URL = "https://www.eurogentec.com/en/job-list"


def _detail_urls(base_url, html):
    soup = BeautifulSoup(html or "", "html.parser")
    urls = set()

    for anchor in soup.find_all("a", href=True):
        href = clean(anchor.get("href"))
        if re.search(r"/jobs/job/details/\d+", href, re.I):
            urls.add(urljoin(base_url, href).split("#", 1)[0])

    # Fallback for links rendered in attributes/scripts but not normal anchors.
    for match in re.finditer(
        r"""(?P<url>(?:https?://[^"' <>()]+)?/en/jobs/job/details/\d+)""",
        html or "",
        flags=re.I,
    ):
        urls.add(urljoin(base_url, match.group("url")).split("#", 1)[0])

    return sorted(urls)


def collect_eurogentec_jobs():
    s = session()
    response = s.get(URL, timeout=30, allow_redirects=True)
    response.raise_for_status()

    urls = _detail_urls(response.url, response.text)

    rows = []
    detail_errors = 0
    closed = 0

    for url in urls:
        try:
            detail = fetch_detail(s, url)
        except Exception:
            detail_errors += 1
            continue

        if detail.get("closed"):
            closed += 1
            continue

        match = re.search(r"/details/(\d+)", url)

        rows.append(
            {
                "title": clean(detail.get("title")),
                "location": detail.get("location") or "Liège, Belgium",
                "geo": "BELGIUM",
                "hard_dutch": detail.get("hard_dutch"),
                "description": detail.get("description"),
                "url": url,
                "external_id": match.group(1) if match else None,
            }
        )

    return finalize(
        source="EUROGENTEC",
        company="Kaneka Eurogentec",
        rows=rows,
        detail_errors=detail_errors,
        closed=closed,
    )


def probe_eurogentec_listing():
    s = session()
    response = s.get(URL, timeout=30, allow_redirects=True)
    response.raise_for_status()
    urls = _detail_urls(response.url, response.text)
    return {
        "http": response.status_code,
        "html_len": len(response.text or ""),
        "detail_urls": len(urls),
        "urls": urls,
    }
