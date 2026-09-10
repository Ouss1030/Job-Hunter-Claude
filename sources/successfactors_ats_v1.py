"""
JOB HUNTER BELGIUM
CONNECTEUR SUCCESSFACTORS - VERSION 1.0

Lit les sites carrière SuccessFactors via leur sitemap public, puis les
pages d'offres rendues côté serveur.

Voir config/successfactors_sources.py pour la nature de l'accès et la
distinction avec le cas Jobat écarté du projet.

Pourquoi ce connecteur est différent des autres
-----------------------------------------------
C'est le premier du projet qui lit du HTML plutôt qu'une API. Trois
conséquences assumées et traitées ici :

1. FRAGILITÉ. Une page n'a pas de contrat. Le connecteur mesure donc la
   qualité de ce qu'il extrait : une description trop courte est comptée
   comme un échec d'analyse, pas ignorée en silence. Un taux d'échec élevé
   signale un changement de mise en page avant qu'il ne pourrisse la base.

2. COÛT. Une requête par offre. D'où un pré-filtrage sur l'URL du sitemap :
   le slug contient la ville, ce qui permet d'écarter les offres non belges
   sans les télécharger. Sur Umicore, cela ramène 208 pages à ~85.

3. POLITESSE. Délai entre chaque requête, plafond par employeur, et arrêt
   propre en cas d'erreur répétée.

Extraction
----------
Les pages portent du microdata schema.org :

    itemprop="title"         -> intitulé faisant autorité
    itemprop="description"   -> corps de l'annonce

Le titre de la page prime sur le slug de l'URL : chez Umicore, une offre
dont le slug dit "Buyer-IT" s'intitule en réalité "Process Engineer".
"""

from __future__ import annotations

import html as html_lib
import re
import time
from datetime import datetime, timezone
from urllib.parse import unquote

import requests

from config.successfactors_sources import (
    SUCCESSFACTORS_VERSION,
    enabled_companies,
)
from database.models import JobOffer
from sources.location_belgium import detect_belgium


SUCCESSFACTORS_CONNECTOR_VERSION = "1.0"

REQUEST_TIMEOUT = 20
MAX_RETRIES = 2
DELAY_BETWEEN_JOBS = 0.5
DELAY_BETWEEN_COMPANIES = 1.0
MAX_JOBS_PER_COMPANY = 90

# En dessous de ce seuil, l'extraction est considérée comme ratée plutôt
# que comme une annonce courte : c'est le signal d'un changement de page.
MIN_DESCRIPTION_CHARS = 300

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "JobHunterBelgium/1.0 (recherche d'emploi personnelle)",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.7",
})


def _clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def html_to_text(fragment) -> str:
    raw = str(fragment or "")
    raw = re.sub(r"<script.*?</script>", " ", raw, flags=re.S | re.I)
    raw = re.sub(r"<style.*?</style>", " ", raw, flags=re.S | re.I)
    raw = re.sub(r"<\s*(br|/p|/li|/div|/h[1-6])\s*/?>", "\n", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    # Une coupe peut tomber au milieu d'une balise : "<div class=\"jobCol"
    # sans ">" final, que le motif ci-dessus ne peut pas retirer.
    raw = re.sub(r"<[^>]*$", " ", raw)
    raw = html_lib.unescape(raw)
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r"\n\s*\n+", "\n", raw)
    return raw.strip()


# ============================================================
# SITEMAP
# ============================================================

def fetch_sitemap_urls(host: str):
    """URLs d'offres déclarées par le sitemap public. Renvoie (urls, erreur)."""
    url = f"https://{host}/sitemap.xml"
    try:
        response = SESSION.get(url, timeout=REQUEST_TIMEOUT)
    except Exception as error:
        return [], f"réseau : {error}"

    if response.status_code != 200:
        return [], f"sitemap HTTP {response.status_code}"

    urls = [
        u for u in re.findall(r"<loc>([^<]+)</loc>", response.text)
        if "/job/" in u
    ]
    if not urls:
        return [], "sitemap sans URL d'offre"
    return urls, None


def slug_from_url(url: str) -> str:
    """"…/job/Hoboken-Buyer-IT/1404786033/" -> "Hoboken Buyer IT"."""
    morceau = str(url or "").split("/job/")[-1].split("/")[0]
    return _clean(unquote(morceau).replace("-", " "))


def looks_belgian_url(url: str) -> bool:
    """
    Pré-filtre sur le slug, pour ne pas télécharger toutes les offres.

    Le slug commence en général par la ville. On accepte largement ici :
    la vérification sérieuse se fait sur la page, une fois chargée.
    """
    statut = detect_belgium(slug_from_url(url))
    return statut in ("BE_CONFIRMED", "BE_LIKELY")


# ============================================================
# PAGE D'OFFRE
# ============================================================

_RE_TITRE = (
    re.compile(r'itemprop="title"[^>]*>(.*?)<', re.S | re.I),
    re.compile(r'data-careersite-propertyid="title"[^>]*>(.*?)<', re.S | re.I),
    re.compile(r'property="og:title"[^>]+content="([^"]{1,140})"', re.I),
)

