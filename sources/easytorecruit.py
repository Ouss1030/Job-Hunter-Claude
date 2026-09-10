"""
JOB HUNTER BELGIUM
GENERIC EASYTORECRUIT PUBLIC API CLIENT - VERSION 1.0

Reusable client for HR-Technologies EasyToRecruit public job sites.

The documented public API requires a tenant-specific ``X-Client-Uuid`` header.
This module never guesses/bruteforces UUIDs. It can use:
  1) an explicitly configured public UUID;
  2) an environment variable;
  3) a previously validated local cache;
  4) UUID values visibly exposed by the tenant's public frontend HTML/JS.

No authenticated candidate endpoints are used for collection.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


API_BASE_DEFAULT = "https://api.hr-technologies.com/v1"
UUID_RE = re.compile(
    r"(?i)(?<![0-9a-f])([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?![0-9a-f])"
)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0 Safari/537.36 Edg/151.0"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.2",
}


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        value = " ".join(str(v) for v in value if v is not None)
    return re.sub(r"\s+", " ", html_lib.unescape(str(value)).replace("\xa0", " ")).strip()


def html_to_text(value: Any) -> str:
    raw = "" if value is None else str(value)
    if not raw:
        return ""
    try:
        return clean_text(BeautifulSoup(html_lib.unescape(raw), "html.parser").get_text(" ", strip=True))
    except Exception:
        return clean_text(raw)


def vacancy_text(item: dict) -> str:
    parts: list[str] = []
    for field_name in (
        "description", "short_description", "profile", "offer", "postcustom1",
        "contact", "company",
    ):
        text = html_to_text(item.get(field_name))
        if text and text not in parts:
            parts.append(text)
    return clean_text(" ".join(parts))


def contract_summary(item: dict) -> str:
    values: list[str] = []
    for field_name in ("contract_types", "work_regimes", "types"):
        raw = item.get(field_name)
        entries = raw if isinstance(raw, list) else [raw]
        for entry in entries:
            text = clean_text(entry)
            if text and text not in values:
                values.append(text)
    return " — ".join(values)


def _safe_key(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z._-]+", "_", clean_text(value))[:120] or "root"


def _hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8", errors="ignore")).hexdigest()[:24]


def _uuid_scores(text: str) -> list[tuple[int, str]]:
    """Rank public UUID-looking values by proximity to EasyToRecruit markers."""
    found: dict[str, int] = {}
    text = text or ""
    for match in UUID_RE.finditer(text):
        uuid = match.group(1).lower()
        start = max(0, match.start() - 600)
        end = min(len(text), match.end() + 600)
        context = text[start:end].lower()
        score = 1
        if "x-client-uuid" in context:
            score += 20
        if any(token in context for token in ("clientuuid", "client_uuid", "client-uuid")):
            score += 14
        if "api.hr-technologies.com" in context:
            score += 10
        if "easytorecruit" in context or "easy to recruit" in context:
            score += 6
        if "vacancies" in context:
            score += 2
        found[uuid] = max(found.get(uuid, 0), score)
    return sorted(((score, uuid) for uuid, score in found.items()), reverse=True)


@dataclass(frozen=True)
class EasyToRecruitTenant:
    key: str
    company: str
    portal_base: str
    languages: tuple[str, ...] = ("fr", "en")
    api_base: str = API_BASE_DEFAULT
    client_uuid: str = ""
    client_uuid_env: str = ""
    frontend_paths: tuple[str, ...] = (
        "/front/fr/vacancies",
        "/front/en/vacancies",
        "/front/nl/vacancies",
        "/front/fr/users/login",
        "/front/en/users/login",
        "/front/nl/users/login",
        "/content/login.asp",
    )
    cache_dir: Path | None = None
    public_vacancy_template: str = "/front/{language}/vacancies/{id}"
    request_timeout: int = 20
    discovery_timeout: int = 10
    max_retries: int = 2
    max_frontend_scripts: int = 24
    max_script_bytes: int = 4_000_000
    extra_discovery_urls: tuple[str, ...] = field(default_factory=tuple)


class EasyToRecruitClient:
    def __init__(self, tenant: EasyToRecruitTenant):
        self.tenant = tenant
        self.portal_base = tenant.portal_base.rstrip("/")
        self.api_base = tenant.api_base.rstrip("/")
        self.cache_dir = Path(tenant.cache_dir) if tenant.cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    # ----------------------------- cache / I/O -----------------------------

    def _uuid_cache_path(self) -> Path | None:
        if not self.cache_dir:
            return None
        return self.cache_dir / "client_uuid.txt"

    def _json_cache_path(self, prefix: str, key: str) -> Path | None:
        if not self.cache_dir:
            return None
        folder = self.cache_dir / "api"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{_safe_key(prefix)}_{_hash(key)}.json"

    def _get_text(self, url: str, timeout: int | None = None) -> tuple[str, str | None, int | None, str]:
        try:
            response = self.session.get(
                url,
                timeout=int(timeout or self.tenant.discovery_timeout),
                allow_redirects=True,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/javascript,text/javascript,*/*;q=0.8",
                    "Referer": self.portal_base + "/",
                },
            )
            status = int(response.status_code)
            response.raise_for_status()
            data = response.content or b""
            if len(data) > self.tenant.max_script_bytes:
                data = data[: self.tenant.max_script_bytes]
            encoding = response.encoding or "utf-8"
            return data.decode(encoding, errors="ignore"), None, status, response.url
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            return "", f"{type(exc).__name__}: {exc}", status, url

    def _api_get(
        self,
        path: str,
        client_uuid: str,
        language: str = "fr",
        params: dict | None = None,
        use_cache: bool = False,
    ) -> tuple[dict | None, str | None, int | None]:
        url = path if path.startswith("http") else f"{self.api_base}/{path.lstrip('/')}"
        cache = self._json_cache_path("GET", f"{url}|{language}|{json.dumps(params or {}, sort_keys=True)}")
        if use_cache and cache and cache.exists():
            try:
                payload = json.loads(cache.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    return payload, None, 200
            except Exception:
                pass

        headers = {
            "Accept": "application/json",
            "Accept-Language": language,
            "X-Client-Uuid": client_uuid,
            "User-Agent": DEFAULT_HEADERS["User-Agent"],
            "Referer": self.portal_base + "/",
        }
        last_error = None
        status = None
        for attempt in range(max(1, self.tenant.max_retries)):
            try:
                response = self.session.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=self.tenant.request_timeout,
                )
                status = int(response.status_code)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Réponse EasyToRecruit JSON non objet")
                if cache:
                    try:
                        cache.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                    except Exception:
                        pass
                return payload, None, status
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if status in {400, 401, 403, 404, 422}:
                    break
                if attempt < self.tenant.max_retries - 1:
                    time.sleep(1 + attempt)
        return None, last_error, status

    # -------------------------- tenant discovery ---------------------------

    def validate_client_uuid(self, client_uuid: str) -> tuple[bool, dict | None, str | None]:
        candidate = clean_text(client_uuid).lower()
        if not UUID_RE.fullmatch(candidate):
            return False, None, "format UUID invalide"
        payload, error, status = self._api_get(
            "vacancies",
            candidate,
            language=(self.tenant.languages[0] if self.tenant.languages else "fr"),
            params={"page[size]": 1, "page[number]": 1},
            use_cache=False,
        )
        if not payload or not isinstance(payload.get("data"), list):
            return False, payload, error or f"API vacancies invalide (HTTP {status})"
        return True, payload, None

    def _discovery_urls(self) -> list[str]:
        urls: list[str] = []
        for raw in self.tenant.extra_discovery_urls:
            url = raw if raw.startswith("http") else urljoin(self.portal_base + "/", raw.lstrip("/"))
            if url not in urls:
                urls.append(url)
        for path in self.tenant.frontend_paths:
            url = path if path.startswith("http") else urljoin(self.portal_base + "/", path.lstrip("/"))
            if url not in urls:
                urls.append(url)
        return urls

    def _script_urls(self, html: str, page_url: str) -> list[str]:
        soup = BeautifulSoup(html or "", "html.parser")
        urls: list[str] = []
        for script in soup.find_all("script", src=True):
            src = clean_text(script.get("src"))
            if not src:
                continue
            absolute = urljoin(page_url, src)
            if absolute not in urls:
                urls.append(absolute)
        for match in re.findall(r"https?://[^\"'<>\s]+\.js(?:\?[^\"'<>\s]+)?", html or "", flags=re.I):
            if match not in urls:
                urls.append(match)
        return urls[: self.tenant.max_frontend_scripts]

    def discover_client_uuid(self, use_cache: bool = True) -> tuple[str, dict]:
        meta = {
            "source": "",
            "frontend_pages": 0,
            "scripts_scanned": 0,
            "candidate_uuids": 0,
            "errors": [],
            "validated": False,
        }

        # 1) Explicit configuration.
        explicit = clean_text(self.tenant.client_uuid).lower()
        if explicit:
            ok, _, error = self.validate_client_uuid(explicit)
            if ok:
                meta.update({"source": "CONFIG", "validated": True})
                return explicit, meta
            meta["errors"].append(f"UUID configuré invalide: {error}")

        # 2) Environment variable (useful when a tenant chooses not to expose it in HTML).
        if self.tenant.client_uuid_env:
            env_value = clean_text(os.getenv(self.tenant.client_uuid_env, "")).lower()
            if env_value:
                ok, _, error = self.validate_client_uuid(env_value)
                if ok:
                    meta.update({"source": f"ENV:{self.tenant.client_uuid_env}", "validated": True})
                    return env_value, meta
                meta["errors"].append(f"UUID environnement invalide: {error}")

        # 3) Validated local cache.
        cache = self._uuid_cache_path()
        if use_cache and cache and cache.exists():
            cached = clean_text(cache.read_text(encoding="utf-8", errors="ignore")).lower()
            if cached:
                ok, _, error = self.validate_client_uuid(cached)
                if ok:
                    meta.update({"source": "CACHE", "validated": True})
                    return cached, meta
                meta["errors"].append(f"UUID cache invalide: {error}")

        # 4) Public frontend discovery. Never brute-force UUIDs.
        candidates: dict[str, int] = {}

        def add_candidates(text: str, bonus: int = 0):
            for score, uuid in _uuid_scores(text):
                candidates[uuid] = max(candidates.get(uuid, 0), score + bonus)

        for page_url in self._discovery_urls():
            text, error, _, final_url = self._get_text(page_url, timeout=self.tenant.discovery_timeout)
            if not text:
                meta["errors"].append(f"frontend {page_url}: {error}")
                continue
            meta["frontend_pages"] += 1
            add_candidates(text, bonus=5)

            # Validate high-confidence UUIDs already present in HTML.
            for score, uuid in sorted(((s, u) for u, s in candidates.items()), reverse=True):
                if score < 8:
                    continue
                ok, _, validation_error = self.validate_client_uuid(uuid)
                if ok:
                    if cache:
                        try:
                            cache.write_text(uuid, encoding="utf-8")
                        except Exception:
                            pass
                    meta.update({"source": f"FRONTEND:{final_url}", "validated": True})
                    meta["candidate_uuids"] = len(candidates)
                    return uuid, meta
                if validation_error:
                    meta["errors"].append(f"UUID {uuid[:8]}… rejeté: {validation_error}")

            for script_url in self._script_urls(text, final_url or page_url):
                script_text, script_error, _, _ = self._get_text(
                    script_url, timeout=self.tenant.discovery_timeout
                )
                meta["scripts_scanned"] += 1
                if not script_text:
                    if script_error:
                        meta["errors"].append(f"script {script_url}: {script_error}")
                    continue
                add_candidates(script_text)

        meta["candidate_uuids"] = len(candidates)
        for _, uuid in sorted(((score, uuid) for uuid, score in candidates.items()), reverse=True):
            ok, _, validation_error = self.validate_client_uuid(uuid)
            if ok:
                if cache:
                    try:
                        cache.write_text(uuid, encoding="utf-8")
                    except Exception:
                        pass
                meta.update({"source": "FRONTEND:UUID", "validated": True})
                return uuid, meta
            if validation_error:
                meta["errors"].append(f"UUID {uuid[:8]}… rejeté: {validation_error}")

        meta["errors"].append(
            "Aucun X-Client-Uuid public valide détecté. Aucun UUID n'a été deviné ou bruteforcé."
        )
        return "", meta

    # ----------------------------- public API ------------------------------

    def vacancies(
        self,
        client_uuid: str,
        language: str,
        page: int = 1,
        page_size: int = 50,
        use_cache: bool = False,
    ) -> tuple[dict | None, str | None, int | None]:
        return self._api_get(
            "vacancies",
            client_uuid,
            language=language,
            params={"page[size]": int(page_size), "page[number]": int(page)},
            use_cache=use_cache,
        )

    def vacancy_detail(
        self,
        client_uuid: str,
        vacancy_id: str | int,
        language: str,
        use_cache: bool = False,
    ) -> tuple[dict | None, str | None, int | None]:
        return self._api_get(
            f"vacancies/{clean_text(vacancy_id)}",
            client_uuid,
            language=language,
            use_cache=use_cache,
        )

    def filters(self, client_uuid: str, language: str = "fr"):
        return self._api_get("filters", client_uuid, language=language)

    def languages(self, client_uuid: str, language: str = "fr"):
        return self._api_get("languages", client_uuid, language=language)

    def vacancy_form(self, client_uuid: str, vacancy_id: str | int, language: str = "fr"):
        return self._api_get(f"vacancies/{clean_text(vacancy_id)}/form", client_uuid, language=language)

    def collect_all(
        self,
        client_uuid: str,
        language: str,
        page_size: int = 50,
        max_pages: int = 20,
        use_cache: bool = False,
    ) -> tuple[list[dict], dict]:
        rows: list[dict] = []
        errors: list[str] = []
        pages = 0
        total = None
        last_page = 1
        for page in range(1, max(1, int(max_pages)) + 1):
            payload, error, status = self.vacancies(
                client_uuid,
                language,
                page=page,
                page_size=page_size,
                use_cache=use_cache,
            )
            if payload is None:
                errors.append(f"API {language.upper()} page {page}: {error or status}")
                break
            data = payload.get("data")
            if not isinstance(data, list):
                errors.append(f"API {language.upper()} page {page}: data[] absent")
                break
            pages += 1
            rows.extend(item for item in data if isinstance(item, dict))
            meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
            try:
                total = int(meta.get("total")) if meta.get("total") is not None else total
            except Exception:
                pass
            try:
                last_page = max(1, int(meta.get("last_page") or 1))
            except Exception:
                last_page = 1
            if page >= last_page or not data:
                break
        return rows, {
            "pages": pages,
            "total": total if total is not None else len(rows),
            "last_page": last_page,
            "reachable": pages > 0,
            "errors": errors,
        }

    def public_vacancy_url(self, vacancy_id: str | int, slug: str = "", language: str = "fr") -> str:
        lang = language if language in {"fr", "en", "nl", "de"} else (self.tenant.languages[0] if self.tenant.languages else "fr")
        path = self.tenant.public_vacancy_template.format(language=lang, id=clean_text(vacancy_id), slug=quote(clean_text(slug), safe="()-_"))
        return urljoin(self.portal_base + "/", path.lstrip("/"))


__all__ = [
    "EasyToRecruitTenant",
    "EasyToRecruitClient",
    "clean_text",
    "html_to_text",
    "vacancy_text",
    "contract_summary",
]
