"""
JOB HUNTER BELGIUM
CONNECTEUR GREENHOUSE - VERSION 1.0

API Job Board publique, documentée, sans authentification :

    GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true

Aucun contournement de protection. Greenhouse publie ce point d'entrée pour
que les pages carrière et les agrégateurs le consomment.

Trois particularités observées sur données réelles (20/08/2026)
---------------------------------------------------------------
1. `content` est du HTML **doublement échappé** : "&lt;p&gt;" au lieu de
   "<p>". Une seule passe de unescape laisse des balises visibles dans le
   texte envoyé au Matcher.

2. `location.name` peut contenir **plusieurs sites** séparés par ";" :

       "New York, New York, USA; Raleigh, North Carolina, USA"

   Une offre ouverte sur plusieurs sites dont un belge concerne la Belgique.
   D'où l'usage de detect_belgium_multi(), qui retient le meilleur statut.

3. `content` contient l'annonce entière, présentation d'entreprise comprise.
   Contrairement à SmartRecruiters, il n'existe pas de champ corporate
   séparé — même limite que Recruitee, documentée ici plutôt que masquée.

Filtrage linguistique
---------------------
Greenhouse expose `language` sur l'offre. Le candidat étant A2 en
néerlandais, une annonce publiée en néerlandais est signalée dès la
collecte via `posting_language`, sans attendre le Gate. La décision de
rejet reste au Gate : ce module se contente d'exposer l'information.
"""

from __future__ import annotations

import html
import re
import time
from datetime import datetime, timezone

import requests

from config.greenhouse_sources import GREENHOUSE_VERSION, enabled_companies
from database.models import JobOffer
from sources.location_belgium import detect_belgium_multi


GREENHOUSE_CONNECTOR_VERSION = "1.0"

API_TEMPLATE = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
REQUEST_TIMEOUT = 25
MAX_RETRIES = 3
DELAY_BETWEEN_COMPANIES = 0.5

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "JobHunterBelgium/1.0 (recherche d'emploi personnelle)",
    "Accept": "application/json",
})


def _clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def html_to_text(value) -> str:
    """
    HTML Greenhouse -> texte lisible.

    Le double unescape n'est pas une précaution théorique : l'API renvoie
    "&lt;p&gt;", donc une seule passe produit "<p>" au lieu de le retirer.
    """
    raw = str(value or "")
    raw = html.unescape(html.unescape(raw))
    raw = re.sub(r"<\s*(br|/p|/li|/div|/h[1-6])\s*/?>", "\n", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r"\n\s*\n+", "\n", raw)
    return raw.strip()


def fetch_board_jobs(token: str):
    """Renvoie (offres, erreur). Une erreur n'interrompt pas les autres boards."""
    url = API_TEMPLATE.format(token=token)

    for essai in range(1, MAX_RETRIES + 1):
        try:
            response = SESSION.get(url, params={"content": "true"},
                                   timeout=REQUEST_TIMEOUT)
        except Exception as error:
            if essai == MAX_RETRIES:
                return [], f"réseau : {error}"
            time.sleep(0.5 * essai)
            continue

        if response.status_code == 404:
            return [], "board inconnu chez Greenhouse (404)"
        if response.status_code != 200:
            if essai == MAX_RETRIES:
                return [], f"HTTP {response.status_code}"
            time.sleep(0.5 * essai)
            continue

        try:
            payload = response.json()
        except Exception as error:
            return [], f"JSON illisible : {error}"

        jobs = payload.get("jobs")
        if jobs is None:
            return [], "réponse sans clé 'jobs'"
        return jobs, None

    return [], "échec après retries"


def _location_text(job: dict) -> str:
    direct = _clean((job.get("location") or {}).get("name"))
    if direct:
        return direct

    bureaux = [
        _clean(o.get("location") or o.get("name"))
        for o in (job.get("offices") or [])
    ]
    return "; ".join(b for b in bureaux if b)


def _departments(job: dict) -> str:
    noms = [_clean(d.get("name")) for d in (job.get("departments") or [])]
    return " / ".join(n for n in noms if n)


