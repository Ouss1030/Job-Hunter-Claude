"""
JOB HUNTER BELGIUM
EXTRACTEUR UNIVERSEL - SITEMAP + JSON-LD JOBPOSTING - VERSION 1.0

N'importe quel site carriere qui (1) declare ses offres dans un sitemap et
(2) porte un bloc schema.org/JobPosting sur chaque page devient une source,
sans connecteur dedie. C'est le cas de Teamtailor, Jobtoolz, Talentfinder,
Radancy, Phenom, et de beaucoup de sites carriere maison : Google for Jobs
exige ce balisage, les employeurs le posent donc.

    extraire_offre(url)            -> une URL publique d'offre, un JobOffer
    collect_site(host, label)      -> tout un site carriere via son sitemap

Ce qui est reutilise
--------------------
sources/phenom_ats_v1.py savait deja lire un sitemap et un JobPosting, mais
pour un hote Phenom et un chemin /job/. Les fonctions de lecture JSON-LD,
de localisation et de nettoyage HTML sont reprises telles quelles ; la
decouverte des sitemaps (robots.txt, index, sous-sitemaps) et la
reconnaissance des URL d'offres sont generalisees ici.

Cout et bornes
--------------
Une offre = une page. Par site et par run : au plus MAX_PAGES_PAR_SITE
pages nouvelles ; les pages deja lues sont relues depuis le cache disque
tant que leur lastmod n'a pas change. Un site de 60 offres coute donc 60
pages la premiere fois, puis presque rien.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests

from database.models import JobOffer
from sources.location_belgium import detect_belgium_multi, BE_CONFIRMED, BE_LIKELY, BE_UNKNOWN
from sources.phenom_ats_v1 import extract_job_posting, html_to_text, _location_text


JSONLD_SITEMAP_VERSION = "1.4"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "logs" / "jsonld_sites_cache"

TIMEOUT = 20
PAUSE_ENTRE_PAGES = 0.35
MAX_PAGES_PAR_SITE = 150
MAX_SOUS_SITEMAPS = 40
CACHE_MAX_AGE_JOURS = 7
MIN_DESCRIPTION = 150

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/151.0 Safari/537.36 JobHunter/jsonld"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-BE,fr;q=0.9,nl;q=0.8,en;q=0.7",
}

SITEMAPS_USUELS = ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml",
                   "/jobs-sitemap.xml", "/job-sitemap.xml", "/careers-sitemap.xml",
                   "/vacatures-sitemap.xml", "/sitemap/jobs.xml", "/sitemaps/jobs.xml")

# Une URL d'offre a un segment "job" ET quelque chose apres (un identifiant,
# un slug) : /jobs/1234-analyst oui, /jobs/ non.
_RE_URL_OFFRE = re.compile(
    r"/(?:jobs?|vacatures?|vacature|vacancies|vacancy|offres?(?:-d-?emploi)?|emplois?|"
    r"positions?|openings?|o|stellen(?:angebote)?|job-openings|jobs-carrieres|postes?|"
    r"job-details?|jobdetails?|vacancy-details?)/[^/?#]{2,}", re.I)
_RE_EXCLURE = re.compile(r"/(?:page|category|categorie|tag|department|departement|location|"
                         r"locations|search|zoeken|recherche|filter|feed|rss)(?:/|$)|\.(?:pdf|jpg|png)$", re.I)
_RE_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
_RE_URLBLOC = re.compile(r"<url>(.*?)</url>", re.I | re.S)
_RE_LASTMOD = re.compile(r"<lastmod>\s*([^<\s]+)\s*</lastmod>", re.I)


def _clean(value) -> str:
    return "" if value is None else str(value).strip()


def _get(url: str, session):
    return session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)


# ------------------------------------------------------------------
# Sitemaps
# ------------------------------------------------------------------

def _sitemaps_depuis_robots(host: str, session) -> list[str]:
    try:
        r = _get(f"https://{host}/robots.txt", session)
        if r.status_code != 200:
            return []
        return [l.split(":", 1)[1].strip() for l in r.text.splitlines()
                if l.lower().startswith("sitemap:")]
    except Exception:
        return []


def _lire_sitemap(url: str, session) -> tuple[list[tuple[str, str]], list[str]]:
    """Rend (offres [(url, lastmod)], sous-sitemaps)."""
    try:
        r = _get(url, session)
    except Exception:
        return [], []
    if r.status_code != 200 or "<" not in r.text[:200]:
        return [], []
    texte = r.text
    if "<sitemapindex" in texte[:2000].lower():
        return [], _RE_LOC.findall(texte)
    entrees = []
    blocs = _RE_URLBLOC.findall(texte)
    if blocs:
        for bloc in blocs:
            loc = _RE_LOC.search(bloc)
            if not loc:
                continue
            lm = _RE_LASTMOD.search(bloc)
            entrees.append((loc.group(1).strip(), lm.group(1).strip() if lm else ""))
    else:
        entrees = [(u, "") for u in _RE_LOC.findall(texte)]
    return entrees, []


def _est_url_offre(url: str, host: str) -> bool:
    try:
        p = urlsplit(url)
    except Exception:
        return False
    if p.netloc.lower().removeprefix("www.") != host.lower().removeprefix("www."):
        return False
    if _RE_EXCLURE.search(p.path):
        return False
    return bool(_RE_URL_OFFRE.search(p.path))


def urls_offres(host: str, session, max_urls: int = 2000,
                max_sitemaps: int = MAX_SOUS_SITEMAPS) -> tuple[list[tuple[str, str]], str | None]:
    """Toutes les URL d'offres d'un hote, avec lastmod quand il existe."""
    host = host.lower().removeprefix("https://").removeprefix("http://").strip("/")
    candidats = _sitemaps_depuis_robots(host, session) or []
    candidats += [f"https://{host}{c}" for c in SITEMAPS_USUELS]
    vus_sitemaps: set[str] = set()
    offres: dict[str, str] = {}
    file = list(dict.fromkeys(candidats))
    lus = 0
    while file and lus < max_sitemaps and len(offres) < max_urls:
        sm = file.pop(0)
        if sm in vus_sitemaps:
            continue
        vus_sitemaps.add(sm)
        entrees, enfants = _lire_sitemap(sm, session)
        lus += 1
        # Les sous-sitemaps qui parlent d'offres passent devant.
        enfants.sort(key=lambda u: 0 if re.search(r"job|vacatur|vacan|offre|emploi|career|position", u, re.I) else 1)
        file = enfants + file
        for url, lastmod in entrees:
            if _est_url_offre(url, host) and url not in offres:
                offres[url] = lastmod
        if offres and not enfants and lus >= 1 and sm.endswith(SITEMAPS_USUELS[0]):
            # sitemap.xml simple et productif : inutile de tester les autres noms usuels
            file = [f for f in file if not f.endswith(SITEMAPS_USUELS)]
    if not offres:
        return [], "aucune URL d'offre dans les sitemaps"
    return plus_recentes_d_abord(list(offres.items())), None


_RE_DATE_URL = re.compile(r"(?<!\d)(20\d\d)[-_/.]?(0[1-9]|1[0-2])(?:[-_/.]?(0[1-9]|[12]\d|3[01]))?(?!\d)")


def plus_recentes_d_abord(entrees: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """
    Un sitemap sans lastmod mais dont les URL portent une date (jobsin.brussels :
    /jobs/…-2026-09/, 8 665 URL dont des archives depuis 2024) : les plus recentes
    passent devant, pour que le plafond de pages par site lise les offres vivantes
    et non les archives. Sans date dans les URL, l'ordre du sitemap est conserve.
    """
    def cle(e):
        url, lastmod = e
        if lastmod:
            return lastmod[:10]
        m = _RE_DATE_URL.search(url)
        return f"{m.group(1)}-{m.group(2)}-{m.group(3) or '00'}" if m else ""
    if not any(cle(e) for e in entrees):
        return entrees
    return sorted(entrees, key=cle, reverse=True)


# ------------------------------------------------------------------
# Une page -> une offre
# ------------------------------------------------------------------

def _cache_path(host: str) -> Path:
    return CACHE_DIR / f"{re.sub(r'[^a-z0-9.-]+', '_', host.lower())}.json"


def _charger_cache(host: str) -> dict:
    chemin = _cache_path(host)
    if chemin.exists():
        try:
            return json.loads(chemin.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _ecrire_cache(host: str, cache: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(host).write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _pays(posting: dict) -> str:
    lieux = posting.get("jobLocation")
    if isinstance(lieux, dict):
        lieux = [lieux]
    codes = []
    for lieu in lieux or []:
        adresse = (lieu or {}).get("address") if isinstance(lieu, dict) else None
        if isinstance(adresse, dict):
            pays = adresse.get("addressCountry")
            if isinstance(pays, dict):
                pays = pays.get("name")
            if pays:
                codes.append(_clean(pays).upper())
    return ",".join(codes)


def _statut(posting: dict) -> tuple[str, str]:
    localisation = _location_text(posting)
    pays = _pays(posting)
    if "BE" in pays.split(",") or "BELGIUM" in pays or "BELGIQUE" in pays or "BELGIË" in pays:
        return BE_CONFIRMED, localisation
    if pays and all(c not in ("", "BE") for c in pays.split(",")):
        st = detect_belgium_multi(localisation)
        return (st if st == BE_CONFIRMED else "BE_EXCLUDED"), localisation
    return detect_belgium_multi(localisation), localisation


def convertir_posting(url: str, posting: dict, source: str, host: str, label: str) -> JobOffer | None:
    titre = _clean(posting.get("title"))
    description = html_to_text(posting.get("description"))
    if not titre or len(description) < MIN_DESCRIPTION:
        return None
    statut, localisation = _statut(posting)
    org = posting.get("hiringOrganization")
    entreprise = _clean(org.get("name")) if isinstance(org, dict) else _clean(org)
    ident = _clean(posting.get("identifier", {}).get("value")) if isinstance(posting.get("identifier"), dict) \
        else _clean(posting.get("identifier"))
    if not ident:
        ident = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    types = posting.get("employmentType")
    if isinstance(types, list):
        types = ", ".join(_clean(t) for t in types)
    sal = posting.get("baseSalary")
    salaire = None
    if isinstance(sal, dict):
        val = sal.get("value")
        if isinstance(val, dict):
            salaire = " ".join(_clean(val.get(k)) for k in ("minValue", "maxValue", "unitText") if val.get(k))
    job = JobOffer(
        source=source, external_id=f"{host}:{ident}", title=titre,
        company=entreprise or label or host, location=localisation or "Lieu non précisé",
        description=description, url=_clean(posting.get("url")) or url,
        date_published=_clean(posting.get("datePosted"))[:10] or None,
        contract_type=_clean(types) or None, language=None, salary=salaire,
        date_collected=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    job.collection_channel = source
    job.origin_source = host
    job.location_status = statut
    job.detail_enrichment_attempted = True
    job.detail_enrichment_success = True
    job.detail_matching_text_length = len(description)
    if posting.get("validThrough"):
        job.application_deadline = _clean(posting.get("validThrough"))[:10]
    return job


def extraire_offre(url: str, session=None, source: str = "JSONLD_SITES") -> tuple[JobOffer | None, str | None]:
    """L'extracteur universel : une URL publique, un JobOffer si la page porte un JobPosting."""
    session = session or requests.Session()
    try:
        r = _get(url, session)
    except Exception as e:
        return None, f"réseau : {e}"
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}"
    posting = extract_job_posting(r.text)
    if not posting:
        return None, "aucun JobPosting JSON-LD"
    host = urlsplit(r.url).netloc.lower()
    job = convertir_posting(r.url, posting, source, host, "")
    return job, (None if job else "titre ou description insuffisants")


