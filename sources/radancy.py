"""
JOB HUNTER BELGIUM
RADANCY / TALENTBREW PUBLIC CAREER ENGINE - VERSION 1.0

Generic reader for public employer career sites powered by Radancy/TalentBrew.
Designed for sites such as jobs.sanofi.com and jobs.baxter.com.

The engine only reads public listing/detail pages. It does not bypass login,
anti-bot or application protections.
"""
from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


@dataclass(frozen=True)
class RadancySite:
    key: str
    company: str
    base_url: str
    listing_urls: tuple[str, ...]
    cache_slug: str
    country_terms: tuple[str, ...] = ("belgium", "belgique")
    location_terms: tuple[str, ...] = ()
    language_path: str = "en"


PROJECT_ROOT = Path(__file__).resolve().parent.parent
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0 Safari/537.36"
    ),
    "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.5",
}

CLOSED_MARKERS = (
    "job is no longer available",
    "position is no longer available",
    "this job has been filled",
    "job you are trying to access is no longer available",
    "page not found",
    "404 not found",
)


def clean_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        value = " ".join(str(x) for x in value if x is not None)
    text = html_lib.unescape(str(value)).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _norm(value) -> str:
    return clean_text(value).lower().replace("’", "'")


def _cache_dir(site: RadancySite) -> Path:
    return PROJECT_ROOT / "logs" / f"{site.cache_slug}_radancy_cache"


def _cache_path(site: RadancySite, url: str, prefix: str = "detail") -> Path:
    digest = hashlib.sha1(url.encode("utf-8", errors="ignore")).hexdigest()[:18]
    return _cache_dir(site) / f"{prefix}_{digest}.html"


def request_html(site: RadancySite, url: str, use_cache: bool = True, prefix: str = "detail") -> tuple[str, bool, str | None, int | None]:
    cache_path = _cache_path(site, url, prefix=prefix)
    if use_cache and cache_path.exists():
        try:
            return cache_path.read_text(encoding="utf-8", errors="ignore"), True, None, 200
        except Exception:
            pass
    try:
        response = requests.get(url, headers=HEADERS, timeout=25, allow_redirects=True)
        status = int(response.status_code)
        if status == 404:
            return "", False, "HTTP 404", status
        response.raise_for_status()
        html = response.text or ""
        if html:
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(html, encoding="utf-8")
            except Exception:
                pass
        return html, False, None, status
    except requests.HTTPError as exc:
        return "", False, f"HTTPError: {exc}", getattr(getattr(exc, "response", None), "status_code", None)
    except Exception as exc:
        return "", False, f"{type(exc).__name__}: {exc}", None


def _job_url_info(url: str) -> tuple[str, str]:
    """Return city slug and numeric TalentBrew/Radancy job id."""
    parts = [p for p in urlparse(url).path.rstrip("/").split("/") if p]
    try:
        idx = next(i for i, part in enumerate(parts) if part.lower() == "job")
    except StopIteration:
        return "", ""
    city = parts[idx + 1].lower() if len(parts) > idx + 1 else ""
    numeric_id = parts[-1] if parts and parts[-1].isdigit() else ""
    return city, numeric_id


def _listing_scope(html: str, site: RadancySite) -> tuple[int | None, str]:
    text = clean_text(BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True))
    for country in site.country_terms:
        patterns = (
            rf"\b(\d+)\s+jobs?\s+in\s+{re.escape(country)}\b",
            rf"\b(\d+)\s+result\(s\)\s+found\s+for\s+{re.escape(country)}\b",
        )
        for pattern in patterns:
            m = re.search(pattern, text, re.I)
            if m:
                return int(m.group(1)), country
    return None, ""


