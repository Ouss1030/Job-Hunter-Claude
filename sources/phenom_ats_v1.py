"""
JOB HUNTER BELGIUM
CONNECTEUR PHENOM - VERSION 1.0

Lit les sites carrière Phenom via leur sitemap public, puis le bloc JSON-LD
`schema.org/JobPosting` présent sur chaque page d'offre.

Pourquoi ce connecteur est le plus solide du projet
---------------------------------------------------
SuccessFactors oblige à analyser la mise en page : un changement de design
le casse. Phenom expose au contraire des données structurées et
standardisées, publiées pour être lues par des machines — c'est le format
que Google for Jobs exige.

Concrètement, on obtient sans analyse de HTML :

    title            intitulé
    datePosted       date de publication
    jobLocation      pays, ville, coordonnées
    description      annonce complète (10 000 caractères chez UCB)
    employmentType   type de contrat

Le pays arrive donc en donnée, comme chez Recruitee, et non en texte libre.

Stratégie de collecte
---------------------
1. Le sitemap donne les URL d'offres.
2. Le JSON-LD de chaque page donne le pays : le filtrage belge est fiable.

Contrairement à SuccessFactors, l'URL ne contient pas la ville chez Phenom.
Il n'y a donc pas de pré-filtrage possible : toutes les offres sont
visitées, d'où un plafond par employeur et un délai entre requêtes.
"""

from __future__ import annotations

import html as html_lib
import json
import re
import time
from datetime import datetime, timezone

import requests

from config.phenom_sources import PHENOM_VERSION, enabled_companies
from database.models import JobOffer
from sources.location_belgium import detect_belgium
from sources.ats_public_v2 import declarer_detail


PHENOM_CONNECTOR_VERSION = "1.0"

REQUEST_TIMEOUT = 20
MAX_RETRIES = 2
DELAY_BETWEEN_JOBS = 0.4
DELAY_BETWEEN_COMPANIES = 1.0
MAX_JOBS_PER_COMPANY = 200
MIN_DESCRIPTION_CHARS = 300

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "JobHunterBelgium/1.0 (recherche d'emploi personnelle)",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.7",
})

_RE_JSONLD = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)


