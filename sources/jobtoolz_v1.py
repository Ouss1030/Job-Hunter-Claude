"""
JOB HUNTER BELGIUM
CONNECTEUR JOBTOOLZ - VERSION 1.0

Jobtoolz est un ATS belge (Gand) utilise par des centaines de PME, sur
domaine propre (jobs.gim.be, careers.etherna.be, jobs.westvlees.com) ou
sous-domaine (dienstencheques-group-f.jobtoolz.com). Pas de sitemap, pas
de flux : la page carriere embarque la liste complete des offres dans
l'attribut Alpine.js de la liste,

    x-data="window.jobComponent([{id, title, url, location, types, ...}], 10, ...)"

en JSON echappe HTML — verifie le 17 septembre 2026 sur GIM (3 offres),
Etherna, Group F. Chaque page d'offre porte un JSON-LD JobPosting
(titre, date, employeur, mais description tronquee et lieu vide) et le
texte complet dans le corps de la page : on prend les deux.

Un employeur = {"identifier": "jobs.gim.be", "label": "GIM"} dans
config/ats_employers_v2.json ; l'identifiant est l'hote du site carriere.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from database.models import JobOffer
from sources.ats_public_v2 import _statut_be, _retenir
from sources.html_generique_v1 import _contenu, _lieu, _clean, HEADERS
from sources.jsonld_sitemap_v1 import extract_job_posting
from sources.location_belgium import BE_CONFIRMED, BE_LIKELY, BE_UNKNOWN


JOBTOOLZ_VERSION = "1.0"

TIMEOUT = 25
PAUSE = 0.5
MAX_OFFRES = 150
MIN_TEXTE = 200
LANGUES = ("fr", "nl", "en", "")
_RE_COMPOSANT = re.compile(r"window\.jobComponent\(\s*", re.I)


def _hote(valeur: str) -> str:
    return _clean(valeur).lower().removeprefix("https://").removeprefix("http://").strip("/")


def extraire_liste(page_html: str) -> list[dict]:
    """La liste d'offres embarquee dans window.jobComponent([...], ...)."""
    m = _RE_COMPOSANT.search(page_html or "")
    if not m:
        return []
    texte = html.unescape(page_html[m.end():m.end() + 2_000_000])
    debut = texte.find("[")
    if debut < 0:
        return []
    try:
        items, _ = json.JSONDecoder().raw_decode(texte[debut:])
    except ValueError:
        return []
    return [i for i in items if isinstance(i, dict) and i.get("url") and i.get("title")]


def lire_liste(host: str, session) -> tuple[list[dict], str | None]:
    host = _hote(host)
    derniere = "aucune page carriere lisible"
    for lang in LANGUES:
        url = f"https://{host}/{lang}".rstrip("/")
        try:
            r = session.get(url, headers=HEADERS, timeout=TIMEOUT)
        except Exception as e:
            derniere = f"{type(e).__name__}: {str(e)[:80]}"
            continue
        if r.status_code != 200:
            derniere = f"HTTP {r.status_code}"
            continue
        items = extraire_liste(r.text)
        if items:
            return items, None
        if "jobComponent" in r.text:
            return [], None  # site Jobtoolz sans offre en ce moment
        derniere = "pas de composant Jobtoolz sur la page"
    return [], derniere


def lire_offre(item: dict, session, host: str, label: str, include_unknown: bool) -> JobOffer | None:
    url = _clean(item.get("url"))
    r = session.get(url, headers=HEADERS, timeout=TIMEOUT)
    if r.status_code != 200:
        return None
    posting = extract_job_posting(r.text) or {}
    soupe = BeautifulSoup(r.text, "html.parser")
    texte = _contenu(soupe)
    if len(texte) < MIN_TEXTE:
        texte = re.sub(r"<[^>]+>", " ", str(posting.get("description") or ""))
    lieu_liste = _clean(item.get("location"))
    statut = _statut_be(lieu_liste, "") if lieu_liste else BE_UNKNOWN
    lieu = lieu_liste
    if statut not in (BE_CONFIRMED, BE_LIKELY):
        lieu_page, statut_page = _lieu(texte + " " + lieu_liste)
        if statut_page in (BE_CONFIRMED, BE_LIKELY):
            deja = lieu_liste and lieu_liste.lower() in lieu_page.lower()
            lieu, statut = (lieu_page if (not lieu_liste or deja) else f"{lieu_liste} — {lieu_page}"), statut_page
    if not _retenir(statut, include_unknown):
        return None
    org = posting.get("hiringOrganization") or {}
    entreprise = _clean(org.get("name") if isinstance(org, dict) else org) or label
    types = item.get("types")
    contrat = _clean(", ".join(types) if isinstance(types, list) else types) or None
    job = JobOffer(
        source="JOBTOOLZ", external_id=f"{host}:{item.get('id') or hashlib.sha1(url.encode()).hexdigest()[:12]}",
        title=_clean(item.get("title")), company=entreprise,
        location=lieu or ("Belgique (site employeur)" if include_unknown else "Lieu non précisé"),
        description=texte[:20000], url=url, date_published=_clean(posting.get("datePosted"))[:10] or None,
        contract_type=contrat, language=None, salary=None,
        date_collected=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    job.collection_channel = "JOBTOOLZ"
    job.origin_source = host
    job.location_status = statut
    job.detail_enrichment_attempted = True
    job.detail_enrichment_success = len(texte) >= MIN_TEXTE
    job.detail_matching_text_length = len(texte)
    return job


def collect_jobtoolz(company: dict, session=None, include_unknown: bool | None = None,
                     max_offres: int = MAX_OFFRES) -> tuple[list[JobOffer], dict]:
    session = session or requests.Session()
    host = _hote(company.get("identifier") or company.get("host"))
    label = _clean(company.get("label")) or host
    if include_unknown is None:
        # ATS belge : une offre sans lieu lisible est presque toujours belge (Westvlees a
        # Staden, 12 offres sur 14 sans lieu dans la liste) ; la gate aval tranche.
        include_unknown = True
    items, erreur = lire_liste(host, session)
    meta = {"host": host, "label": label, "total": len(items), "be": 0, "hors_be": 0, "echecs": 0, "error": erreur}
    jobs = []
    for item in items[:max_offres]:
        try:
            job = lire_offre(item, session, host, label, include_unknown)
        except Exception:
            meta["echecs"] += 1
            continue
        if job:
            jobs.append(job)
            meta["be"] += 1
        else:
            meta["hors_be"] += 1
        time.sleep(PAUSE)
    return jobs, meta


def collect_jobtoolz_jobs(companies: list[dict], verbose: bool = True) -> dict:
    session = requests.Session()
    jobs, report = [], []
    for c in companies:
        if not c.get("enabled", True):
            continue
        label = _clean(c.get("label")) or _clean(c.get("identifier"))
        try:
            trouves, meta = collect_jobtoolz(c, session, include_unknown=c.get("include_unknown"))
            jobs.extend(trouves)
        except Exception as e:
            meta = {"label": label, "total": 0, "be": 0, "hors_be": 0, "echecs": 0, "error": f"{type(e).__name__}: {str(e)[:100]}"}
        report.append(meta)
        if verbose:
            print(f"  {label:<24} " + (f"⚠️  {meta['error']}" if meta.get("error") else
                  f"liste={meta['total']:<4} BE={meta['be']:<4} hors BE={meta['hors_be']}  echecs={meta['echecs']}"))
    dedup = {}
    for j in jobs:
        dedup[j.external_id] = j
    return {"jobs": list(dedup.values()), "report": report}
