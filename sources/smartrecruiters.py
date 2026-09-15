"""
JOB HUNTER BELGIUM
SOURCE SMARTRECRUITERS V1.1

Correction V1.1
===============
Le texte corporate "companyDescription" n'est PLUS injecté dans
JobOffer.description, car il polluait le Matcher avec des mots-clés génériques
(pharmaceutical, laboratory, data, quality...) sans rapport avec le poste.

Aucune donnée n'est perdue :
- description = contenu réellement lié au poste
- company_description = présentation générale de l'employeur (attribut dynamique)

Le reste du connecteur V1.0 est inchangé :
- Posting API structurée SmartRecruiters
- Belgique uniquement
- pagination
- retries
- détails complets
- cache mémoire
- X-SmartToken optionnel
"""

from __future__ import annotations

import html
import os
import re
from datetime import datetime, timezone
from typing import Any

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.smartrecruiters_sources import (
    SMARTRECRUITERS_COMPANIES,
    SMARTRECRUITERS_COUNTRY,
    SMARTRECRUITERS_PAGE_SIZE,
    SMARTRECRUITERS_TIMEOUT_SECONDS,
)
from database.models import JobOffer


API_BASE = "https://api.smartrecruiters.com/v1/companies"
_DETAIL_CACHE: dict[tuple[str, str], dict] = {}


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _norm(value: Any) -> str:
    return _clean(value).lower()


def _html_to_text(value: Any) -> str:
    text = _clean(value)
    if not text:
        return ""
    text = html.unescape(text)
    return _clean(BeautifulSoup(text, "html.parser").get_text(" ", strip=True))


def _session() -> requests.Session:
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        status=4,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)

    session = requests.Session()
    session.mount("https://", adapter)
    session.headers.update(
        {
            "Accept": "application/json",
            "User-Agent": "JobHunterBelgium/1.1 personal-job-search",
        }
    )

    token = (
        os.getenv("SMARTRECRUITERS_API_KEY")
        or os.getenv("SMARTRECRUITERS_SMARTTOKEN")
        or ""
    ).strip()
    if token:
        session.headers["X-SmartToken"] = token

    return session


def _request_json(
    session: requests.Session,
    url: str,
    *,
    params: dict | None = None,
) -> dict:
    response = session.get(
        url,
        params=params,
        timeout=SMARTRECRUITERS_TIMEOUT_SECONDS,
    )

    if response.status_code in {401, 403}:
        raise RuntimeError(
            f"SmartRecruiters HTTP {response.status_code}. "
            "Le Posting API a refusé cette requête. "
            "Si un token officiel est requis, définir "
            "SMARTRECRUITERS_API_KEY dans l'environnement."
        )

    response.raise_for_status()

    try:
        payload = response.json()
    except Exception as exc:
        raise RuntimeError(
            f"Réponse SmartRecruiters non JSON pour {url}: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise RuntimeError(
            f"Format SmartRecruiters inattendu pour {url}: "
            f"{type(payload).__name__}"
        )

    return payload


def _belgium_location(location: dict | None) -> bool:
    loc = location or {}
    country = _norm(
        loc.get("country")
        or loc.get("countryCode")
        or ""
    )
    return country in {
        "be",
        "belgium",
        "belgique",
        "belgië",
        "belgie",
    }


def _location_text(location: dict | None) -> str:
    loc = location or {}

    country = _clean(loc.get("country") or loc.get("countryCode"))
    if _norm(country) == "be":
        country = "Belgique"

    parts = [
        _clean(loc.get("city")),
        _clean(loc.get("region")),
        country,
    ]

    result = []
    for part in parts:
        if part and part not in result:
            result.append(part)

    return ", ".join(result)


def _label(obj: Any) -> str:
    if isinstance(obj, dict):
        return _clean(
            obj.get("label")
            or obj.get("name")
            or obj.get("id")
        )
    return _clean(obj)


