"""
JOB HUNTER BELGIUM
CONNECTEUR RECRUITEE - VERSION 1.0

API publique, documentée, sans authentification :

    GET https://{identifiant}.recruitee.com/api/offers/

Aucun contournement de protection. Recruitee expose ce point d'entrée pour
que les pages carrière et les agrégateurs puissent le consommer.

Pourquoi Recruitee en premier
-----------------------------
C'est le seul des trois ATS visés qui expose un `country_code` structuré.
Le filtrage Belgique ne dépend donc pas du parsing de texte, ce qui permet
de valider le patron de connecteur avant d'attaquer Greenhouse et Lever,
où la localisation est une chaîne libre.

Leçon SmartRecruiters V1.1 reprise ici
--------------------------------------
Chez SmartRecruiters, la description corporate était un champ séparé, et
l'inclure dans le texte envoyé au Matcher produisait des faux positifs
Real Estate, HR et KYC.

Recruitee est plus délicat : `description` **mélange** la présentation de
l'entreprise et le contenu du poste, dans le même champ HTML. On ne peut
donc pas simplement l'exclure sans perdre le poste lui-même.

Choix retenu :
- `requirements` est le champ le plus spécifique au poste : il est placé
  en tête du texte de matching ;
- `description` suit, car il contient le contenu réel du poste ;
- `sharing_description`, qui est une reprise purement corporate, est
  conservé à part et n'entre pas dans le Matcher.

Ce compromis est documenté parce qu'il diffère de SmartRecruiters : ici
un peu de texte corporate subsiste dans le matching, faute de champ propre.

Bonus structuré
---------------
Recruitee expose `education_code` ("master_degree", "bachelor_degree"...).
C'est l'exigence de diplôme sous forme de donnée, là où le Gate doit
habituellement la déduire du texte. Elle est exposée sur l'offre.
"""

from __future__ import annotations

import html
import re
import time
from datetime import datetime, timezone

import requests

from config.recruitee_sources import RECRUITEE_VERSION, enabled_companies
from database.models import JobOffer
from sources.location_belgium import BE_CONFIRMED, analyze_location


RECRUITEE_CONNECTOR_VERSION = "1.0"

API_TEMPLATE = "https://{identifier}.recruitee.com/api/offers/"
REQUEST_TIMEOUT = 20
MAX_RETRIES = 3
DELAY_BETWEEN_COMPANIES = 0.5

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "JobHunterBelgium/1.0 (recherche d'emploi personnelle)",
    "Accept": "application/json",
})


# ============================================================
# OUTILS
# ============================================================

def _clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _html_to_text(value) -> str:
    """HTML Recruitee -> texte lisible, sans dépendre de BeautifulSoup."""
    raw = str(value or "")
    raw = re.sub(r"<\s*(br|/p|/li|/div|/h[1-6])\s*/?>", "\n", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r"\n\s*\n+", "\n", raw)
    return raw.strip()


# ============================================================
# APPEL API
# ============================================================

def fetch_company_offers(identifier: str, verbose: bool = True):
    """
    Récupère les offres publiées d'un employeur.

    Renvoie (offres, erreur). Une erreur n'interrompt jamais la collecte des
    autres employeurs : le pipeline doit survivre à un employeur indisponible.
    """
    url = API_TEMPLATE.format(identifier=identifier)

    for essai in range(1, MAX_RETRIES + 1):
        try:
            response = SESSION.get(url, timeout=REQUEST_TIMEOUT)
        except Exception as error:
            if essai == MAX_RETRIES:
                return [], f"réseau : {error}"
            time.sleep(0.5 * essai)
            continue

        if response.status_code == 404:
            return [], "identifiant inconnu chez Recruitee (404)"

        if response.status_code != 200:
            if essai == MAX_RETRIES:
                return [], f"HTTP {response.status_code}"
            time.sleep(0.5 * essai)
            continue

        try:
            payload = response.json()
        except Exception as error:
            return [], f"JSON illisible : {error}"

        offers = payload.get("offers")
        if offers is None:
            return [], "réponse sans clé 'offers'"

        publiees = [
            o for o in offers
            if str(o.get("status") or "published").lower() == "published"
        ]
        return publiees, None

    return [], "échec après retries"


# ============================================================
# CONVERSION
# ============================================================

def build_matching_text(offer: dict) -> dict:
    """
    Sépare ce qui va au Matcher de ce qui reste purement corporate.

    Voir la note d'en-tête : `description` mélange les deux chez Recruitee,
    contrairement à SmartRecruiters.
    """
    titre = _clean(offer.get("title"))
    departement = _clean(offer.get("department"))
    requirements = _html_to_text(offer.get("requirements"))
    description = _html_to_text(offer.get("description"))
    corporate = _html_to_text(offer.get("sharing_description"))

    morceaux = [p for p in (titre, departement, requirements, description) if p]

    return {
        "matching_text": "\n\n".join(morceaux),
        "company_description": corporate,
        "requirements": requirements,
        "description": description,
    }


