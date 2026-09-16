"""
JOB HUNTER BELGIUM
CONNECTEUR CVWAREHOUSE - VERSION 1.0

CVWarehouse est un ATS belge, tres present chez les provinces, hautes
ecoles et hopitaux flamands. Sept employeurs detectes par le moteur de
decouverte le 15 septembre 2026 : provinces d'Anvers et du Brabant
flamand, HOGENT, Thomas More, AZ Turnhout, Vivalia, Greenyard.

Pas d'API ni de JSON-LD, mais des pages servies par le serveur :

    liste   https://{site}/?lang=nl-BE          liens ?job=<id>
                                                 .job-title, .location
    detail  https://{site}/?lang=nl-BE&job=<id>  TOUS les blocs .job-detail
                                                 de l'employeur, masques par
                                                 CSS sauf celui demande

Constate le 16/09/2026 chez HOGENT : la page de detail embarque les 14
offres completes. Deux requetes suffisent donc pour un employeur entier ;
chaque bloc est relie a son offre par son titre.

Trois formes de site : {x}.cvw.io, jobpage.cvwarehouse.com/?companyGuid=…,
ou un domaine propre (jobs.provincieantwerpen.be). L'identifiant est donc
l'URL de base, telle quelle.

Un site bilingue publie les memes offres en nl-BE et fr-BE : on lit la
langue configuree ("lang", defaut nl-BE) et on ne double pas.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit, parse_qs, urlencode

import requests
from bs4 import BeautifulSoup

from database.models import JobOffer
from sources.ats_public_v2 import _statut_be, _retenir


CVWAREHOUSE_VERSION = "1.0"

TIMEOUT = 25
MAX_DETAILS = 150
MIN_DESCRIPTION = 150
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/151.0 Safari/537.36 JobHunter/cvwarehouse"),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "nl-BE,nl;q=0.9,fr-BE;q=0.8,en;q=0.6",
}
_RE_JOB = re.compile(r"[?&]job=(\d+)")


def _clean(v) -> str:
    return re.sub(r"\s+", " ", "" if v is None else str(v)).strip()


def _url(base: str, **params) -> str:
    """Ajoute des parametres a l'URL de base sans perdre companyGuid."""
    p = urlsplit(base if base.startswith("http") else f"https://{base}/")
    q = {k: v[0] for k, v in parse_qs(p.query).items()}
    q.update(params)
    return urlunsplit((p.scheme, p.netloc, p.path or "/", urlencode(q), ""))


_RE_SECTION = re.compile(r"[?&]section=([0-9a-f-]{36})")
MAX_SECTIONS = 20


def _liens_offres(soupe, vus: set, lignes: list, section: str = "") -> None:
    for a in soupe.select("a[href*='job=']"):
        m = _RE_JOB.search(a.get("href") or "")
        if not m or m.group(1) in vus:
            continue
        vus.add(m.group(1))
        titre = a.select_one(".job-title")
        lieu = a.select_one(".location")
        lignes.append({
            "id": m.group(1), "section": section,
            "titre": _clean(titre.get_text() if titre else a.get_text())[:200],
            "lieu": _clean(lieu.get_text() if lieu else ""),
        })


