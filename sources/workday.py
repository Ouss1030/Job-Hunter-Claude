"""
JOB HUNTER BELGIUM
GENERIC WORKDAY PUBLIC CAREERS CLIENT - VERSION 1.0

Small helper around the public Workday CXS endpoints used by employer career sites.
No authentication bypass or anti-bot circumvention is performed.
"""

from __future__ import annotations

import html as html_lib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup


DEFAULT_TIMEOUT = 30
DEFAULT_RETRIES = 3
DEFAULT_DELAYS = (1, 2, 4)


def clean_text(value) -> str:
    if value is None:
        return ""
    value = html_lib.unescape(str(value)).replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def strip_html(value) -> str:
    text = clean_text(value)
    if not text:
        return ""
    try:
        soup = BeautifulSoup(str(value), "html.parser")
        return clean_text(soup.get_text(" ", strip=True))
    except Exception:
        return text


def _first(mapping: dict, *keys):
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _path_external_id(path: str) -> str:
    value = clean_text(path).rstrip("/")
    match = re.search(r"_([0-9A-Za-z-]{4,})$", value)
    return match.group(1) if match else ""


@dataclass
class WorkdayClient:
    host: str
    tenant: str
    site: str
    public_locale: str = "en-US"
    cache_dir: Path | None = None
    timeout: int = DEFAULT_TIMEOUT

    def __post_init__(self):
        self.host = self.host.rstrip("/")
        self.base_cxs = f"{self.host}/wday/cxs/{self.tenant}/{self.site}"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/151.0 Safari/537.36 Edg/151.0"
                ),
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.2",
                "Content-Type": "application/json",
                "Origin": self.host,
                "Referer": f"{self.host}/{self.public_locale}/{self.site}",
            }
        )
        if self.cache_dir:
            Path(self.cache_dir).mkdir(parents=True, exist_ok=True)

    def _cache_path(self, prefix: str, key: str) -> Path | None:
        if not self.cache_dir:
            return None
        safe = re.sub(r"[^0-9A-Za-z._-]+", "_", clean_text(key))[:120] or "root"
        return Path(self.cache_dir) / f"{prefix}_{safe}.json"

    def _request_json(self, method: str, url: str, payload: dict | None = None):
        last_error = None
        for attempt in range(DEFAULT_RETRIES):
            try:
                if method.upper() == "POST":
                    response = self.session.post(url, json=payload or {}, timeout=self.timeout)
                else:
                    response = self.session.get(url, timeout=self.timeout)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("Réponse Workday JSON inattendue")
                return data, None
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < DEFAULT_RETRIES - 1:
                    time.sleep(DEFAULT_DELAYS[attempt])
        return None, last_error

    def search(
        self,
        search_text: str = "",
        applied_facets: dict | None = None,
        offset: int = 0,
        limit: int = 20,
        use_cache: bool = False,
        omit_applied_facets: bool = False,
    ) -> tuple[dict | None, bool, str | None]:
        """Read a public Workday listing page.

        Most Workday tenants accept ``appliedFacets`` even when it is empty.
        A minority rejects that field with HTTP 422. Callers can force a
        compact payload with ``omit_applied_facets=True``; empty-facet 422s
        are also retried once automatically without that member.
        """
        facets = applied_facets or {}
        payload = {
            "limit": int(limit),
            "offset": int(offset),
            "searchText": clean_text(search_text),
        }
        if not omit_applied_facets:
            payload["appliedFacets"] = facets

        mode = "no_facets_field" if omit_applied_facets else "standard"
        cache_key = (
            f"{mode}_{clean_text(search_text)}_{offset}_"
            f"{json.dumps(facets, sort_keys=True)}"
        )
        cache = self._cache_path("search", cache_key)
        if use_cache and cache and cache.exists():
            try:
                return json.loads(cache.read_text(encoding="utf-8")), True, None
            except Exception:
                pass

        data, error = self._request_json("POST", f"{self.base_cxs}/jobs", payload=payload)

        # Compatibility fallback. Never remove a NON-empty facet selection:
        # doing so would silently turn a location-filtered request into a
        # global request.
        if (
            not data
            and not omit_applied_facets
            and not facets
            and error
            and "422" in error
        ):
            compact_payload = {
                "limit": int(limit),
                "offset": int(offset),
                "searchText": clean_text(search_text),
            }
            data2, error2 = self._request_json(
                "POST", f"{self.base_cxs}/jobs", payload=compact_payload
            )
            if data2:
                data, error = data2, None
            elif error2:
                error = f"{error} | retry sans appliedFacets: {error2}"

        if data and cache:
            try:
                cache.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
        return data, False, error


    def detail(self, external_path: str, use_cache: bool = True):
        path = clean_text(external_path)
        if not path.startswith("/"):
            path = "/" + path
        external_id = _path_external_id(path) or quote(path, safe="")[-50:]
        cache = self._cache_path("detail", external_id)
        if use_cache and cache and cache.exists():
            try:
                return json.loads(cache.read_text(encoding="utf-8")), True, None
            except Exception:
                pass

        data, error = self._request_json("GET", f"{self.base_cxs}{path}")
        if data and cache:
            try:
                cache.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
        return data, False, error

    def public_url(self, external_path: str) -> str:
        path = clean_text(external_path)
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.host}/{self.public_locale}/{self.site}{path}"


