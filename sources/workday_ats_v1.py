"""
JOB HUNTER BELGIUM
CONNECTEUR WORKDAY - VERSION 1.0

Interroge l'endpoint JSON que le site carrière public utilise lui-même :

    POST https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
    GET  https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{externalPath}

Aucune authentification, aucun blocage, aucune protection contournée.
Voir config/workday_sources.py pour la distinction avec le cas Jobat et la
réserve assumée sur le caractère non documenté de cet endpoint.

Stratégie de collecte, pensée pour limiter les requêtes
------------------------------------------------------
1. La liste est interrogée avec searchText="Belgium" : le filtrage est fait
   côté serveur. Sur GSK, cela ramène 62 offres au lieu de 782.
2. La liste porte déjà `locationsText` ("Belgium-Wavre"). On écarte donc les
   offres non belges AVANT d'aller chercher le détail.
3. Le détail n'est demandé que pour les offres retenues, et il apporte le
   descriptif complet ainsi que `country.descriptor`, donnée structurée qui
   confirme le pays.

Les offres multi-sites affichent "6 Locations" au lieu d'un pays. Elles sont
conservées comme candidates et tranchées au détail : ce sont souvent des
postes globaux, mais en écarter une belge serait pire que d'en vérifier une
de trop.

Politesse
---------
Délai entre chaque requête, plafond de détails par employeur, et arrêt
propre à la première erreur persistante. Le pipeline continue sans cette
source plutôt que d'insister.
"""

from __future__ import annotations

import html
import re
import time
from datetime import datetime, timezone

import requests

from config.workday_sources import WORKDAY_VERSION, enabled_companies
from database.models import JobOffer
from sources.location_belgium import BE_CONFIRMED, detect_belgium


WORKDAY_CONNECTOR_VERSION = "1.0"

REQUEST_TIMEOUT = 20
MAX_RETRIES = 2
PAGE_SIZE = 20
MAX_PAGES = 20
MAX_DETAILS_PER_COMPANY = 120
DELAY_LIST = 0.4
DELAY_DETAIL = 0.25

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "JobHunterBelgium/1.0 (recherche d'emploi personnelle)",
    "Accept": "application/json",
    "Content-Type": "application/json",
})


def _clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def html_to_text(value) -> str:
    raw = html.unescape(str(value or ""))
    raw = re.sub(r"<\s*(br|/p|/li|/div|/h[1-6])\s*/?>", "\n", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r"\n\s*\n+", "\n", raw)
    return raw.strip()


def _base_url(company: dict) -> str:
    return (f"https://{company['tenant']}.{company['wd']}.myworkdayjobs.com"
            f"/wday/cxs/{company['tenant']}/{company['site']}")


# ============================================================
# APPELS
# ============================================================

def fetch_job_list(company: dict, search_text: str = "Belgium"):
    """Pagination de la liste. Renvoie (postings, erreur)."""
    url = f"{_base_url(company)}/jobs"
    postings = []
    total = None

    for page in range(MAX_PAGES):
        corps = {
            "appliedFacets": {},
            "limit": PAGE_SIZE,
            "offset": page * PAGE_SIZE,
            "searchText": search_text,
        }

        reponse = None
        for essai in range(1, MAX_RETRIES + 1):
            try:
                reponse = SESSION.post(url, json=corps, timeout=REQUEST_TIMEOUT)
                break
            except Exception as error:
                if essai == MAX_RETRIES:
                    return postings, f"réseau : {error}"
                time.sleep(0.5 * essai)

        if reponse is None:
            return postings, "aucune réponse"
        if reponse.status_code == 404:
            return postings, "tenant ou site inconnu (404)"
        if reponse.status_code != 200:
            return postings, f"HTTP {reponse.status_code}"

        try:
            payload = reponse.json()
        except Exception as error:
            return postings, f"JSON illisible : {error}"

        if total is None:
            total = payload.get("total")

        lot = payload.get("jobPostings") or []
        if not lot:
            break

        postings.extend(lot)
        if total is not None and len(postings) >= total:
            break

        time.sleep(DELAY_LIST)

    return postings, None


def fetch_job_detail(company: dict, external_path: str):
    """Détail d'une offre. Renvoie (info, erreur)."""
    if not external_path:
        return None, "chemin absent"

    url = f"{_base_url(company)}{external_path}"
    try:
        reponse = SESSION.get(url, timeout=REQUEST_TIMEOUT)
    except Exception as error:
        return None, f"réseau : {error}"

    if reponse.status_code != 200:
        return None, f"HTTP {reponse.status_code}"

    try:
        return (reponse.json() or {}).get("jobPostingInfo") or {}, None
    except Exception as error:
        return None, f"JSON illisible : {error}"


# ============================================================
# FILTRAGE ET CONVERSION
# ============================================================

def _multi_site(locations_text: str) -> bool:
    """"6 Locations" : le pays n'est pas lisible depuis la liste."""
    return bool(re.match(r"^\s*\d+\s+locations?\s*$", str(locations_text or ""),
                         re.I))