def fetch_listing(site: RadancySite, use_cache: bool = True) -> tuple[str, str, bool, list[str], int | None, str]:
    errors: list[str] = []
    for url in site.listing_urls:
        html, from_cache, error, status = request_html(site, url, use_cache=use_cache, prefix="listing")
        if not html:
            errors.append(f"{url}: {error or status or 'réponse vide'}")
            continue
        announced, scope = _listing_scope(html, site)
        # Some Radancy pages can preserve a country filter without a stable heading.
        # Accept if the final listing visibly contains Belgium on multiple job cards.
        low = _norm(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
        country_signal = any(low.count(term.lower()) >= 2 for term in site.country_terms)
        if not scope and not country_signal:
            errors.append(f"{url}: page non confirmée Belgique")
            continue
        return html, url, from_cache, errors, announced, scope or "Belgium"
    return "", "", False, errors, None, ""


def _nearest_job_card(anchor, listing_url: str, max_chars: int = 2400):
    current = anchor
    for _ in range(8):
        parent = getattr(current, "parent", None)
        if parent is None:
            break
        current = parent
        text = clean_text(current.get_text(" ", strip=True))
        if len(text) > max_chars:
            break
        urls = set()
        for a in current.find_all("a", href=True):
            abs_url = urljoin(listing_url, clean_text(a.get("href")))
            _, jid = _job_url_info(abs_url)
            if jid:
                urls.add(abs_url.rstrip("/"))
        if len(urls) == 1 and ("location" in text.lower() or "job category" in text.lower() or "category:" in text.lower()):
            return current
    return None


def extract_listing_rows(site: RadancySite, html: str, listing_url: str) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    found: dict[str, dict] = {}
    host = urlparse(site.base_url).netloc.lower()
    for anchor in soup.find_all("a", href=True):
        href = clean_text(anchor.get("href"))
        if not href:
            continue
        absolute = urljoin(listing_url or site.base_url, href)
        if urlparse(absolute).netloc.lower() != host:
            continue
        city_slug, jid = _job_url_info(absolute)
        if not jid:
            continue
        card = _nearest_job_card(anchor, listing_url)
        raw_anchor = clean_text(anchor.get_text(" ", strip=True))
        card_text = clean_text(card.get_text(" ", strip=True) if card else raw_anchor)
        title = raw_anchor
        # Many Radancy cards put title + Location + Category inside the anchor.
        title = re.split(r"\s+Location\s*:\s*", title, maxsplit=1, flags=re.I)[0]
        title = re.split(r"\s+Req\s*#", title, maxsplit=1, flags=re.I)[0]
        title = clean_text(title)
        if not title or title.lower() in {"apply now", "save job", "view all of our available opportunities"}:
            continue

        m_loc = re.search(r"\bLocation\s*:\s*(.+?)(?=\s+Category\s*:|\s+Job Category\b|\s+Date posted\b|$)", card_text, re.I)
        if not m_loc:
            m_loc = re.search(r"\bLocation\s+(.+?)(?=\s+Job Category\b|\s+Date posted\b|$)", card_text, re.I)
        location = clean_text(m_loc.group(1)) if m_loc else ""
        # Hard guard: only cards explicitly located in Belgium survive.
        card_low = _norm(card_text + " " + location)
        allowed_location_terms = tuple(site.country_terms) + tuple(site.location_terms)
        if not any(_norm(term) in card_low for term in allowed_location_terms):
            continue

        m_cat = re.search(r"\b(?:Job\s+)?Category\s*:?\s*(.+?)(?=\s+Date posted\b|\s+Save\b|$)", card_text, re.I)
        category = clean_text(m_cat.group(1)) if m_cat else ""
        m_date = re.search(r"\bDate posted\s+([0-9./-]{6,12}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})", card_text, re.I)
        date_published = clean_text(m_date.group(1)) if m_date else ""
        key = absolute.rstrip("/")
        found[key] = {
            "external_id": jid,
            "title": title,
            "location": location,
            "category": category,
            "date_published": date_published,
            "url": absolute,
            "city_slug": city_slug,
        }
    return list(found.values())


def _extract_jobposting_jsonld(soup: BeautifulSoup) -> dict:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop(0)
            if isinstance(item, list):
                stack.extend(item)
                continue
            if not isinstance(item, dict):
                continue
            typ = item.get("@type")
            if typ == "JobPosting" or (isinstance(typ, list) and "JobPosting" in typ):
                return item
            graph = item.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)
    return {}


def _jsonld_location(data: dict) -> str:
    loc = data.get("jobLocation")
    if isinstance(loc, list):
        loc = loc[0] if loc else None
    if not isinstance(loc, dict):
        return ""
    address = loc.get("address")
    if isinstance(address, dict):
        parts = [address.get("addressLocality"), address.get("addressRegion"), address.get("addressCountry")]
        return clean_text(", ".join(clean_text(p) for p in parts if clean_text(p)))
    return clean_text(loc.get("name"))


def _html_to_text(fragment: str) -> str:
    return clean_text(BeautifulSoup(fragment or "", "html.parser").get_text(" ", strip=True))