def lister(base: str, lang: str, session) -> list[dict]:
    """
    Les offres de la page d'accueil, puis de chaque "section" (Vacatures,
    Jobstudenten, Stages...) : la province d'Anvers ne liste rien sur
    l'accueil et huit offres dans sa premiere section.
    """
    r = session.get(_url(base, lang=lang), headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    soupe = BeautifulSoup(r.text, "html.parser")
    vus, lignes = set(), []
    _liens_offres(soupe, vus, lignes)
    sections = []
    for a in soupe.select("a[href*='section=']"):
        m = _RE_SECTION.search(a.get("href") or "")
        if m and m.group(1) not in sections:
            sections.append(m.group(1))
    for guid in sections[:MAX_SECTIONS]:
        try:
            rs = session.get(_url(base, lang=lang, section=guid), headers=HEADERS, timeout=TIMEOUT)
            if rs.status_code == 200:
                _liens_offres(BeautifulSoup(rs.text, "html.parser"), vus, lignes, section=guid)
        except Exception:
            continue
    return lignes


def _normaliser_titre(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _clean(t).lower()).strip()


def blocs_detail(base: str, lang: str, job_id: str, session, section: str = "") -> dict[str, dict]:
    """
    Tous les blocs .job-detail de la page, indexes par titre normalise.

    La page servie pour une offre contient les blocs de toutes les offres
    de sa section (masques cote client) : une requete par section, tout
    le contenu.
    """
    params = {"lang": lang, "job": job_id}
    if section:
        params["section"] = section
    r = session.get(_url(base, **params), headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    soupe = BeautifulSoup(r.text, "html.parser")
    sortie: dict[str, dict] = {}
    for bloc in soupe.select(".job-detail"):
        for tag in bloc.select("script, style, nav, form, .share, .social, .cvwShare, #cvwShare"):
            tag.decompose()
        titre = bloc.select_one(".job-title")
        lieu = bloc.select_one(".location")
        texte = bloc.get_text("\n")
        texte = re.sub(r"[ \t]+", " ", texte)
        texte = re.sub(r"\n\s*\n+", "\n", texte).strip()
        cle = _normaliser_titre(titre.get_text() if titre else "")
        if cle and cle not in sortie:
            sortie[cle] = {"titre": _clean(titre.get_text()) if titre else "",
                           "lieu": _clean(lieu.get_text()) if lieu else "", "texte": texte}
    return sortie


def collect_cvwarehouse(company: dict, session=None, include_unknown: bool = True,
                        max_details: int = MAX_DETAILS) -> tuple[list[JobOffer], dict]:
    session = session or requests.Session()
    base = _clean(company.get("base") or company.get("identifier"))
    lang = _clean(company.get("lang")) or "nl-BE"
    hote = urlsplit(base if base.startswith("http") else f"https://{base}").netloc.lower()
    label = _clean(company.get("label")) or hote
    lignes = lister(base, lang, session)
    blocs: dict[str, dict] = {}
    echecs = 0
    # Une page de detail par section : elle porte les blocs de toute la section.
    premiers: dict[str, str] = {}
    for l in lignes:
        premiers.setdefault(l.get("section", ""), l["id"])
    for section, job_id in list(premiers.items())[:MAX_SECTIONS]:
        try:
            for cle, bloc in blocs_detail(base, lang, job_id, session, section=section).items():
                blocs.setdefault(cle, bloc)
        except Exception:
            echecs += 1
    jobs, hors_be, sans_texte = [], 0, 0
    for l in lignes:
        d = blocs.get(_normaliser_titre(l["titre"])) or {}
        localisation = d.get("lieu") or l["lieu"]
        # Un employeur public belge sans lieu affiche reste belge : l'inconnu
        # est accepte par defaut ici (contrairement aux sites mondiaux).
        statut = _statut_be(localisation, "")
        if not _retenir(statut, include_unknown):
            hors_be += 1
            continue
        description = d.get("texte") or ""
        if not description:
            sans_texte += 1
        job = JobOffer(
            source="CVWAREHOUSE", external_id=f"{hote}:{l['id']}",
            title=d.get("titre") or l["titre"], company=label,
            location=localisation or "Lieu non précisé", description=description,
            url=_url(base, lang=lang, job=l["id"]),
            date_published=None, contract_type=None, language=lang[:2], salary=None,
            date_collected=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        job.collection_channel = "CVWAREHOUSE"
        job.origin_source = hote
        job.detail_enrichment_attempted = True
        job.detail_enrichment_success = len(description) >= MIN_DESCRIPTION
        job.detail_matching_text_length = len(description)
        jobs.append(job)
    return jobs, {"total": len(lignes), "be": len(jobs), "hors_be": hors_be,
                  "details": len(blocs), "sans_texte": sans_texte, "echecs_detail": echecs}


def collect_cvwarehouse_jobs(companies: list[dict], verbose: bool = True) -> dict:
    session = requests.Session()
    jobs, report = [], []
    for c in companies:
        if not c.get("enabled", True):
            continue
        label = _clean(c.get("label")) or _clean(c.get("identifier"))
        try:
            trouves, meta = collect_cvwarehouse(c, session)
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