def looks_belgian(posting: dict) -> bool:
    """
    Pré-filtre sur la liste, pour ne pas demander le détail de chaque offre.

    Workday écrit "Belgium-Wavre" : detect_belgium() y reconnaît le pays.
    Les offres multi-sites passent, faute d'information exploitable ici.
    """
    texte = _clean(posting.get("locationsText"))
    if _multi_site(texte):
        return True
    return detect_belgium(texte.replace("-", ", ")) in ("BE_CONFIRMED", "BE_LIKELY")


def build_matching_text(detail: dict, posting: dict) -> str:
    titre = _clean(detail.get("title") or posting.get("title"))
    corps = html_to_text(detail.get("jobDescription"))
    return "\n\n".join(p for p in (titre, corps) if p)


def convert_workday_job(detail: dict, posting: dict, company: dict) -> JobOffer | None:
    if not detail:
        return None

    texte = build_matching_text(detail, posting)
    if not texte:
        return None

    pays = _clean((detail.get("country") or {}).get("descriptor"))
    lieu = _clean(detail.get("location") or posting.get("locationsText"))
    localisation = ", ".join(p for p in (lieu.replace("-", ", "), pays) if p)

    req_id = _clean(detail.get("jobReqId")) or _clean(detail.get("id"))

    offre = JobOffer(
        source="WORKDAY",
        external_id=f"{company['tenant']}:{req_id}",
        title=_clean(detail.get("title") or posting.get("title")),
        company=company.get("label") or company["tenant"],
        location=localisation,
        description=texte,
        url=_clean(detail.get("externalUrl")),
        date_published=_clean(detail.get("startDate")) or None,
        contract_type=_clean(detail.get("timeType")) or None,
        language=None,
        salary=None,
        date_collected=datetime.now(timezone.utc).isoformat(),
    )

    setattr(offre, "collection_channel", "WORKDAY")
    setattr(offre, "origin_source", company["tenant"])
    setattr(offre, "direct_employer", True)
    setattr(offre, "source_company_identifier", company["tenant"])

    setattr(offre, "remote", _clean(detail.get("remoteType")))
    setattr(offre, "workday_req_id", req_id)

    # country.descriptor est structuré : plus fiable que le texte.
    statut = BE_CONFIRMED if pays.lower() == "belgium" else detect_belgium(localisation)
    setattr(offre, "belgium_status", statut)
    setattr(offre, "country_descriptor", pays or None)

    setattr(offre, "source_eligibility_status", "ELIGIBLE")
    setattr(offre, "source_eligibility_reason", None)

    return offre


# ============================================================
# COLLECTE
# ============================================================

def collect_workday_jobs(companies=None, verbose=True):
    companies = companies if companies is not None else enabled_companies()

    jobs = []
    rapport = []

    if verbose:
        print()
        print("=" * 76)
        print("        SOURCE - WORKDAY (SITES CARRIÈRE EMPLOYEURS)")
        print("=" * 76)

    for company in companies:
        postings, erreur = fetch_job_list(company)

        candidates = [p for p in postings if looks_belgian(p)]
        retenues, hors_be, echecs = 0, 0, 0

        for posting in candidates[:MAX_DETAILS_PER_COMPANY]:
            detail, err_detail = fetch_job_detail(
                company, _clean(posting.get("externalPath")))
            time.sleep(DELAY_DETAIL)

            if err_detail or detail is None:
                echecs += 1
                continue

            try:
                offre = convert_workday_job(detail, posting, company)
            except Exception:
                echecs += 1
                continue

            if offre is None:
                echecs += 1
                continue

            if getattr(offre, "belgium_status", "") not in ("BE_CONFIRMED",
                                                            "BE_LIKELY"):
                hors_be += 1
                continue

            jobs.append(offre)
            retenues += 1

        ligne = {
            "tenant": company["tenant"],
            "label": company.get("label") or company["tenant"],
            "listed": len(postings),
            "candidates": len(candidates),
            "retained": retenues,
            "outside_belgium": hors_be,
            "failures": echecs,
            "error": erreur,
        }
        rapport.append(ligne)

        if verbose:
            if erreur:
                print(f"  {ligne['label']:<16} ⚠️  {erreur}")
            else:
                print(f"  {ligne['label']:<16} listées={len(postings):<4} "
                      f"candidates={len(candidates):<4} BE={retenues:<4} "
                      f"hors BE={hors_be:<3} échecs={echecs}")

    if verbose:
        print()
        print(f"WORKDAY - offres retenues : {len(jobs)}")
        print(f"WORKDAY - erreurs fatales : "
              f"{sum(1 for r in rapport if r['error'])}")

    return {
        "version": WORKDAY_CONNECTOR_VERSION,
        "config_version": WORKDAY_VERSION,
        "jobs": jobs,
        "report": rapport,
    }