def build_matching_text(job: dict) -> dict:
    """
    Greenhouse ne sépare pas le corporate du poste : `content` contient tout.

    On place le titre et le département en tête pour que les signaux les
    plus spécifiques pèsent, puis le corps de l'annonce.
    """
    titre = _clean(job.get("title"))
    departement = _departments(job)
    corps = html_to_text(job.get("content"))

    morceaux = [p for p in (titre, departement, corps) if p]
    return {
        "matching_text": "\n\n".join(morceaux),
        "content_text": corps,
    }


def convert_greenhouse_job(job: dict, company: dict) -> JobOffer | None:
    token = company["identifier"]
    job_id = job.get("id")
    if not job_id:
        return None

    ad = build_matching_text(job)
    if not ad["matching_text"]:
        return None

    localisation = _location_text(job)

    offer = JobOffer(
        source="GREENHOUSE",
        external_id=f"{token}:{job_id}",
        title=_clean(job.get("title")),
        company=_clean(job.get("company_name")) or company.get("label") or token,
        location=localisation,
        description=ad["matching_text"],
        url=_clean(job.get("absolute_url")),
        date_published=_clean(job.get("first_published")) or None,
        contract_type=None,
        language=_clean(job.get("language")) or None,
        salary=None,
        date_collected=datetime.now(timezone.utc).isoformat(),
    )

    setattr(offer, "collection_channel", "GREENHOUSE")
    setattr(offer, "origin_source", token)
    setattr(offer, "direct_employer", True)
    setattr(offer, "source_company_identifier", token)

    setattr(offer, "department", _departments(job))
    setattr(offer, "requisition_id", _clean(job.get("requisition_id")))
    setattr(offer, "posting_language", _clean(job.get("language")).lower() or None)

    setattr(offer, "belgium_status", detect_belgium_multi(localisation))

    setattr(offer, "source_eligibility_status", "ELIGIBLE")
    setattr(offer, "source_eligibility_reason", None)

    return offer


def collect_greenhouse_jobs(companies=None, include_unknown_location=False,
                            verbose=True):
    """
    include_unknown_location est à False par défaut, contrairement à
    Recruitee : un board Greenhouse est majoritairement international, et
    conserver tous les "Remote" mondiaux noierait les offres belges.
    """
    companies = companies if companies is not None else enabled_companies()

    jobs = []
    rapport = []

    if verbose:
        print()
        print("=" * 76)
        print("           SOURCE - GREENHOUSE (ATS PUBLIC)")
        print("=" * 76)

    for company in companies:
        token = company["identifier"]
        offres, erreur = fetch_board_jobs(token)

        retenues, hors_be, inconnues, echecs, nl = 0, 0, 0, 0, 0
        for brut in offres:
            try:
                offer = convert_greenhouse_job(brut, company)
            except Exception:
                echecs += 1
                continue
            if offer is None:
                echecs += 1
                continue

            statut = getattr(offer, "belgium_status", "")
            if statut == "BE_UNKNOWN":
                inconnues += 1
                if not include_unknown_location:
                    continue
            elif statut not in ("BE_CONFIRMED", "BE_LIKELY"):
                hors_be += 1
                continue

            if getattr(offer, "posting_language", None) == "nl":
                nl += 1

            jobs.append(offer)
            retenues += 1

        ligne = {
            "identifier": token,
            "label": company.get("label") or token,
            "offers_total": len(offres),
            "retained": retenues,
            "outside_belgium": hors_be,
            "unknown_location": inconnues,
            "dutch_postings": nl,
            "failures": echecs,
            "error": erreur,
        }
        rapport.append(ligne)

        if verbose:
            if erreur:
                print(f"  {ligne['label']:<20} ⚠️  {erreur}")
            else:
                print(f"  {ligne['label']:<20} total={len(offres):<4} "
                      f"BE={retenues:<4} hors BE={hors_be:<4} "
                      f"inconnues={inconnues:<4} NL={nl:<3} échecs={echecs}")

        time.sleep(DELAY_BETWEEN_COMPANIES)

    if verbose:
        print()
        print(f"GREENHOUSE - offres retenues : {len(jobs)}")
        print(f"GREENHOUSE - erreurs fatales : "
              f"{sum(1 for r in rapport if r['error'])}")

    return {
        "version": GREENHOUSE_CONNECTOR_VERSION,
        "config_version": GREENHOUSE_VERSION,
        "jobs": jobs,
        "report": rapport,
    }