def _location_text(offer: dict) -> str:
    direct = _clean(offer.get("location"))
    if direct:
        return direct

    parties = [
        _clean(offer.get("city")),
        _clean(offer.get("state_name")),
        _clean(offer.get("country")),
    ]
    return ", ".join(p for p in parties if p)


def _belgium_status(offer: dict) -> str:
    """
    `country_code` est prioritaire : c'est une donnée structurée, donc fiable.
    Le détecteur textuel ne sert que de repli quand le champ est absent.
    """
    code = _clean(offer.get("country_code")).upper()
    if code == "BE":
        return BE_CONFIRMED
    if code:
        return analyze_location(f"{_location_text(offer)}, {code}")["status"]
    return analyze_location(_location_text(offer))["status"]


def convert_recruitee_offer(offer: dict, company: dict) -> JobOffer | None:
    identifier = company["identifier"]
    offer_id = offer.get("id")
    if not offer_id:
        return None

    ad = build_matching_text(offer)
    if not ad["matching_text"]:
        return None

    url = (
        _clean(offer.get("careers_url"))
        or _clean(offer.get("careers_apply_url"))
        or f"https://{identifier}.recruitee.com/o/{_clean(offer.get('slug'))}"
    )

    job = JobOffer(
        source="RECRUITEE",
        external_id=f"{identifier}:{offer_id}",
        title=_clean(offer.get("title")),
        company=company.get("label") or identifier,
        location=_location_text(offer),
        description=ad["matching_text"],
        url=url,
        date_published=_clean(offer.get("published_at")) or None,
        contract_type=_clean(offer.get("employment_type_code")) or None,
        language=None,
        salary=None,
        date_collected=datetime.now(timezone.utc).isoformat(),
    )

    setattr(job, "collection_channel", "RECRUITEE")
    setattr(job, "origin_source", identifier)
    setattr(job, "direct_employer", True)
    setattr(job, "source_company_identifier", identifier)

    setattr(job, "department", _clean(offer.get("department")))
    setattr(job, "experience_level", _clean(offer.get("experience_code")))
    setattr(job, "remote", bool(offer.get("remote")))
    setattr(job, "apply_url", _clean(offer.get("careers_apply_url")))

    # Exigence de diplôme en donnée structurée : rare et précieux.
    setattr(job, "degree_requirement", _clean(offer.get("education_code")) or None)

    # Corporate conservé mais hors Matcher, comme SmartRecruiters V1.1.
    setattr(job, "company_description", ad["company_description"])
    setattr(job, "job_requirements_text", ad["requirements"])

    setattr(job, "belgium_status", _belgium_status(offer))
    setattr(job, "source_eligibility_status", "ELIGIBLE")
    setattr(job, "source_eligibility_reason", None)

    return job


# ============================================================
# COLLECTE
# ============================================================

def collect_recruitee_jobs(companies=None, include_unknown_location=True,
                           verbose=True):
    companies = companies if companies is not None else enabled_companies()

    jobs = []
    rapport = []

    if verbose:
        print()
        print("=" * 76)
        print("           SOURCE - RECRUITEE (ATS PUBLIC)")
        print("=" * 76)

    for company in companies:
        identifier = company["identifier"]
        offres, erreur = fetch_company_offers(identifier, verbose=verbose)

        convertis, hors_belgique, echecs = 0, 0, 0
        for offre in offres:
            try:
                job = convert_recruitee_offer(offre, company)
            except Exception:
                echecs += 1
                continue
            if job is None:
                echecs += 1
                continue

            statut = getattr(job, "belgium_status", None)
            garder = statut in ("BE_CONFIRMED", "BE_LIKELY") or (
                include_unknown_location and statut == "BE_UNKNOWN"
            )
            if not garder:
                hors_belgique += 1
                continue

            jobs.append(job)
            convertis += 1

        ligne = {
            "identifier": identifier,
            "label": company.get("label") or identifier,
            "offers_total": len(offres),
            "converted": convertis,
            "outside_belgium": hors_belgique,
            "failures": echecs,
            "error": erreur,
        }
        rapport.append(ligne)

        if verbose:
            if erreur:
                print(f"  {ligne['label']:<20} ⚠️  {erreur}")
            else:
                print(f"  {ligne['label']:<20} total={len(offres):<4} "
                      f"BE={convertis:<4} hors BE={hors_belgique:<4} "
                      f"échecs={echecs}")

        time.sleep(DELAY_BETWEEN_COMPANIES)

    if verbose:
        print()
        print(f"RECRUITEE - offres retenues : {len(jobs)}")
        print(f"RECRUITEE - erreurs fatales : "
              f"{sum(1 for r in rapport if r['error'])}")

    return {
        "version": RECRUITEE_CONNECTOR_VERSION,
        "config_version": RECRUITEE_VERSION,
        "jobs": jobs,
        "report": rapport,
    }
