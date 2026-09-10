"""
JOB HUNTER BELGIUM
CONNECTEUR VDAB - VERSION 1.0

Service public flamand de l'emploi. La Flandre représente environ 43 % des
offres déjà collectées par le projet, et le VDAB n'était pas intégré.

L'hypothese de depart, et pourquoi elle etait fausse
----------------------------------------------------
L'API officielle exige des identifiants (ibm-api-key, X-IBM-Client-Id). Le
site publiant par ailleurs ses offres en sitemap, la voie sitemap paraissait
ouverte et sans contournement.

Elle ne l'est pas : le sitemap liste des URL dont le contenu n'est jamais
servi par le serveur. Voir le constat date plus bas. La verification initiale
avait ete faite avec un outil qui execute le JavaScript, ce qui donnait
l'illusion d'une page rendue cote serveur.

Lecon : verifier une page avec un outil qui rend le JavaScript ne dit rien de
ce qu'un client HTTP simple recevra. Les deux doivent etre testes.

Collecte incrémentale native
----------------------------
L'index liste 228 sitemaps enfants nommés par année et semaine :

    .../vacatures/index-2026-35-1.xml

Chacun contient environ 1 000 à 1 200 URL d'offres avec leur `lastmod`. On ne
lit donc que les semaines récentes, jamais les 228 fichiers.

ETAT AU 8 SEPTEMBRE 2026 : CONNECTEUR INOPERANT, DESACTIVE
-----------------------------------------------------------
Verifie sur 20 pages reelles : le serveur ne renvoie qu'une coquille. Le
<title> est generique ("Vind een job | VDAB"), les <h3> servis sont de la
navigation, il n'y a ni og:title, ni meta description, ni flux RSS. Le
contenu de l'offre est entierement construit en JavaScript.

Il est alimente par /api/vindeenjob/, que le robots.txt du site interdit
explicitement :

    Disallow: /api/vindeenjob/
    Disallow: /include/vacature/

La politique du projet est claire : on ne contourne pas un blocage explicite.
Ce connecteur reste donc DESACTIVE par defaut.

Ce qui reste vrai : le sitemap existe, il est declare dans robots.txt, il
liste bien ~1 000 URL par semaine et le tri par annee-semaine fonctionne. Ce
qui manque, c'est le contenu derriere ces URL.

Deux voies possibles le jour venu
---------------------------------
1. L'API officielle VDAB (ibm-api-key + X-IBM-Client-Id). C'est la voie
   propre. Le code d'analyse ci-dessous serait alors remplace par une
   lecture JSON, mais toute la partie sitemap et compteurs reste valable.
2. Un rendu navigateur des pages, qui sont elles autorisees. Techniquement
   permis, mais ~1 000 pages par semaine rend la chose lourde pour eux
   comme pour nous.

Structure attendue si la page etait servie par le serveur
---------------------------------------------------------
Contrairement à Phenom, les pages d'offres VDAB ne portent pas de bloc
schema.org/JobPosting. Il faut lire le HTML :

    <h1>                          intitulé
    "Plaats tewerkstelling"       lieu
    <h3>Functieomschrijving</h3>  début de l'annonce
    <h3>Profiel</h3>              profil recherché
    <h3>Aanbod</h3>               conditions

Cette dépendance à la mise en page est fragile par nature : le connecteur
compte ses échecs d'analyse et le signale plutôt que de les absorber en
silence.
"""

from __future__ import annotations

import html as html_lib
import re
import time
from datetime import datetime, timezone

import requests

from database.models import JobOffer
from sources.belgium_locations import classify_belgium_location


VDAB_CONNECTOR_VERSION = "1.0"

SITEMAP_INDEX = "https://www.vdab.be/sitemap/vindeenjob/vacatures/index.xml"

REQUEST_TIMEOUT = 20
MAX_RETRIES = 2
DELAY_BETWEEN_JOBS = 0.35
DELAY_BETWEEN_SITEMAPS = 1.0

# Nombre de sitemaps hebdomadaires lus, du plus récent au plus ancien.
DEFAULT_WEEKS = 2
# Plafond de sécurité : un sitemap hebdomadaire contient ~1 000 URL.
MAX_JOBS_PER_RUN = 400
MIN_DESCRIPTION_CHARS = 200

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "JobHunterBelgium/1.0 (recherche d'emploi personnelle)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "nl-BE,nl;q=0.9,fr;q=0.8,en;q=0.7",
})

_RE_LOC = re.compile(r"<loc>\s*([^<]+?)\s*</loc>", re.I)
_RE_SITEMAP_WEEK = re.compile(r"index-(\d{4})-(\d{1,2})-(\d+)\.xml\s*$", re.I)
_RE_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S | re.I)
_RE_TAG = re.compile(r"<[^>]+>")
_RE_SCRIPT = re.compile(r"<(script|style|nav|footer|header)\b.*?</\1>", re.S | re.I)