def _slice_description(soup: BeautifulSoup, fallback_title: str = "") -> str:
    for selector in ("[itemprop='description']", ".job-description", ".jobDescription", ".job-description-content", "#job-description"):
        node = soup.select_one(selector)
        if node:
            text = clean_text(node.get_text(" ", strip=True))
            if len(text) >= 220:
                return text
    lines = [clean_text(x) for x in soup.get_text("\n", strip=True).splitlines() if clean_text(x)]
    text = "\n".join(lines)
    starts = [
        r"(?:^|\n)#?\s*About the job(?:\n|$)",
        r"(?:^|\n)#?\s*Job Details(?:\n|$)",
        r"(?:^|\n)This is where\s+your work makes a difference\.(?:\n|$)",
    ]
    start_pos = None
    for pattern in starts:
        m = re.search(pattern, text, re.I)
        if m:
            start_pos = m.start()
            break
    if start_pos is None and fallback_title:
        # Use the last occurrence of title because job pages often repeat it before description.
        positions = [m.end() for m in re.finditer(re.escape(fallback_title), text, re.I)]
        if positions:
            start_pos = positions[-1]
    body = text[start_pos:] if start_pos is not None else text
    stop = re.search(r"\n(?:Why choose us\?|Equal Employment Opportunity|Reasonable Accommodations|Hear From Our Employees|Related Content|Find out more about this location)\b", body, re.I)
    if stop:
        body = body[: stop.start()]
    return clean_text(body)


def parse_detail(site: RadancySite, html: str, url: str, fallback: dict | None = None, from_cache: bool = False) -> dict:
    fallback = dict(fallback or {})
    soup = BeautifulSoup(html or "", "html.parser")
    full_text = clean_text(soup.get_text(" ", strip=True))
    low = _norm(full_text)
    jsonld = _extract_jobposting_jsonld(soup)

    title = clean_text(jsonld.get("title")) or clean_text(fallback.get("title"))
    if not title:
        h1 = soup.find("h1")
        title = clean_text(h1.get_text(" ", strip=True) if h1 else "")

    location = _jsonld_location(jsonld) or clean_text(fallback.get("location"))
    if not location:
        m = re.search(r"\bLocation\s*:?\s*(.+?)(?=\s+(?:Job Category|Category|Date posted|Salary Range|Grade|Hiring Manager)\b|$)", full_text, re.I)
        if m:
            location = clean_text(m.group(1))

    employment = jsonld.get("employmentType")
    if isinstance(employment, list):
        employment = ", ".join(clean_text(x) for x in employment)
    contract_type = clean_text(employment)
    date_published = clean_text(jsonld.get("datePosted")) or clean_text(fallback.get("date_published"))

    _, jid = _job_url_info(url)
    external_id = clean_text(fallback.get("external_id") or jid)
    req = ""
    for pattern in (r"\bReq\s*#\s*([A-Za-z0-9-]+)", r"\bRequisition(?:\s+ID)?\s*:?\s*([A-Za-z0-9-]+)"):
        m = re.search(pattern, full_text, re.I)
        if m:
            req = clean_text(m.group(1))
            break

    description = _html_to_text(clean_text(jsonld.get("description")))
    if len(description) < 220:
        description = _slice_description(soup, fallback_title=title)

    closed = any(marker in low for marker in CLOSED_MARKERS)
    structured = {
        **fallback,
        "external_id": external_id,
        "radancy_job_id": external_id,
        "requisition_id": req,
        "title": title,
        "company": site.company,
        "location": location,
        "contract_type": contract_type,
        "date_published": date_published,
        "url": url,
        "closed": closed,
    }
    if closed:
        return {"success": False, "closed": True, "matching_text": "", "matching_text_length": 0, "structured": structured, "from_cache": from_cache, "error": f"{site.company}: offre clôturée."}
    if len(description) < 220:
        return {"success": False, "closed": False, "matching_text": description, "matching_text_length": len(description), "structured": structured, "from_cache": from_cache, "error": f"{site.company}: description trop courte ({len(description)} caractères)."}
    return {"success": True, "closed": False, "matching_text": description, "matching_text_length": len(description), "structured": structured, "from_cache": from_cache, "error": None}


def get_job_detail(site: RadancySite, url: str, external_id: str | None = None, use_cache: bool = True, fallback: dict | None = None) -> dict:
    fallback = dict(fallback or {})
    if external_id and not fallback.get("external_id"):
        fallback["external_id"] = external_id
    html, from_cache, error, status = request_html(site, url, use_cache=use_cache, prefix="detail")
    if not html:
        return {
            "success": False,
            "closed": status == 404,
            "matching_text": "",
            "matching_text_length": 0,
            "structured": {**fallback, "external_id": external_id or fallback.get("external_id"), "url": url, "closed": status == 404},
            "from_cache": from_cache,
            "error": f"{site.company}: {'offre clôturée / HTTP 404' if status == 404 else (error or 'lecture impossible')}",
        }
    return parse_detail(site, html, url, fallback=fallback, from_cache=from_cache)
