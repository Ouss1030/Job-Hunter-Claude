"""
JOB HUNTER BELGIUM
CONNECTEUR TEAMTAILOR (FLUX RSS) - VERSION 1.0

Un site carriere Teamtailor publie un flux RSS public :

    https://{host}/jobs.rss            (100 offres par page, ?page=2 ensuite)

Chaque item porte titre, lien, date, description complete (HTML) et les
champs Teamtailor tt:city, tt:zip, tt:country, tt:department. Verifie le
16 septembre 2026 : Equip Interim 100 items de 4 266 caracteres, ML6 13
items de 6 192 caracteres. Une requete par site au lieu d'une page par
offre — l'idee vient du projet principal (multi_ats_generic_v417).

Un employeur = {"identifier": "jobs.ml6.eu", "label": "ML6"} dans
config/ats_employers_v2.json ; l'identifiant est l'hote du site carriere,
teamtailor.com ou domaine propre.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import requests

from database.models import JobOffer
from sources.ats_public_v2 import html_to_text, _statut_be, _retenir


TEAMTAILOR_VERSION = "1.0"

TIMEOUT = 25
MAX_PAGES = 10
PAUSE_PAGE = 0.5
MIN_DESCRIPTION = 150
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) JobHunter/teamtailor",
    "Accept": "application/rss+xml, application/xml, text/xml",
}
_NS_TT = "{https://teamtailor.com/locations}"


def _clean(v) -> str:
    return re.sub(r"\s+", " ", "" if v is None else str(v)).strip()


def _texte(item, nom: str) -> str:
    """Premier element dont le tag se termine par `nom` (avec ou sans espace de noms), a toute profondeur."""
    court = nom.split(":")[-1]
    for e in item.iter():
        if e is item:
            continue
        if e.tag == court or e.tag.endswith("}" + court):
            return _clean(e.text)
    return ""


def _lieux(item) -> list[str]:
    """Les lieux d'une offre : tt:locations > tt:location > tt:city / tt:zip / tt:country."""
    sortie = []
    for loc in item.iter():
        if not (loc.tag.endswith("}location") or loc.tag == "location"):
            continue
        champs = {e.tag.split("}")[-1]: _clean(e.text) for e in loc}
        parties = [champs.get("city", ""), champs.get("zip", ""), champs.get("country", "")]
        if any(parties):
            sortie.append(", ".join(x for x in parties if x))
    return sortie


def lire_flux(host: str, session, max_pages: int = MAX_PAGES) -> list[ET.Element]:
    host = host.lower().removeprefix("https://").removeprefix("http://").strip("/")
    items: list[ET.Element] = []
    vus: set[str] = set()
    for page in range(1, max_pages + 1):
        url = f"https://{host}/jobs.rss" + (f"?page={page}" if page > 1 else "")
        r = session.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            break
        try:
            racine = ET.fromstring(r.content)
        except ET.ParseError:
            break
        page_items = racine.findall(".//item")
        guids = {_texte(i, "guid") for i in page_items}
        # ?page=2 rend la meme page que la premiere (verifie le 16/09/2026) :
        # on s'arrete des qu'une page n'apporte rien de neuf. Le flux est donc
        # plafonne a 100 offres par site — suffisant pour presque tous.
        if not page_items or not (guids - vus):
            break
        vus |= guids
        items.extend(i for i in page_items if _texte(i, "guid") in guids)
        if len(page_items) < 100:
            break
        time.sleep(PAUSE_PAGE)
    return items


def collect_teamtailor(company: dict, session=None, include_unknown: bool = False) -> tuple[list[JobOffer], dict]:
    session = session or requests.Session()
    host = _clean(company.get("identifier") or company.get("host")).lower().removeprefix("https://").removeprefix("http://").strip("/")
    label = _clean(company.get("label")) or host
    items = lire_flux(host, session)
    jobs, hors_be = [], 0
    for it in items:
        lieux = _lieux(it)
        lieu = " ; ".join(lieux)
        pays = _texte(it, "tt:country")
        iso = {"belgium": "BE", "belgique": "BE", "belgië": "BE", "belgie": "BE"}.get(pays.lower(), pays.upper() if len(pays) == 2 else "")
        # Plusieurs lieux : il suffit qu'un soit belge (detect_belgium_multi sur " ; ").
        statut = _statut_be(lieu, iso if len(lieux) <= 1 else "")
        if not _retenir(statut, include_unknown):
            hors_be += 1
            continue
        lien = _texte(it, "link")
        guid = _texte(it, "guid") or lien
        ident = re.sub(r"[^A-Za-z0-9]+", "", guid.rsplit("/", 1)[-1])[:40] or str(abs(hash(lien)))
        description = html_to_text(_texte(it, "description"))
        date = _texte(it, "pubDate")
        try:
            from email.utils import parsedate_to_datetime
            date = parsedate_to_datetime(date).date().isoformat() if date else None
        except Exception:
            date = (date or "")[:10] or None
        job = JobOffer(
            source="TEAMTAILOR", external_id=f"{host}:{ident}", title=_texte(it, "title"),
            company=label, location=lieu or "Lieu non précisé",
            description=description, url=lien, date_published=date,
            contract_type=_texte(it, "tt:role") or None, language=None, salary=None,
            date_collected=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        job.collection_channel = "TEAMTAILOR"
        job.origin_source = host
        job.detail_enrichment_attempted = True
        job.detail_enrichment_success = len(description) >= MIN_DESCRIPTION
        job.detail_matching_text_length = len(description)
        jobs.append(job)
    return jobs, {"total": len(items), "be": len(jobs), "hors_be": hors_be}


def collect_teamtailor_jobs(companies: list[dict], verbose: bool = True) -> dict:
    session = requests.Session()
    jobs, report = [], []
    for c in companies:
        if not c.get("enabled", True):
            continue
        label = _clean(c.get("label")) or _clean(c.get("identifier"))
        try:
            trouves, meta = collect_teamtailor(c, session, include_unknown=bool(c.get("include_unknown", False)))
            jobs.extend(trouves)
            meta.update(label=label, error=None)
        except Exception as e:
            meta = {"label": label, "total": 0, "be": 0, "hors_be": 0, "error": f"{type(e).__name__}: {str(e)[:100]}"}
        report.append(meta)
        if verbose:
            print(f"  {label:<24} " + (f"⚠️  {meta['error']}" if meta["error"] else
                  f"flux={meta['total']:<4} BE={meta['be']:<4} hors BE={meta['hors_be']}"))
    dedup = {}
    for j in jobs:
        dedup[j.external_id] = j
    return {"jobs": list(dedup.values()), "report": report}
