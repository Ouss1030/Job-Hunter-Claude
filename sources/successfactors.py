"""
JOB HUNTER BELGIUM
SAP SUCCESSFACTORS PUBLIC CAREER SITE - VERSION 1.0

Petit client générique pour les career sites SAP SuccessFactors / jobs2web.
Il ne contourne ni authentification ni anti-bot : GET publics uniquement.
"""
from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


def clean_text(value) -> str:
    if value is None:
        return ""
    value = html_lib.unescape(str(value)).replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


class SuccessFactorsClient:
    def __init__(
        self,
        base_url: str,
        all_jobs_path: str,
        cache_dir: Path,
        page_size: int = 50,
        timeout: int = 30,
    ):
        self.base_url = base_url.rstrip("/")
        self.all_jobs_path = "/" + all_jobs_path.strip("/") + "/"
        self.page_size = int(page_size)
        self.timeout = int(timeout)
        self.cache_dir = Path(cache_dir)
        self.list_cache = self.cache_dir / "listings"
        self.detail_cache = self.cache_dir / "details"
        self.list_cache.mkdir(parents=True, exist_ok=True)
        self.detail_cache.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/151.0 Safari/537.36 Edg/151.0"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.2",
                "Cache-Control": "no-cache",
            }
        )
        self._warmed = False

    def warmup(self):
        if self._warmed:
            return
        self._warmed = True
        try:
            self.session.get(self.base_url + "/", timeout=self.timeout)
        except Exception:
            pass

    def _get(self, url: str):
        self.warmup()
        last = None
        for delay in (0, 1, 2):
            if delay:
                time.sleep(delay)
            try:
                response = self.session.get(url, timeout=self.timeout, allow_redirects=True)
                response.raise_for_status()
                text = response.text or ""
                if len(text) < 300:
                    raise ValueError(f"HTML trop court ({len(text)} caractères)")
                return text, None
            except Exception as exc:
                last = f"{type(exc).__name__}: {exc}"
        return None, last

    def listing_url(self, offset: int = 0) -> str:
        base = urljoin(self.base_url + "/", self.all_jobs_path.lstrip("/"))
        if offset > 0:
            base = base.rstrip("/") + f"/{offset}/"
        sep = "&" if "?" in base else "?"
        return base + sep + "q=&sortColumn=referencedate&sortDirection=desc"

    def listing_html(self, offset: int = 0, use_cache: bool = True):
        cache = self.list_cache / f"offset_{offset}.html"
        text, error = self._get(self.listing_url(offset))
        if text:
            try:
                cache.write_text(text, encoding="utf-8")
            except Exception:
                pass
            return text, False, None
        if use_cache and cache.exists():
            try:
                return cache.read_text(encoding="utf-8"), True, error
            except Exception:
                pass
        return None, False, error

    def detail_html(self, url: str, external_id: str | None = None, use_cache: bool = True):
        key = clean_text(external_id) or hashlib.sha1(url.encode("utf-8")).hexdigest()[:24]
        cache = self.detail_cache / f"{key}.html"
        text, error = self._get(url)
        if text:
            try:
                cache.write_text(text, encoding="utf-8")
            except Exception:
                pass
            return text, False, None
        if use_cache and cache.exists():
            try:
                return cache.read_text(encoding="utf-8"), True, error
            except Exception:
                pass
        return None, False, error

    def absolute(self, href: str) -> str:
        return urljoin(self.base_url + "/", clean_text(href))


JOB_LINK_RE = re.compile(r"/job/[^?#]+/(\d+)/?", re.I)


def parse_total(html: str) -> int | None:
    text = clean_text(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
    patterns = (
        r"Results\s+\d+\s*[–-]\s*\d+\s+of\s+(\d+)",
        r"Results\s+\d+\s+of\s+(\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return int(match.group(1))
    return None


def parse_listing_rows(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, dict] = {}
    for anchor in soup.find_all("a", href=True):
        href = clean_text(anchor.get("href"))
        match = JOB_LINK_RE.search(urlparse(urljoin(base_url, href)).path)
        if not match:
            continue
        external_id = match.group(1)
        title = clean_text(anchor.get_text(" ", strip=True))
        if not title or title.lower() in {"apply now", "postuler", "view job"}:
            continue
        row = found.setdefault(
            external_id,
            {
                "external_id": external_id,
                "title": title,
                "url": urljoin(base_url, href),
                "category": "",
                "location": "",
                "seniority": "",
                "work_model": "",
            },
        )
        if len(title) > len(row.get("title") or ""):
            row["title"] = title

        tr = anchor.find_parent("tr")
        if tr:
            cells = [clean_text(td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]
            # Standard SuccessFactors jobs2web table: title, category, location, seniority, work model.
            if len(cells) >= 5:
                row["category"] = cells[-4]
                row["location"] = cells[-3]
                row["seniority"] = cells[-2]
                row["work_model"] = cells[-1]
            else:
                joined = clean_text(tr.get_text(" ", strip=True))
                loc = re.search(r"([A-Za-zÀ-ÿ0-9'’ .\-/]+,\s*BE)\b", joined)
                if loc:
                    row["location"] = clean_text(loc.group(1))
        if not row.get("location"):
            container = anchor.find_parent(["li", "div"])
            if container:
                joined = clean_text(container.get_text(" ", strip=True))
                loc = re.search(r"([A-Za-zÀ-ÿ0-9'’ .\-/]+,\s*BE)\b", joined)
                if loc:
                    row["location"] = clean_text(loc.group(1))
    return list(found.values())


def extract_jobposting_jsonld(soup: BeautifulSoup) -> dict:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text() or ""
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if isinstance(item, dict) and str(item.get("@type", "")).lower() == "jobposting":
                return item
            if isinstance(item, dict) and isinstance(item.get("@graph"), list):
                for node in item["@graph"]:
                    if isinstance(node, dict) and str(node.get("@type", "")).lower() == "jobposting":
                        return node
    return {}


def jsonld_location(payload: dict) -> str:
    loc = payload.get("jobLocation")
    if isinstance(loc, list):
        loc = loc[0] if loc else None
    if not isinstance(loc, dict):
        return ""
    address = loc.get("address")
    if not isinstance(address, dict):
        return ""
    parts = [address.get("addressLocality"), address.get("addressRegion"), address.get("addressCountry")]
    return ", ".join(clean_text(x) for x in parts if clean_text(x))