def posting_rows(payload: dict | None) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    rows = payload.get("jobPostings") or payload.get("jobs") or payload.get("items") or []
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    return []


def posting_total(payload: dict | None) -> int:
    if not isinstance(payload, dict):
        return 0
    for key in ("total", "totalResults", "totalCount"):
        try:
            return int(payload.get(key) or 0)
        except Exception:
            pass
    return len(posting_rows(payload))


def posting_external_path(row: dict) -> str:
    return clean_text(_first(row, "externalPath", "path", "jobPath", "url"))


def posting_title(row: dict) -> str:
    return clean_text(_first(row, "title", "jobTitle", "descriptor"))


def posting_location(row: dict) -> str:
    values = []
    for key in ("locationsText", "location", "primaryLocation", "locations"):
        value = row.get(key)
        if isinstance(value, list):
            values.extend(clean_text(item.get("descriptor") if isinstance(item, dict) else item) for item in value)
        else:
            values.append(clean_text(value))
    return clean_text(" | ".join(value for value in values if value))


def posting_date(row: dict) -> str:
    return clean_text(_first(row, "postedOn", "datePosted", "startDate"))


def posting_id(row: dict) -> str:
    return clean_text(_first(row, "jobReqId", "jobRequisitionId", "jobPostingId", "id")) or _path_external_id(posting_external_path(row))


def discover_facet_values(payload: dict | None, wanted_terms: tuple[str, ...]) -> dict[str, list[str]]:
    """Return {facetParameter: [value ids]} for values whose descriptor matches wanted terms."""
    if not isinstance(payload, dict):
        return {}
    wanted = tuple(clean_text(term).lower() for term in wanted_terms if clean_text(term))
    matches: dict[str, list[str]] = {}
    facets = payload.get("facets") or []
    if not isinstance(facets, list):
        return matches
    for facet in facets:
        if not isinstance(facet, dict):
            continue
        parameter = clean_text(
            _first(facet, "facetParameter", "parameter", "id", "name", "facetId")
        )
        if not parameter:
            continue
        values = facet.get("values") or facet.get("facetValues") or []
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, dict):
                continue
            descriptor = clean_text(_first(value, "descriptor", "label", "text", "name"))
            value_id = clean_text(_first(value, "id", "value", "facetValue", "code"))
            low = descriptor.lower()
            if descriptor and value_id and any(term in low for term in wanted):
                matches.setdefault(parameter, [])
                if value_id not in matches[parameter]:
                    matches[parameter].append(value_id)
    return matches


def parse_workday_detail(payload: dict | None, fallback: dict | None = None) -> dict:
    fallback = fallback or {}
    if not isinstance(payload, dict):
        return {
            "success": False,
            "matching_text": "",
            "matching_text_length": 0,
            "structured": dict(fallback),
            "error": "Réponse Workday détail vide ou invalide.",
        }

    info = payload.get("jobPostingInfo") if isinstance(payload.get("jobPostingInfo"), dict) else payload
    title = clean_text(_first(info, "title", "jobTitle") or fallback.get("title"))
    description = strip_html(
        _first(info, "jobDescription", "jobDescriptionHtml", "description", "jobDetails")
    )
    location = clean_text(
        _first(info, "locationsText", "location", "primaryLocation") or fallback.get("location")
    )
    if isinstance(info.get("additionalLocations"), list):
        additional = [clean_text(x.get("descriptor") if isinstance(x, dict) else x) for x in info["additionalLocations"]]
        location = clean_text(" | ".join([location] + [x for x in additional if x]))
    contract = clean_text(_first(info, "timeType", "employmentType"))
    remote = clean_text(_first(info, "remoteType"))
    if remote and remote.lower() not in contract.lower():
        contract = clean_text(" | ".join(x for x in (contract, remote) if x))
    posted = clean_text(_first(info, "postedOn", "datePosted", "startDate") or fallback.get("date_published"))
    req_id = clean_text(
        _first(info, "jobReqId", "jobRequisitionId", "jobPostingId", "id") or fallback.get("external_id")
    )
    external_path = clean_text(_first(info, "externalPath") or fallback.get("external_path"))

    structured = {
        "external_id": req_id or _path_external_id(external_path),
        "external_path": external_path,
        "title": title,
        "location": location,
        "contract_type": contract,
        "date_published": posted,
        "job_requisition_id": req_id,
    }
    success = bool(title and len(description) >= 120)
    return {
        "success": success,
        "matching_text": description,
        "matching_text_length": len(description),
        "structured": structured,
        "error": None if success else f"Fiche Workday incomplète (titre={bool(title)}, description={len(description)} car.)",
    }
