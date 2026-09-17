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
from sources.ats_public_v2 import declarer_detail


SUCCESSFACTORS_CONNECTOR_VERSION = "1.2"

REQUEST_TIMEOUT = 20
MAX_RETRIES = 2
DELAY_BETWEEN_JOBS = 0.5
DELAY_BETWEEN_COMPANIES = 1.0
MAX_JOBS_PER_COMPANY = 90
MAX_JOBS_PER_COMPANY_BE = 300

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

    texte = response.text
    entete = texte[:600].lower()

    # V1.1 (15/09/2026) — trois formes constatees sur les sites SuccessFactors :
    #   urlset  (Umicore, Puratos, VUB, Bekaert)  : <loc> des pages /job/
    #   rss     (Barry-Callebaut)                  : un flux Google Jobs, <item><link>
    #   index   (Colruyt)                          : <sitemapindex> vers des sous-sitemaps
    if "<rss" in entete:
        urls = [u.strip() for u in re.findall(r"<link>([^<]+)</link>", texte) if "/job/" in u]
    elif "<sitemapindex" in entete:
        urls = []
        for enfant in re.findall(r"<loc>([^<]+)</loc>", texte)[:12]:
            try:
                sous = SESSION.get(enfant.strip(), timeout=REQUEST_TIMEOUT)
            except Exception:
                continue
            if sous.status_code == 200:
                urls.extend(u for u in re.findall(r"<loc>([^<]+)</loc>", sous.text) if "/job/" in u)
    else:
        urls = [u for u in re.findall(r"<loc>([^<]+)</loc>", texte) if "/job/" in u]
    import html as _html
    urls = list(dict.fromkeys(_html.unescape(u) for u in urls))
    if not urls:
        return [], "sitemap sans URL d'offre"
    return urls, None


# V1.2 (17/09/2026) — sans sitemap exploitable (jobs.ulb.be, jobs.elia.be,
# careers.novonordisk.com, jobs.barry-callebaut.com : sitemap vide ou sans
# /job/), la page de recherche du site rend la liste en HTML :
#     https://{host}/search/?q=&startrow=0   (25 ou 100 lignes par page)
# chaque ligne = lien /job/<Ville-Titre>/<id>/ + colonne lieu. On ne garde
# que les lignes dont le lieu est belge, avant de charger les pages.
SEARCH_MAX_PAGES = 40
_RE_LIGNE = re.compile(r'<tr[^>]*class="[^"]*data-row[^"]*"[^>]*>(.*?)</tr>', re.S | re.I)
_RE_LIEN_JOB = re.compile(r'href="(/job/[^"]+)"', re.I)
_RE_LIEU = re.compile(r'class="[^"]*jobLocation[^"]*"[^>]*>(.*?)</', re.S | re.I)


def fetch_search_urls(host: str, max_pages: int = SEARCH_MAX_PAGES):
    """Liste HTML /search/ : renvoie ([(url, lieu)], erreur)."""
    import html as _html
    lignes, vus, startrow, pas = [], set(), 0, None
    for _ in range(max_pages):
        url = f"https://{host}/search/?q=&startrow={startrow}"
        try:
            r = SESSION.get(url, timeout=REQUEST_TIMEOUT)
        except Exception as error:
            return lignes, f"réseau : {error}"
        if r.status_code != 200:
            break
        rangs = _RE_LIGNE.findall(r.text)
        if not rangs:
            break
        nouveaux = 0
        for rang in rangs:
            m = _RE_LIEN_JOB.search(rang)
            if not m:
                continue
            u = f"https://{host}" + _html.unescape(m.group(1))
            if u in vus:
                continue
            vus.add(u)
            nouveaux += 1
            ml = _RE_LIEU.search(rang)
            lignes.append((u, _clean(_html.unescape(re.sub(r"<[^>]+>", " ", ml.group(1)))) if ml else ""))
        if not nouveaux:
            break
        pas = pas or len(rangs)
        startrow += pas
        time.sleep(DELAY_BETWEEN_JOBS)
    if not lignes:
        return [], "page de recherche sans offre"
    return lignes, None


def lister_offres(host: str):
    """
    (candidates belges, total liste, erreur) : sitemap d'abord (V1.1), sinon
    la page de recherche HTML (V1.2). Sur la liste HTML, le lieu de la ligne
    remplace le pre-filtre sur le slug.
    """
    urls, erreur = fetch_sitemap_urls(host)
    if urls:
        return [u for u in urls if looks_belgian_url(u)], len(urls), None
    lignes, erreur2 = fetch_search_urls(host)
    if not lignes:
        return [], 0, erreur2 or erreur
    candidates = [u for u, lieu in lignes
                  if detect_belgium(lieu) in ("BE_CONFIRMED", "BE_LIKELY") or (not lieu and looks_belgian_url(u))]
    return candidates, len(lignes), None


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

    # La fiche complete a ete lue : le Matcher doit le savoir (17/09/2026).
    declarer_detail(offre)

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
        candidates, total_liste, erreur = lister_offres(host)
        urls = range(total_liste)  # seul len() est utilise dans le rapport
        retenues, hors_be, echecs = 0, 0, 0
        # V1.1 — plafond par employeur : "max_jobs" dans la config, sinon
        # 300 pour un hote .be (il ne publie que pour la Belgique : Infrabel,
        # SNCB, Belfius, Multipharma butaient sur 90), sinon 90.
        plafond = int(company.get("max_jobs") or
                      (MAX_JOBS_PER_COMPANY_BE if host.lower().endswith(".be") else MAX_JOBS_PER_COMPANY))

        for url in candidates[:plafond]:
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
        traitees = min(len(candidates), plafond)
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
