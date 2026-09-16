"""
JOB HUNTER BELGIUM
CONNECTEUR ICIMS - VERSION 1.0

Les portails iCIMS servent leur liste en HTML simple quand on demande la
version "cadre" (in_iframe=1), paginee par pr=0, 1, 2... et chaque page
d'offre porte un JSON-LD schema.org/JobPosting complet :

    liste   https://{host}/jobs/search?ss=1&in_iframe=1&pr={n}   liens /jobs/{id}/
    detail  https://{host}/jobs/{id}/job?in_iframe=1              JSON-LD JobPosting

Verifie le 16 septembre 2026 : BDO Belgium (20 par page), Jan De Nul (51).
La conversion et le cache par page sont ceux de l'extracteur universel
(sources/jsonld_sitemap_v1.collect_pages) : rien de nouveau a maintenir
pour lire une offre, seulement la facon d'en obtenir la liste.

Un employeur = {"identifier": "careers-bdobelgium.icims.com", "label": "BDO"}
dans config/ats_employers_v2.json.
"""

from __future__ import annotations

import re
import time

import requests

from sources.jsonld_sitemap_v1 import collect_pages, HEADERS


ICIMS_VERSION = "1.0"

TIMEOUT = 20
MAX_PAGES_LISTE = 15
PAUSE_LISTE = 0.4
_RE_ID = re.compile(r"/jobs/(\d+)/")


def _clean(v) -> str:
    return "" if v is None else str(v).strip()


def lister(host: str, session=None, max_pages: int = MAX_PAGES_LISTE) -> list[tuple[str, str]]:
    """Les URL d'offres d'un portail, page apres page, jusqu'a une page sans nouveaute."""
    session = session or requests.Session()
    host = host.lower().removeprefix("https://").removeprefix("http://").strip("/")
    vus: list[str] = []
    for page in range(max_pages):
        r = session.get(f"https://{host}/jobs/search", params={"ss": "1", "in_iframe": "1", "pr": str(page)},
                        headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            break
        nouveaux = [i for i in dict.fromkeys(_RE_ID.findall(r.text)) if i not in vus]
        if not nouveaux:
            break
        vus.extend(nouveaux)
        time.sleep(PAUSE_LISTE)
    return [(f"https://{host}/jobs/{i}/job?in_iframe=1", "") for i in vus]


def collect_icims(company: dict, session=None, include_unknown: bool = False, max_pages: int = 150):
    session = session or requests.Session()
    host = _clean(company.get("identifier") or company.get("host"))
    label = _clean(company.get("label")) or host
    entrees = lister(host, session)
    if not entrees:
        return [], {"host": host, "label": label, "sitemap_urls": 0, "be": 0, "hors_be": 0,
                    "visitees": 0, "cache": 0, "sans_jsonld": 0, "echecs": 0, "error": "aucune offre listee"}
    return collect_pages(host, label, entrees, session, include_unknown=include_unknown,
                         max_pages=max_pages, source="ICIMS")


def collect_icims_jobs(companies: list[dict], verbose: bool = True) -> dict:
    session = requests.Session()
    jobs, report = [], []
    for c in companies:
        if not c.get("enabled", True):
            continue
        label = _clean(c.get("label")) or _clean(c.get("identifier"))
        try:
            trouves, meta = collect_icims(c, session, include_unknown=bool(c.get("include_unknown", False)))
            jobs.extend(trouves)
        except Exception as e:
            meta = {"label": label, "sitemap_urls": 0, "be": 0, "hors_be": 0, "visitees": 0, "cache": 0,
                    "sans_jsonld": 0, "error": f"{type(e).__name__}: {str(e)[:100]}"}
        report.append(meta)
        if verbose:
            print(f"  {label:<24} " + (f"⚠️  {meta['error']}" if meta.get("error") else
                  f"listées={meta['sitemap_urls']:<4} cache={meta['cache']:<4} visitées={meta['visitees']:<4} "
                  f"BE={meta['be']:<4} hors BE={meta['hors_be']:<3} sans JSON-LD={meta['sans_jsonld']}"))
    dedup = {}
    for j in jobs:
        dedup[j.external_id] = j
    return {"jobs": list(dedup.values()), "report": report}