# ============================================================
# COMPTEURS
# ============================================================

COMPTEURS = (
    "seen", "detail_ok", "detail_failed",
    "geography_accepted", "geography_rejected", "geography_unknown",
    "too_short", "converted", "errors",
)


def nouveaux_compteurs() -> dict[str, int]:
    """
    Jeu de compteurs complet, initialisé à zéro.

    Initialiser explicitement plutôt que de créer les variables au fil de
    l'eau : un compteur absent devient alors visible dans le rapport, au lieu
    de disparaître silencieusement.
    """
    return {nom: 0 for nom in COMPTEURS}


# ============================================================
# TEXTE
# ============================================================

def html_to_text(fragment) -> str:
    """
    Désescape AVANT de retirer les balises.

    L'ordre inverse laisse passer le HTML échappé : "&lt;p&gt;" survit au
    retrait des balises puis redevient "<p>" dans le texte final.
    """
    raw = html_lib.unescape(html_lib.unescape(str(fragment or "")))
    raw = _RE_SCRIPT.sub(" ", raw)
    raw = re.sub(r"<\s*(br|/p|/li|/div|/h[1-6]|/section)\s*/?>", "\n", raw, flags=re.I)
    raw = _RE_TAG.sub(" ", raw)
    raw = re.sub(r"[ \t]+", " ", raw)
    return re.sub(r"\n\s*\n+", "\n", raw).strip()


def _clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


# ============================================================
# SITEMAPS
# ============================================================

def _get(url: str):
    for essai in range(1, MAX_RETRIES + 1):
        try:
            response = SESSION.get(url, timeout=REQUEST_TIMEOUT)
        except Exception as error:
            if essai == MAX_RETRIES:
                return None, f"réseau : {error}"
            time.sleep(0.6 * essai)
            continue
        if response.status_code == 404:
            return None, "404"
        if response.status_code in (403, 429, 503):
            # Blocage explicite : on s'arrête, on ne contourne pas.
            return None, f"blocage HTTP {response.status_code}"
        if response.status_code != 200:
            if essai == MAX_RETRIES:
                return None, f"HTTP {response.status_code}"
            time.sleep(0.6 * essai)
            continue
        return response.text, None
    return None, "échec après retries"


def _week_key(url: str) -> tuple[int, int, int]:
    """Clé de tri (année, semaine, partie) extraite du nom de sitemap."""
    m = _RE_SITEMAP_WEEK.search(url)
    if not m:
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def fetch_weekly_sitemaps(weeks: int = DEFAULT_WEEKS):
    """
    Renvoie les sitemaps hebdomadaires les plus récents.

    L'index en liste plus de deux cents ; les lire tous serait inutile et
    impoli. Le nommage année-semaine rend le tri fiable sans requête
    supplémentaire.
    """
    texte, erreur = _get(SITEMAP_INDEX)
    if erreur:
        return [], f"index : {erreur}"

    urls = [u for u in _RE_LOC.findall(texte) if _RE_SITEMAP_WEEK.search(u)]
    if not urls:
        return [], "index sans sitemap hebdomadaire reconnaissable"

    urls.sort(key=_week_key, reverse=True)
    return urls[:max(1, int(weeks))], None


def fetch_job_urls(sitemap_url: str):
    """URL d'offres d'un sitemap hebdomadaire."""
    texte, erreur = _get(sitemap_url)
    if erreur:
        return [], erreur
    urls = [u for u in _RE_LOC.findall(texte) if "/vindeenjob/vacatures/" in u]
    return urls, None


# ============================================================
# PAGE D'OFFRE
# ============================================================

# Intitulés de sections de l'annonce, dans l'ordre où ils apparaissent.
SECTIONS = (
    "Functieomschrijving", "Profiel", "Professionele vaardigheden",
    "Persoonlijke vaardigheden", "Aanbod", "Plaats tewerkstelling",
    "Vereiste studies", "Werkervaring", "Talenkennis",
)


def _section_text(page: str, titre: str) -> str:
    """
    Texte d'une section, délimité par son titre et le titre suivant.

    On ne s'appuie pas sur une classe CSS : elle changerait au premier
    redesign. Les intitulés de section, eux, sont du contenu métier.
    """
    m = re.search(rf"<h[23][^>]*>\s*{re.escape(titre)}\s*</h[23]>", page, re.I)
    if not m:
        return ""
    reste = page[m.end():]
    suivant = re.search(r"<h[23][^>]*>", reste, re.I)
    return html_to_text(reste[:suivant.start()] if suivant else reste[:4000])


def parse_job_page(page: str, url: str) -> dict | None:
    """Extrait les champs d'une page d'offre. None si la structure manque."""
    if not page:
        return None

    m = _RE_H1.search(page)
    titre = html_to_text(m.group(1)) if m else ""
    if not titre:
        return None

    morceaux = []
    for titre_section in SECTIONS[:5]:
        texte = _section_text(page, titre_section)
        if texte:
            morceaux.append(f"{titre_section}\n{texte}")

    lieu = _section_text(page, "Plaats tewerkstelling")

    return {
        "title": titre,
        "location": _clean(lieu),
        "description": "\n\n".join(morceaux).strip(),
        "url": url,
    }