# ------------------------------------------------------------------
# Un site entier
# ------------------------------------------------------------------

def collect_site(host: str, label: str, session=None, include_unknown: bool = True,
                 max_pages: int = MAX_PAGES_PAR_SITE, source: str = "JSONLD_SITES",
                 verbose: bool = False, max_sitemaps: int = MAX_SOUS_SITEMAPS) -> tuple[list[JobOffer], dict]:
    session = session or requests.Session()
    host = host.lower().removeprefix("https://").removeprefix("http://").strip("/")
    entrees, erreur = urls_offres(host, session, max_sitemaps=max_sitemaps)
    if erreur:
        return [], {"host": host, "label": label, "sitemap_urls": 0, "cache": 0, "visitees": 0,
                    "sans_jsonld": 0, "be": 0, "hors_be": 0, "echecs": 0, "error": erreur}
    return collect_pages(host, label, entrees, session, include_unknown=include_unknown,
                         max_pages=max_pages, source=source, verbose=verbose)


def collect_pages(host: str, label: str, entrees: list[tuple[str, str]], session=None,
                  include_unknown: bool = True, max_pages: int = MAX_PAGES_PAR_SITE,
                  source: str = "JSONLD_SITES", verbose: bool = False) -> tuple[list[JobOffer], dict]:
    """
    Le coeur de l'extracteur : des URL d'offres (avec lastmod ou "") vers des
    JobOffer, avec cache par page. collect_site les tire du sitemap ; un
    connecteur qui les obtient autrement (iCIMS : liste paginee) appelle
    directement cette fonction.
    """
    session = session or requests.Session()
    host = host.lower().removeprefix("https://").removeprefix("http://").strip("/")
    meta = {"host": host, "label": label, "sitemap_urls": len(entrees), "cache": 0, "visitees": 0,
            "sans_jsonld": 0, "be": 0, "hors_be": 0, "echecs": 0, "error": None}
    cache = _charger_cache(host)
    maintenant = datetime.now(timezone.utc)
    jobs = []
    nouvelles = 0
    for url, lastmod in entrees:
        entree = cache.get(url)
        frais = False
        if entree:
            try:
                age = (maintenant - datetime.fromisoformat(entree["lu"])).days
            except Exception:
                age = 999
            frais = (lastmod and entree.get("lastmod") == lastmod) or (not lastmod and age < CACHE_MAX_AGE_JOURS)
        if frais:
            posting = entree.get("posting")
            meta["cache"] += 1
        else:
            if nouvelles >= max_pages:
                continue
            nouvelles += 1
            meta["visitees"] += 1
            try:
                r = _get(url, session)
                posting = extract_job_posting(r.text) if r.status_code == 200 else None
                if r.status_code == 404:
                    cache.pop(url, None)
                    continue
            except Exception:
                meta["echecs"] += 1
                continue
            cache[url] = {"lu": maintenant.isoformat(), "lastmod": lastmod, "posting": posting}
            time.sleep(PAUSE_ENTRE_PAGES)
        if not posting:
            meta["sans_jsonld"] += 1
            continue
        job = convertir_posting(url, posting, source, host, label)
        if not job:
            meta["echecs"] += 1
            continue
        statut = getattr(job, "location_status", BE_UNKNOWN)
        if statut in (BE_CONFIRMED, BE_LIKELY) or (statut == BE_UNKNOWN and include_unknown):
            jobs.append(job)
            meta["be"] += 1
        else:
            meta["hors_be"] += 1
    _ecrire_cache(host, cache)
    if verbose:
        print(f"  {label:<24} sitemap={meta['sitemap_urls']:<4} cache={meta['cache']:<4} "
              f"visitées={meta['visitees']:<4} BE={meta['be']:<4} hors BE={meta['hors_be']:<3} "
              f"sans JSON-LD={meta['sans_jsonld']}")
    return jobs, meta


