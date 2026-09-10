"""
JOB HUNTER BELGIUM
PHENOM PUBLIC CAREER CLIENT - VERSION 1.0

Small reusable client for public Phenom career sites.
Uses the public /widgets endpoint exposed by the branded careers domain.
No authentication bypass or anti-bot circumvention is used.
"""

from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path
from typing import Any

import requests


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0 Safari/537.36 Edg/151.0"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.2",
    "Content-Type": "application/json",
}


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip()


def _decode_play_session_csrf(cookie_value: str) -> str:
    """Best-effort extraction of csrfToken from a JWT-like PLAY_SESSION cookie."""
    value = clean_text(cookie_value)
    parts = value.split(".")
    if len(parts) < 2:
        return ""
    try:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")).decode("utf-8"))
    except Exception:
        return ""

    if isinstance(data, dict):
        direct = clean_text(data.get("csrfToken"))
        if direct:
            return direct
        nested = data.get("data")
        if isinstance(nested, dict):
            return clean_text(nested.get("csrfToken"))
    return ""


def _find_string(obj: Any, keys: tuple[str, ...]) -> str:
    if isinstance(obj, dict):
        for key in keys:
            value = obj.get(key)
            if isinstance(value, (str, int, float)) and clean_text(value):
                return clean_text(value)
        for value in obj.values():
            found = _find_string(value, keys)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_string(value, keys)
            if found:
                return found
    return ""