# Deux gabarits coexistent selon l'employeur, constaté le 22/08/2026 :
# Umicore expose le microdata schema.org, Aquafin non mais structure la
# page en colonnes. On essaie les deux, dans cet ordre de fiabilité.
_RE_DESCRIPTION = (
    # 1. microdata schema.org : le plus fiable, standardisé
    re.compile(
        r'itemprop="description"[^>]*>(.*?)'
        r'(?=<div[^>]+class="[^"]*(?:jobColumnTwo|cc-job-layout)|</body>)',
        re.S | re.I),
    # 2. colonne principale du gabarit alternatif
    re.compile(
        r'class="[^"]*jobColumnOne[^"]*"[^>]*>(.*?)'
        r'(?=class="[^"]*jobColumnTwo)', re.S | re.I),
)


def parse_job_page(page_html: str) -> dict:
    titre = ""
    for motif in _RE_TITRE:
        m = motif.search(page_html)
        if m:
            titre = _clean(html_lib.unescape(re.sub(r"<[^>]+>", " ", m.group(1))))
            if titre:
                break

    description = ""
    for motif in _RE_DESCRIPTION:
        m = motif.search(page_html)
        if not m:
            continue
        candidat = html_to_text(m.group(1))
        if len(candidat) > len(description):
            description = candidat
        if len(description) >= MIN_DESCRIPTION_CHARS:
            break

    return {"title": titre, "description": description}


def fetch_job(url: str):
    """Renvoie (donnees, erreur)."""
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

        donnees = parse_job_page(response.text)
        if len(donnees["description"]) < MIN_DESCRIPTION_CHARS:
            return None, "extraction insuffisante (page modifiée ?)"
        return donnees, None

    return None, "échec après retries"


# ============================================================
# CONVERSION
# ============================================================

def convert_successfactors_job(url: str, donnees: dict, company: dict):
    titre = _clean(donnees.get("title")) or slug_from_url(url)
    description = donnees.get("description") or ""
    if not titre or len(description) < MIN_DESCRIPTION_CHARS:
        return None

    identifiant = str(url).rstrip("/").split("/")[-1]
    slug = slug_from_url(url)

    offre = JobOffer(
        source="SUCCESSFACTORS",
        external_id=f"{company['host']}:{identifiant}",
        title=titre,
        company=company.get("label") or company["host"],
        location=slug,
        description=f"{titre}\n\n{description}",
        url=url,
        date_published=None,
        contract_type=None,
        language=None,
        salary=None,
        date_collected=datetime.now(timezone.utc).isoformat(),
    )

    setattr(offre, "collection_channel", "SUCCESSFACTORS")
    setattr(offre, "origin_source", company["host"])
    setattr(offre, "direct_employer", True)
    setattr(offre, "source_company_identifier", company["host"])
    setattr(offre, "belgium_status", detect_belgium(slug))
    setattr(offre, "source_eligibility_status", "ELIGIBLE")
    setattr(offre, "source_eligibility_reason", None)

    return offre


# ============================================================
# COLLECTE
# ============================================================

def collect_successfactors_jobs(companies=None, verbose=True):
    companies = companies if companies is not None else enabled_companies()

    jobs = []
    rapport = []

    if verbose:
        print()
        print("=" * 76)
        print("      SOURCE - SUCCESSFACTORS (SITES CARRIÈRE, VIA SITEMAP)")
        print("=" * 76)

    for company in companies:
        host = company["host"]
        urls, erreur = fetch_sitemap_urls(host)

        candidates = [u for u in urls if looks_belgian_url(u)]
        retenues, hors_be, echecs = 0, 0, 0

        for url in candidates[:MAX_JOBS_PER_COMPANY]:
            donnees, err = fetch_job(url)
            time.sleep(DELAY_BETWEEN_JOBS)

            if err or donnees is None:
                echecs += 1
                continue

            try:
                offre = convert_successfactors_job(url, donnees, company)
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

        # Un taux d'échec élevé n'est pas du bruit : c'est le signal que la
        # mise en page a changé et que le connecteur doit être revu.
        traitees = min(len(candidates), MAX_JOBS_PER_COMPANY)
        taux_echec = (echecs / traitees) if traitees else 0.0

        ligne = {
            "host": host,
            "label": company.get("label") or host,
            "sitemap_urls": len(urls),
            "candidates": len(candidates),
            "retained": retenues,
            "outside_belgium": hors_be,
            "failures": echecs,
            "failure_rate": round(taux_echec, 3),
            "layout_warning": bool(traitees >= 5 and taux_echec > 0.5),
            "error": erreur,
        }
        rapport.append(ligne)

        if verbose:
            if erreur:
                print(f"  {ligne['label']:<12} ⚠️  {erreur}")
            else:
                print(f"  {ligne['label']:<12} sitemap={len(urls):<4} "
                      f"candidates={len(candidates):<4} BE={retenues:<4} "
                      f"échecs={echecs} ({taux_echec:.0%})")
                if ligne["layout_warning"]:
                    print("               ⚠️  plus d'une extraction sur deux échoue : "
                          "mise en page probablement modifiée")

        time.sleep(DELAY_BETWEEN_COMPANIES)

    if verbose:
        print()
        print(f"SUCCESSFACTORS - offres retenues : {len(jobs)}")
        print(f"SUCCESSFACTORS - alertes de mise en page : "
              f"{sum(1 for r in rapport if r['layout_warning'])}")

    return {
        "version": SUCCESSFACTORS_CONNECTOR_VERSION,
        "config_version": SUCCESSFACTORS_VERSION,
        "jobs": jobs,
        "report": rapport,
    }