def _inconnu_accepte(host: str, company: dict, defaut: bool | None) -> bool:
    """
    Faut-il garder une offre dont la localisation n'est pas reconnue ?

    Un hote en .be publie pour la Belgique : "Merelbeke, Merelbeke" chez
    Actief est belge meme si la commune n'est pas dans la liste. Un site
    carriere mondial (.com) sans pays dans son JSON-LD ne l'est pas par
    defaut : 80 offres AbbVie (Sligo, Shanghai...) etaient passees ainsi
    le 15/09/2026. La config peut trancher avec "include_unknown".
    """
    if company.get("include_unknown") is not None:
        return bool(company["include_unknown"])
    if defaut is not None:
        return defaut
    return host.lower().rstrip("/").endswith(".be")


SITES_EN_PARALLELE = 4


def collect_sites(companies: list[dict], verbose: bool = True,
                  include_unknown: bool | None = None, workers: int = SITES_EN_PARALLELE) -> dict:
    """
    Tous les sites, quatre a la fois (V1.3, 16/09/2026).

    Sequentiel, 56 sites a 150 pages et 0,35 s de pause pouvaient prendre
    cinquante minutes sur une premiere passe. Les sites sont independants
    (une session et un fichier de cache par hote) : on les lit en parallele,
    la pause entre pages restant par site — la charge par serveur ne change pas.
    """
    from concurrent.futures import ThreadPoolExecutor

    actifs = [c for c in companies if c.get("enabled", True)]

    def _un(c):
        host = _clean(c.get("identifier"))
        label = _clean(c.get("label")) or host
        try:
            trouves, meta = collect_site(host, label, requests.Session(),
                                         include_unknown=_inconnu_accepte(host, c, include_unknown),
                                         verbose=verbose)
            return trouves, meta
        except Exception as erreur:
            meta = {"host": host, "label": label, "error": f"{type(erreur).__name__}: {erreur}", "be": 0}
            if verbose:
                print(f"  {label:<24} ⚠️  {meta['error']}")
            return [], meta

    jobs, report = [], []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for trouves, meta in pool.map(_un, actifs):
            jobs.extend(trouves)
            report.append(meta)
    dedup = {}
    for job in jobs:
        dedup[job.external_id] = job
    return {"jobs": list(dedup.values()), "report": report}