def phenom_result_block(payload: dict | None) -> dict:
    if not isinstance(payload, dict):
        return {}
    for key in ("refineSearch", "searchResults", "jobSearch"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    # Some deployments wrap the widget result once more.
    for value in payload.values():
        if isinstance(value, dict):
            for key in ("refineSearch", "searchResults", "jobSearch"):
                nested = value.get(key)
                if isinstance(nested, dict):
                    return nested
    return payload


def phenom_jobs(payload: dict | None) -> list[dict]:
    block = phenom_result_block(payload)
    candidates = []
    data = block.get("data") if isinstance(block, dict) else None
    if isinstance(data, dict):
        for key in ("jobs", "jobResults", "results"):
            value = data.get(key)
            if isinstance(value, list):
                candidates = value
                break
    if not candidates and isinstance(block, dict):
        for key in ("jobs", "jobResults", "results"):
            value = block.get(key)
            if isinstance(value, list):
                candidates = value
                break
    return [item for item in candidates if isinstance(item, dict)]


def phenom_total(payload: dict | None) -> int:
    block = phenom_result_block(payload)
    if not isinstance(block, dict):
        return 0
    for key in ("totalHits", "total", "totalCount", "count"):
        value = block.get(key)
        try:
            if value is not None:
                return int(value)
        except Exception:
            pass
    data = block.get("data")
    if isinstance(data, dict):
        for key in ("totalHits", "total", "totalCount", "count"):
            value = data.get(key)
            try:
                if value is not None:
                    return int(value)
            except Exception:
                pass
    return len(phenom_jobs(payload))


class PhenomClient:
    def __init__(
        self,
        host: str,
        locale_path: str = "/global/en",
        lang: str = "en_global",
        country: str = "global",
        ref_num: str = "",
        page_id: str = "page20",
        cache_dir: str | Path | None = None,
        timeout: int = 30,
    ):
        self.host = host.rstrip("/")
        self.locale_path = "/" + locale_path.strip("/")
        self.lang = lang
        self.country = country
        self.ref_num = clean_text(ref_num)
        self.page_id = clean_text(page_id) or "page20"
        self.timeout = int(timeout)
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self._warmed = False
        self._csrf = ""

    @property
    def search_page_url(self) -> str:
        return f"{self.host}{self.locale_path}/search-results"

    @property
    def widgets_url(self) -> str:
        return f"{self.host}/widgets"

    def warmup(self) -> tuple[bool, str | None]:
        if self._warmed:
            return True, None
        try:
            response = self.session.get(
                self.search_page_url,
                timeout=self.timeout,
                headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
            )
            response.raise_for_status()
            text = response.text or ""
            if not self.ref_num:
                for pattern in (
                    r'"refNum"\s*:\s*"([^"]+)"',
                    r'"clientName"\s*:\s*"([^"]+)"',
                ):
                    match = re.search(pattern, text, flags=re.I)
                    if match:
                        self.ref_num = clean_text(match.group(1))
                        break
            match_page = re.search(r'"pageId"\s*:\s*"([^"]+)"', text, flags=re.I)
            if match_page:
                self.page_id = clean_text(match_page.group(1)) or self.page_id

            cookie = self.session.cookies.get("PLAY_SESSION") or ""
            self._csrf = _decode_play_session_csrf(cookie)
            if not self._csrf:
                match_csrf = re.search(r'"csrfToken"\s*:\s*"([^"]+)"', text, flags=re.I)
                if match_csrf:
                    self._csrf = clean_text(match_csrf.group(1))
            self._warmed = True
            return True, None
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    def _payload(
        self,
        keywords: str,
        selected_fields: dict | None,
        offset: int,
        size: int,
    ) -> dict:
        return {
            "lang": self.lang,
            "deviceType": "desktop",
            "country": self.country,
            "pageName": "search-results",
            "pageType": "search-results",
            "size": int(size),
            "from": int(offset),
            "jobs": True,
            "counts": True,
            "all_fields": [
                "category", "country", "state", "city", "type", "jobFamily"
            ],
            "clearAll": False,
            "jdsource": "facets",
            "isSliderEnable": False,
            "pageId": self.page_id,
            "siteType": "external",
            "keywords": clean_text(keywords),
            "global": True,
            "selected_fields": selected_fields or {},
            "sort": {"order": "desc", "field": "postedDate"},
            "locationData": {},
            "refNum": self.ref_num,
            "ddoKey": "refineSearch",
        }

    def search(
        self,
        keywords: str = "",
        selected_fields: dict | None = None,
        offset: int = 0,
        size: int = 50,
        retries: int = 3,
    ) -> tuple[dict | None, str | None]:
        self.warmup()
        headers = {"Referer": self.search_page_url}
        if self._csrf:
            headers["x-csrf-token"] = self._csrf

        last_error = None
        for attempt in range(max(1, retries)):
            try:
                response = self.session.post(
                    self.widgets_url,
                    json=self._payload(keywords, selected_fields, offset, size),
                    timeout=self.timeout,
                    headers=headers,
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("réponse Phenom JSON inattendue")
                return payload, None
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < retries - 1:
                    time.sleep(1.0 + attempt)
        return None, last_error

    def public_job_url(self, job: dict) -> str:
        for key in ("jobUrl", "jobDetailUrl", "url", "externalUrl"):
            value = clean_text(job.get(key))
            if value:
                if value.startswith("http://") or value.startswith("https://"):
                    return value
                return self.host + (value if value.startswith("/") else "/" + value)

        seq = _find_string(job, ("jobSeqNo", "jobId", "reqId"))
        title = clean_text(job.get("title")) or "job"
        slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-")
        if seq:
            return f"{self.host}{self.locale_path}/job/{seq}/{slug}"
        return ""


def job_title(row: dict) -> str:
    return _find_string(row, ("title", "jobTitle", "name"))


def job_external_id(row: dict) -> str:
    return _find_string(row, ("jobSeqNo", "reqId", "jobId", "id"))


def job_location(row: dict) -> str:
    direct = _find_string(row, ("location", "formattedLocation", "locationName"))
    if direct:
        return direct
    parts = []
    for key in ("city", "state", "country"):
        value = clean_text(row.get(key))
        if value and value not in parts:
            parts.append(value)
    return ", ".join(parts)


def job_posted_date(row: dict) -> str:
    return _find_string(row, ("postedDate", "datePosted", "postedOn", "date"))


def job_contract(row: dict) -> str:
    return _find_string(row, ("type", "employmentType", "jobType"))


def job_teaser(row: dict) -> str:
    return _find_string(row, ("descriptionTeaser", "teaser", "shortDescription", "description"))