def job_id_from_url(url: str) -> str:
    m = re.search(r"/vacatures/(\d+)", str(url or ""))
    return m.group(1) if m else str(url).rstrip("/").split("/")[-1]


def convert_vdab_job(fiche: dict) -> JobOffer | None:
    titre = _clean(fiche.get("title"))
    description = fiche.get("description") or ""
    if not titre or len(description) < MIN_DESCRIPTION_CHARS:
        return None

    lieu = _clean(fiche.get("location"))
    # Le VDAB est le service public flamand : le listing est belge par
    # nature. On le déclare comme tel plutôt que d'exiger que chaque fiche
    # répète « Belgique », ce que fait rarement une annonce locale.
    decision = classify_belgium_location(lieu, True)

    offre = JobOffer(
        source="VDAB",
        external_id=f"vdab:{job_id_from_url(fiche['url'])}",
        title=titre,
        company="",
        location=lieu,
        description=f"{titre}\n\n{description}",
        url=fiche["url"],
        date_published=None,
        contract_type=None,
        language="nl",
        salary=None,
        date_collected=datetime.now(timezone.utc).isoformat(),
    )
    setattr(offre, "collection_channel", "VDAB")
    setattr(offre, "origin_source", "vdab.be")
    setattr(offre, "direct_employer", False)
    setattr(offre, "belgium_status", decision.status)
    setattr(offre, "source_eligibility_status", "ELIGIBLE")
    setattr(offre, "source_eligibility_reason", None)
    return offre


# ============================================================
# COLLECTE
# ============================================================

def collect_vdab_jobs(weeks: int = DEFAULT_WEEKS,
                      max_jobs: int = MAX_JOBS_PER_RUN,
                      verbose: bool = True) -> dict:
    compteurs = nouveaux_compteurs()
    jobs: list[JobOffer] = []
    erreurs: list[str] = []

    if verbose:
        print()
        print("=" * 76)
        print("        SOURCE - VDAB (SITEMAP PUBLIC)")
        print("=" * 76)

    sitemaps, erreur = fetch_weekly_sitemaps(weeks)
    if erreur:
        erreurs.append(erreur)
        compteurs["errors"] += 1
        if verbose:
            print(f"  ⚠️  {erreur}")
        return {"version": VDAB_CONNECTOR_VERSION, "jobs": [],
                "compteurs": compteurs, "erreurs": erreurs}

    vues = 0
    for sitemap in sitemaps:
        urls, err = fetch_job_urls(sitemap)
        if err:
            erreurs.append(f"{sitemap} : {err}")
            compteurs["errors"] += 1
            continue

        if verbose:
            print(f"  {sitemap.rsplit('/', 1)[-1]:<28} {len(urls)} URL")

        for url in urls:
            if vues >= max_jobs:
                break
            vues += 1
            compteurs["seen"] += 1

            page, err = _get(url)
            time.sleep(DELAY_BETWEEN_JOBS)
            if err or not page:
                compteurs["detail_failed"] += 1
                continue
            compteurs["detail_ok"] += 1

            fiche = parse_job_page(page, url)
            if fiche is None:
                compteurs["detail_failed"] += 1
                continue

            offre = convert_vdab_job(fiche)
            if offre is None:
                compteurs["too_short"] += 1
                continue

            statut = getattr(offre, "belgium_status", "UNKNOWN")
            if statut == "FOREIGN":
                compteurs["geography_rejected"] += 1
                continue
            if statut == "UNKNOWN":
                # Comptée à part : une localisation illisible n'est pas une
                # offre étrangère, elle mérite une vérification.
                compteurs["geography_unknown"] += 1
            else:
                compteurs["geography_accepted"] += 1

            jobs.append(offre)
            compteurs["converted"] += 1

        time.sleep(DELAY_BETWEEN_SITEMAPS)
        if vues >= max_jobs:
            break

    if verbose:
        print()
        for nom in COMPTEURS:
            print(f"  {nom:<22}{compteurs[nom]:>6}")
        # Un taux d'échec élevé signale une page redessinée, pas une absence
        # d'offres : les deux demandent des actions opposées.
        traitees = compteurs["seen"] or 1
        taux = compteurs["detail_failed"] / traitees
        if traitees >= 10 and taux > 0.5:
            print("  ⚠️  Plus d'une page sur deux n'a pas pu être analysée : "
                  "la mise en page VDAB a probablement changé.")
        print(f"\nVDAB - offres retenues : {len(jobs)}")

    return {
        "version": VDAB_CONNECTOR_VERSION,
        "jobs": jobs,
        "compteurs": compteurs,
        "erreurs": erreurs,
    }