def _extract_job_ad(detail: dict) -> dict:
    """
    Retourne séparément :
    - matching_text : uniquement contenu lié au poste
    - company_description : présentation générale entreprise
    - sections : sections nettoyées individuellement
    """
    job_ad = detail.get("jobAd") or {}
    raw_sections = job_ad.get("sections") or {}
    sections: dict[str, str] = {}

    if isinstance(raw_sections, dict):
        for key, value in raw_sections.items():
            if isinstance(value, dict):
                title = _html_to_text(value.get("title"))
                body = _html_to_text(value.get("text"))
            else:
                title = ""
                body = _html_to_text(value)

            if body:
                sections[key] = f"{title}: {body}" if title else body

    # Compatibilité variantes plates.
    for key in (
        "companyDescription",
        "jobDescription",
        "qualifications",
        "additionalInformation",
    ):
        if key in job_ad and key not in sections:
            body = _html_to_text(job_ad.get(key))
            if body:
                sections[key] = body

    company_description = _clean(sections.get("companyDescription"))

    # CRITIQUE V1.1 :
    # companyDescription est volontairement exclu du texte envoyé au Matcher.
    ordered_job_keys = (
        "jobDescription",
        "qualifications",
        "additionalInformation",
    )

    matching_parts = [
        sections[key]
        for key in ordered_job_keys
        if sections.get(key)
    ]

    # Conserver aussi toute section inconnue liée au job,
    # SAUF companyDescription.
    for key, value in sections.items():
        if key not in set(ordered_job_keys) | {"companyDescription"}:
            matching_parts.append(value)

    matching_text = _clean(" ".join(matching_parts))

    return {
        "matching_text": matching_text,
        "company_description": company_description,
        "sections": sections,
    }


# Alias conservé pour compatibilité avec le diagnostic V1.
def _sections_text(detail: dict) -> tuple[str, dict[str, str]]:
    extracted = _extract_job_ad(detail)
    return extracted["matching_text"], extracted["sections"]


def _compensation_text(detail: dict) -> str | None:
    comp = detail.get("compensation") or {}
    if not isinstance(comp, dict) or not comp:
        return None

    parts = []
    for key in ("min", "max", "currency", "period", "type"):
        value = comp.get(key)
        if value not in (None, ""):
            parts.append(_clean(value))

    return " ".join(parts) or None


def _public_url(
    detail: dict,
    company_identifier: str,
    posting_id: str,
) -> str:
    for key in ("postingUrl", "jobAdUrl", "applyUrl"):
        value = _clean(detail.get(key))
        if value.startswith("http"):
            return value

    return f"{API_BASE}/{company_identifier}/postings/{posting_id}"


def list_company_postings(
    company_identifier: str,
    *,
    country: str = SMARTRECRUITERS_COUNTRY,
    session: requests.Session | None = None,
) -> list[dict]:
    session = session or _session()

    offset = 0
    results: list[dict] = []

    while True:
        payload = _request_json(
            session,
            f"{API_BASE}/{company_identifier}/postings",
            params={
                "country": country,
                "destination": "PUBLIC",
                "limit": SMARTRECRUITERS_PAGE_SIZE,
                "offset": offset,
            },
        )

        content = payload.get("content") or []
        if not isinstance(content, list):
            raise RuntimeError(
                f"{company_identifier}: champ content inattendu."
            )

        for item in content:
            if not isinstance(item, dict):
                continue
            if _belgium_location(item.get("location") or {}):
                results.append(item)

        total = int(payload.get("totalFound") or 0)
        limit = int(payload.get("limit") or SMARTRECRUITERS_PAGE_SIZE)
        current_offset = int(payload.get("offset") or offset)

        if not content or current_offset + limit >= total:
            break

        offset = current_offset + limit

    return results


def get_posting_detail(
    company_identifier: str,
    posting_id: str,
    *,
    session: requests.Session | None = None,
    use_cache: bool = True,
) -> dict:
    key = (company_identifier, str(posting_id))

    if use_cache and key in _DETAIL_CACHE:
        return _DETAIL_CACHE[key]

    session = session or _session()

    payload = _request_json(
        session,
        f"{API_BASE}/{company_identifier}/postings/{posting_id}",
    )

    if use_cache:
        _DETAIL_CACHE[key] = payload

    return payload


