"""
JOB HUNTER BELGIUM
PUBLIC SEARCH INDEX - VERSION 1.1

Small, conservative discovery helper for public employer pages that are
indexed by a search engine but temporarily unreachable from the local runtime.

The engine uses Bing's public RSS search representation when available and a
normal public result-page fallback otherwise.  It is intentionally discovery
only: callers must still attempt to refresh/read the employer's original page
before treating a result as a fully enriched vacancy.
"""
from __future__ import annotations

import base64
import hashlib
import html as html_lib
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests
from bs4 import BeautifulSoup


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0 Safari/537.36"
    ),
    "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.3",
}


def clean_text(value) -> str:
    if value is None:
        return ""
    text = html_lib.unescape(str(value)).replace("\xa0", " ")
    if "<" in text and ">" in text:
        text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()




def _decode_bing_u(value: str) -> str:
    """Decode Bing's public redirect target when it is carried in ``u=``.

    Bing commonly prefixes the URL-safe base64 payload with ``a1``.  Some
    result surfaces instead expose a normal percent-encoded absolute URL.
    The helper is deliberately conservative: it only returns absolute http(s)
    targets and never follows the redirect.
    """
    value = html_lib.unescape(str(value or "")).strip()
    if not value:
        return ""
    value = unquote(value)
    if value.startswith(("http://", "https://")):
        return value

    candidates = [value]
    if len(value) > 2 and value[:2].lower() in {"a1", "a2"}:
        candidates.insert(0, value[2:])

    for candidate in candidates:
        token = candidate.strip()
        if not token:
            continue
        token += "=" * (-len(token) % 4)
        try:
            decoded = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8", errors="ignore").strip()
        except Exception:
            continue
        decoded = unquote(decoded)
        if decoded.startswith(("http://", "https://")):
            return decoded
    return ""


def normalize_result_url(value: str) -> str:
    """Return the public destination URL for a search result when possible.

    In particular, Bing RSS/HTML may emit ``bing.com/ck/a`` tracking links
    instead of the indexed URL.  We decode their public ``u`` target locally
    so employer-domain filters can operate on the real destination.
    """
    raw = html_lib.unescape(str(value or "")).strip()
    if not raw:
        return ""
    raw = raw.replace("&amp;", "&")
    parsed = urlparse(raw)
    host = (parsed.netloc or "").lower()
    if host not in {"bing.com", "www.bing.com"} and not host.endswith(".bing.com"):
        return raw

    params = parse_qs(parsed.query, keep_blank_values=True)
    for key in ("u", "url", "r", "target"):
        for candidate in params.get(key, []):
            decoded = _decode_bing_u(candidate) if key == "u" else unquote(candidate)
            if decoded.startswith(("http://", "https://")):
                return decoded

    # Defensive fallback for unusual redirect strings where the target was not
    # parsed cleanly into the query mapping.
    match = re.search(r"[?&]u=([^&]+)", raw, re.I)
    if match:
        decoded = _decode_bing_u(match.group(1))
        if decoded:
            return decoded
    return raw


def _hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8", errors="ignore")).hexdigest()[:24]


@dataclass(frozen=True)
class SearchIndexResult:
    title: str
    url: str
    snippet: str = ""
    published: str = ""
    query: str = ""
    engine: str = "bing"
    raw_url: str = ""


class PublicSearchIndex:
    def __init__(
        self,
        cache_dir: Path,
        timeout: int = 15,
        max_retries: int = 2,
        query_delay: float = 0.25,
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = int(timeout)
        self.max_retries = int(max_retries)
        self.query_delay = float(query_delay)
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def _cache_path(self, query: str, mode: str) -> Path:
        return self.cache_dir / f"{mode}_{_hash(query)}.txt"

    def _get(self, url: str, query: str, mode: str, use_cache: bool):
        cache = self._cache_path(query, mode)
        last_error = None
        for attempt in range(max(1, self.max_retries)):
            try:
                response = self.session.get(url, timeout=self.timeout, allow_redirects=True)
                response.raise_for_status()
                text = response.text or ""
                if len(text) < 80:
                    raise ValueError(f"réponse trop courte ({len(text)} caractères)")
                try:
                    cache.write_text(text, encoding="utf-8")
                except Exception:
                    pass
                return text, False, None
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < self.max_retries - 1:
                    time.sleep(1 + attempt)
        if use_cache and cache.exists():
            try:
                return cache.read_text(encoding="utf-8", errors="ignore"), True, last_error
            except Exception:
                pass
        return "", False, last_error

    def _parse_rss(self, text: str, query: str) -> list[SearchIndexResult]:
        results: list[SearchIndexResult] = []
        try:
            root = ET.fromstring(text)
        except Exception:
            return results
        for item in root.findall(".//item"):
            title = clean_text(item.findtext("title"))
            raw_url = clean_text(item.findtext("link"))
            url = normalize_result_url(raw_url)
            snippet = clean_text(item.findtext("description"))
            published = clean_text(item.findtext("pubDate"))
            if url:
                results.append(SearchIndexResult(title, url, snippet, published, query, "bing-rss", raw_url))
        return results

    def _parse_html(self, text: str, query: str) -> list[SearchIndexResult]:
        soup = BeautifulSoup(text or "", "html.parser")
        results: list[SearchIndexResult] = []
        for node in soup.select("li.b_algo"):
            link = node.select_one("h2 a")
            if not link:
                continue
            raw_url = clean_text(link.get("href"))
            url = normalize_result_url(raw_url)
            title = clean_text(link.get_text(" ", strip=True))
            snippet_node = node.select_one(".b_caption p") or node.select_one("p")
            snippet = clean_text(snippet_node.get_text(" ", strip=True)) if snippet_node else ""
            if url:
                results.append(SearchIndexResult(title, url, snippet, "", query, "bing-html", raw_url))
        return results

    def search(self, query: str, use_cache: bool = True) -> tuple[list[SearchIndexResult], dict]:
        query = clean_text(query)
        meta = {"query": query, "mode": "", "from_cache": False, "error": None}
        if not query:
            return [], {**meta, "error": "requête vide"}

        rss_url = f"https://www.bing.com/search?q={quote_plus(query)}&format=rss"
        text, from_cache, error = self._get(rss_url, query, "rss", use_cache)
        results = self._parse_rss(text, query) if text else []
        if results:
            meta.update({"mode": "bing-rss", "from_cache": from_cache, "error": error})
            return results, meta

        html_url = f"https://www.bing.com/search?q={quote_plus(query)}"
        text2, from_cache2, error2 = self._get(html_url, query, "html", use_cache)
        results = self._parse_html(text2, query) if text2 else []
        meta.update({
            "mode": "bing-html" if results else "failed",
            "from_cache": from_cache2,
            "error": error2 or error,
        })
        return results, meta

    def search_many(self, queries: Iterable[str], use_cache: bool = True):
        queries = tuple(queries)
        merged: dict[str, SearchIndexResult] = {}
        metas: list[dict] = []
        for index, query in enumerate(queries):
            rows, meta = self.search(query, use_cache=use_cache)
            metas.append(meta)
            for row in rows:
                key = row.url.rstrip("/")
                existing = merged.get(key)
                if existing is None or len(row.snippet) > len(existing.snippet):
                    merged[key] = row
            if self.query_delay and index < len(queries) - 1:
                time.sleep(self.query_delay)
        return list(merged.values()), metas
