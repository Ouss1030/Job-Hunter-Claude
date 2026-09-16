"""
JOB HUNTER BELGIUM
CONNECTEUR ORACLE RECRUITING CLOUD - VERSION 1.0

Les sites carriere Oracle ("Candidate Experience") exposent une API REST
publique, sans cle, celle que la page elle-meme appelle :

    GET https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions
        ?onlyData=true&finder=findReqs;siteNumber={site},limit=200,offset=0
    GET https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails
        ?expand=all&onlyData=true&finder=ById;siteNumber={site},Id="{id}"

Verifie le 16 septembre 2026 sur quatre employeurs belges detectes par le
moteur de decouverte : Telenet (62 offres belges), Euroclear (16), Aperam
(9), Carmeuse (3). La liste donne titre, lieu, pays, date ; le detail donne
la description complete en HTML.

Un employeur = {"host": "ebza.fa.em2.oraclecloud.com", "site": "CX_1001",
"lang": "nl", "label": "Telenet"} dans config/ats_employers_v2.json.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import requests

from database.models import JobOffer
from sources.ats_public_v2 import html_to_text, _statut_be, _retenir


ORACLE_CLOUD_VERSION = "1.0"

TIMEOUT = 25
PAGE = 200
MAX_PAGES = 10
MAX_DETAILS = 150
PAUSE_DETAIL = 0.3
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) JobHunter/oracle-cloud",
    "Accept": "application/json",
}


def _clean(v) -> str:
    return "" if v is None else str(v).strip()


def _get(session, host: str, ressource: str, params: dict) -> dict:
    r = session.get(f"https://{host}/hcmRestApi/resources/latest/{ressource}",
                    params=params, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def lister(host: str, site: str, session) -> list[dict]:
    """Toutes les requisitions publiees d'un site, par pages de 200."""
    lignes = []
    for page in range(MAX_PAGES):
        data = _get(session, host, "recruitingCEJobRequisitions", {
            "onlyData": "true",
            "expand": "requisitionList.secondaryLocations",
            "finder": f"findReqs;siteNumber={site},limit={PAGE},offset={page * PAGE},sortBy=POSTING_DATES_DESC",
        })
        item = (data.get("items") or [{}])[0]
        req = item.get("requisitionList") or []
        lignes.extend(req)
        total = int(item.get("TotalJobsCount") or 0)
        if not req or len(lignes) >= total:
            break
    return lignes


def detail(host: str, site: str, req_id: str, session) -> dict:
    data = _get(session, host, "recruitingCEJobRequisitionDetails", {
        "expand": "all", "onlyData": "true",
        "finder": f'ById;siteNumber={site},Id="{req_id}"',
    })
    items = data.get("items") or []
    return items[0] if items else {}


def _localisation(r: dict) -> str:
    parties = [_clean(r.get("PrimaryLocation"))]
    for s in r.get("secondaryLocations") or []:
        parties.append(_clean(s.get("Name")))
    return " ; ".join(p for p in parties if p)


def collect_oracle_cloud(company: dict, session=None, include_unknown: bool = False,
                         max_details: int = MAX_DETAILS) -> tuple[list[JobOffer], dict]:
    session = session or requests.Session()
    host, site = _clean(company.get("host")), _clean(company.get("site"))
    lang = _clean(company.get("lang")) or "en"
    label = _clean(company.get("label")) or host
    lignes = lister(host, site, session)
    jobs, hors_be, details, echecs = [], 0, 0, 0
    for r in lignes:
        localisation = _localisation(r)
        statut = _statut_be(localisation, _clean(r.get("PrimaryLocationCountry")))
        if not _retenir(statut, include_unknown):
            hors_be += 1
            continue
        req_id = _clean(r.get("Id"))
        description = _clean(r.get("ShortDescriptionStr"))
        if details < max_details:
            try:
                d = detail(host, site, req_id, session)
                description = "\n".join(x for x in [
                    html_to_text(d.get("ExternalDescriptionStr")),
                    html_to_text(d.get("ExternalResponsibilitiesStr")),
                    html_to_text(d.get("ExternalQualificationsStr")),
                ] if x) or description
                details += 1
                time.sleep(PAUSE_DETAIL)
            except Exception:
                echecs += 1
        job = JobOffer(
            source="ORACLE_CLOUD", external_id=f"{host}:{req_id}",
            title=_clean(r.get("Title")), company=label,
            location=localisation or "Lieu non précisé", description=description,
            url=f"https://{host}/hcmUI/CandidateExperience/{lang}/sites/{site}/job/{req_id}",
            date_published=_clean(r.get("PostedDate"))[:10] or None,
            contract_type=_clean(r.get("WorkerType")) or None,
            language=_clean(r.get("Language")) or None, salary=None,
            date_collected=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        job.collection_channel = "ORACLE_CLOUD"
        job.origin_source = host
        job.detail_enrichment_attempted = True
        job.detail_enrichment_success = len(description) >= 200
        job.detail_matching_text_length = len(description)
        if r.get("PostingEndDate"):
            job.application_deadline = _clean(r.get("PostingEndDate"))[:10]
        jobs.append(job)
    return jobs, {"total": len(lignes), "be": len(jobs), "hors_be": hors_be,
                  "details": details, "echecs_detail": echecs}


def collect_oracle_cloud_jobs(companies: list[dict], verbose: bool = True) -> dict:
    session = requests.Session()
    jobs, report = [], []
    for c in companies:
        if not c.get("enabled", True):
            continue
        label = _clean(c.get("label")) or _clean(c.get("host"))
        try:
            trouves, meta = collect_oracle_cloud(c, session)
            jobs.extend(trouves)
            meta.update(label=label, error=None)
        except Exception as e:
            meta = {"label": label, "total": 0, "be": 0, "hors_be": 0, "error": f"{type(e).__name__}: {str(e)[:100]}"}
        report.append(meta)
        if verbose:
            print(f"  {label:<24} " + (f"⚠️  {meta['error']}" if meta["error"] else
                  f"total={meta['total']:<4} BE={meta['be']:<4} hors BE={meta['hors_be']:<4} détails={meta.get('details', 0)}"))
    dedup = {}
    for j in jobs:
        dedup[j.external_id] = j
    return {"jobs": list(dedup.values()), "report": report}