def posting_to_job(
    company_identifier: str,
    detail: dict,
) -> JobOffer:
    posting_id = _clean(detail.get("id") or detail.get("uuid"))

    company_obj = detail.get("company") or {}
    company_name = _clean(
        company_obj.get("name")
        if isinstance(company_obj, dict)
        else company_obj
    ) or company_identifier

    ad = _extract_job_ad(detail)
    location = detail.get("location") or {}

    released = _clean(
        detail.get("releasedDate")
        or detail.get("postedDate")
    )

    contract_type = _label(detail.get("typeOfEmployment"))
    language = _label(detail.get("language") or {})

    job = JobOffer(
        source="SMARTRECRUITERS",
        external_id=f"{company_identifier}:{posting_id}",
        title=_clean(detail.get("name")),
        company=company_name,
        location=_location_text(location),
        description=ad["matching_text"],
        url=_public_url(detail, company_identifier, posting_id),
        date_published=released,
        contract_type=contract_type or None,
        language=language or None,
        salary=_compensation_text(detail),
        date_collected=datetime.now(timezone.utc).isoformat(),
    )

    setattr(job, "collection_channel", "SMARTRECRUITERS")
    setattr(job, "origin_source", company_identifier)
    setattr(job, "direct_employer", True)
    setattr(job, "source_company_identifier", company_identifier)

    setattr(job, "smartrecruiters_uuid", _clean(detail.get("uuid")))
    setattr(job, "smartrecruiters_ref_number", _clean(detail.get("refNumber")))

    setattr(job, "department", _label(detail.get("department")))
    setattr(job, "job_function", _label(detail.get("function")))
    setattr(job, "industry", _label(detail.get("industry")))
    setattr(job, "experience_level", _label(detail.get("experienceLevel")))

    setattr(job, "remote", bool(location.get("remote")))
    setattr(job, "apply_url", _clean(detail.get("applyUrl")))

    # V1.1 : données corporate conservées, mais hors Matcher.
    setattr(job, "company_description", ad["company_description"])
    setattr(job, "job_sections", ad["sections"])

    setattr(job, "source_eligibility_status", "ELIGIBLE")
    setattr(job, "source_eligibility_reason", None)

    return job


def fetch_company_jobs(
    company_identifier: str,
    *,
    session: requests.Session | None = None,
    detail_limit: int | None = None,
) -> tuple[list[JobOffer], dict]:
    session = session or _session()

    listings = list_company_postings(
        company_identifier,
        session=session,
    )

    selected = (
        listings[:detail_limit]
        if detail_limit is not None
        else listings
    )

    jobs: list[JobOffer] = []
    failures: list[dict] = []

    for item in selected:
        posting_id = _clean(item.get("id") or item.get("uuid"))

        if not posting_id:
            failures.append(
                {
                    "posting_id": "",
                    "error": "ID manquant",
                }
            )
            continue

        try:
            detail = get_posting_detail(
                company_identifier,
                posting_id,
                session=session,
                use_cache=True,
            )

            if not _belgium_location(detail.get("location") or {}):
                continue

            jobs.append(
                posting_to_job(company_identifier, detail)
            )

        except Exception as exc:
            failures.append(
                {
                    "posting_id": posting_id,
                    "title": _clean(item.get("name")),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    meta = {
        "company_identifier": company_identifier,
        "listings_belgium": len(listings),
        "details_attempted": len(selected),
        "jobs_converted": len(jobs),
        "failures": failures,
    }

    return jobs, meta


def fetch_smartrecruiters_jobs(
    *,
    companies: list[dict] | None = None,
    detail_limit_per_company: int | None = None,
) -> tuple[list[JobOffer], list[dict]]:
    if companies is None:
        from config.smartrecruiters_sources import enabled_companies
        companies = enabled_companies()
    configured = companies or SMARTRECRUITERS_COMPANIES
    session = _session()

    all_jobs: list[JobOffer] = []
    metas: list[dict] = []

    for company in configured:
        if not company.get("enabled", True):
            continue

        identifier = _clean(company.get("identifier"))
        if not identifier:
            continue

        try:
            jobs, meta = fetch_company_jobs(
                identifier,
                session=session,
                detail_limit=detail_limit_per_company,
            )

            meta["label"] = _clean(company.get("label")) or identifier
            meta["tracks"] = list(company.get("tracks") or [])

            all_jobs.extend(jobs)
            metas.append(meta)

        except Exception as exc:
            metas.append(
                {
                    "company_identifier": identifier,
                    "label": _clean(company.get("label")) or identifier,
                    "tracks": list(company.get("tracks") or []),
                    "listings_belgium": 0,
                    "details_attempted": 0,
                    "jobs_converted": 0,
                    "failures": [],
                    "fatal_error": f"{type(exc).__name__}: {exc}",
                }
            )

    dedup: dict[str, JobOffer] = {}
    for job in all_jobs:
        dedup[job.external_id] = job

    return list(dedup.values()), metas