def _clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def html_to_text(fragment) -> str:
    """
    Désescape AVANT de retirer les balises.

    L'ordre inverse laisse passer le HTML échappé : "&lt;p&gt;" survit au
    retrait des balises, puis le désescapage le retransforme en "<p>" dans
    le texte final. Deux passes, certaines descriptions étant doublement
    échappées.
    """
    raw = html_lib.unescape(html_lib.unescape(str(fragment or "")))
    raw = re.sub(r"<\s*(br|/p|/li|/div|/h[1-6])\s*/?>", "\n", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = re.sub(r"<[^>]*$", " ", raw)
    raw = re.sub(r"[ \t]+", " ", raw)
    return re.sub(r"\n\s*\n+", "\n", raw).strip()


# ============================================================
# SITEMAP
# ============================================================

def fetch_sitemap_urls(host: str):
    url = f"https://{host}/sitemap.xml"
    try:
        response = SESSION.get(url, timeout=REQUEST_TIMEOUT)
    except Exception as error:
        return [], f"réseau : {error}"

    if response.status_code != 200:
        return [], f"sitemap HTTP {response.status_code}"

    urls = [u for u in re.findall(r"<loc>([^<]+)</loc>", response.text)
            if "/job/" in u]
    if not urls:
        return [], "sitemap sans URL d'offre"
    return urls, None


# ============================================================
# JSON-LD
# ============================================================

def extract_job_posting(page_html: str):
    """
    Renvoie le premier bloc JSON-LD de type JobPosting.

    Une page en porte souvent plusieurs (fil d'Ariane, organisation) : on
    ne retient que celui qui décrit le poste.
    """
    for bloc in _RE_JSONLD.findall(page_html or ""):
        try:
            donnees = json.loads(bloc.strip())
        except Exception:
            continue

        candidats = donnees if isinstance(donnees, list) else [donnees]
        for candidat in candidats:
            if not isinstance(candidat, dict):
                continue
            if candidat.get("@type") == "JobPosting":
                return candidat
    return None


def _location_text(posting: dict) -> str:
    """Reconstruit une localisation lisible depuis jobLocation."""
    lieux = posting.get("jobLocation")
    if isinstance(lieux, dict):
        lieux = [lieux]
    if not isinstance(lieux, list):
        return ""

    morceaux = []
    for lieu in lieux:
        if not isinstance(lieu, dict):
            continue
        adresse = lieu.get("address")
        if not isinstance(adresse, dict):
            continue
        parties = [
            _clean(adresse.get("addressLocality")),
            _clean(adresse.get("addressRegion")),
            _clean(adresse.get("addressCountry")
                   if isinstance(adresse.get("addressCountry"), str)
                   else (adresse.get("addressCountry") or {}).get("name")),
        ]
        texte = ", ".join(p for p in parties if p)
        if texte:
            morceaux.append(texte)

    return " ; ".join(morceaux)


def fetch_job(url: str):
    for essai in range(1, MAX_RETRIES + 1):
        try:
            response = SESSION.get(url, timeout=REQUEST_TIMEOUT)
        except Exception as error:
            if essai == MAX_RETRIES:
                return None, f"réseau : {error}"
            time.sleep(0.6 * essai)
            continue

        if response.status_code == 404:
            return None, "offre retirée (404)"
        if response.status_code != 200:
            if essai == MAX_RETRIES:
                return None, f"HTTP {response.status_code}"
            time.sleep(0.6 * essai)
            continue

        posting = extract_job_posting(response.text)
        if posting is None:
            return None, "aucun JobPosting JSON-LD"
        return posting, None

    return None, "échec après retries"


# ============================================================
# CONVERSION
# ============================================================

def convert_phenom_job(url: str, posting: dict, company: dict):
    titre = _clean(posting.get("title"))
    description = html_to_text(posting.get("description"))
    if not titre or len(description) < MIN_DESCRIPTION_CHARS:
        return None

    localisation = _location_text(posting)
    identifiant = (_clean(posting.get("identifier", {}).get("value")
                          if isinstance(posting.get("identifier"), dict)
                          else posting.get("identifier"))
                   or str(url).rstrip("/").split("/")[-2:][0])

    contrat = posting.get("employmentType")
    if isinstance(contrat, list):
        contrat = ", ".join(str(c) for c in contrat)

    offre = JobOffer(
        source="PHENOM",
        external_id=f"{company['host']}:{identifiant}",
        title=titre,
        company=company.get("label") or company["host"],
        location=localisation or _clean(posting.get("jobLocation")),
        description=f"{titre}\n\n{description}",
        url=url,
        date_published=_clean(posting.get("datePosted")) or None,
        contract_type=_clean(contrat) or None,
        language=None,
        salary=None,
        date_collected=datetime.now(timezone.utc).isoformat(),
    )

    setattr(offre, "collection_channel", "PHENOM")
    setattr(offre, "origin_source", company["host"])
    setattr(offre, "direct_employer", True)
    setattr(offre, "source_company_identifier", company["host"])
    setattr(offre, "belgium_status", detect_belgium(localisation))
    setattr(offre, "source_eligibility_status", "ELIGIBLE")
    setattr(offre, "source_eligibility_reason", None)

    # La fiche complete a ete lue : le Matcher doit le savoir (17/09/2026).
    declarer_detail(offre)

    return offre


# ============================================================
# COLLECTE
# ============================================================

def collect_phenom_jobs(companies=None, verbose=True):
    companies = companies if companies is not None else enabled_companies()

    jobs = []
    rapport = []

    if verbose:
        print()
        print("=" * 76)
        print("        SOURCE - PHENOM (SITES CARRIÈRE, VIA JSON-LD)")
        print("=" * 76)

    for company in companies:
        host = company["host"]
        urls, erreur = fetch_sitemap_urls(host)

        retenues, hors_be, echecs = 0, 0, 0
        for url in urls[:MAX_JOBS_PER_COMPANY]:
            posting, err = fetch_job(url)
            time.sleep(DELAY_BETWEEN_JOBS)

            if err or posting is None:
                echecs += 1
                continue

            try:
                offre = convert_phenom_job(url, posting, company)
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

        traitees = min(len(urls), MAX_JOBS_PER_COMPANY)
        taux = (echecs / traitees) if traitees else 0.0

        ligne = {
            "host": host,
            "label": company.get("label") or host,
            "sitemap_urls": len(urls),
            "visited": traitees,
            "retained": retenues,
            "outside_belgium": hors_be,
            "failures": echecs,
            "failure_rate": round(taux, 3),
            "jsonld_warning": bool(traitees >= 5 and taux > 0.5),
            "error": erreur,
        }
        rapport.append(ligne)

        if verbose:
            if erreur:
                print(f"  {ligne['label']:<18} ⚠️  {erreur}")
            else:
                print(f"  {ligne['label']:<18} sitemap={len(urls):<4} "
                      f"visitées={traitees:<4} BE={retenues:<4} "
                      f"hors BE={hors_be:<4} échecs={echecs} ({taux:.0%})")
                if ligne["jsonld_warning"]:
                    print("                     ⚠️  JSON-LD absent sur plus d'une "
                          "page sur deux")

        time.sleep(DELAY_BETWEEN_COMPANIES)

    if verbose:
        print()
        print(f"PHENOM - offres retenues : {len(jobs)}")

    return {
        "version": PHENOM_CONNECTOR_VERSION,
        "config_version": PHENOM_VERSION,
        "jobs": jobs,
        "report": rapport,
    }
