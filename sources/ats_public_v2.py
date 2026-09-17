"""
JOB HUNTER BELGIUM
CONNECTEURS ATS PUBLICS - GENERATION 2 - VERSION 1.0

Quatre ATS de plus, lus par leur interface publique documentee, sans
navigateur ni contournement :

    LEVER      api.lever.co/v0/postings/{slug}?mode=json
    ASHBY      api.ashbyhq.com/posting-api/job-board/{slug}
    WORKABLE   apply.workable.com/api/v3/accounts/{slug}/jobs  (+ detail)
    PERSONIO   {slug}.jobs.personio.de/xml

Le principe est celui des connecteurs de premiere generation (Greenhouse,
Recruitee, SmartRecruiters) : un employeur = une ligne de configuration,
jamais un scraper. La description complete arrive en JSON/XML, la
localisation est filtree par sources/location_belgium.py.

Les employeurs viennent de config/ats_employers_v2.json, alimente par le
moteur de decouverte (sources/source_discovery_v1.py). Chaque entree porte
son ATS, son identifiant, et le nombre d'offres belges mesure a la
validation.
"""

from __future__ import annotations

import html
import re
import time
from datetime import datetime, timezone

import requests

from database.models import JobOffer
from sources.location_belgium import detect_belgium_multi, BE_CONFIRMED, BE_LIKELY, BE_UNKNOWN


ATS_PUBLIC_V2_VERSION = "1.1"

TIMEOUT = 25
PAUSE_ENTRE_EMPLOYEURS = 0.5
HEADERS = {
    "User-Agent": "JobHunter/2.0 (recherche d'emploi personnelle ; lecture publique)",
    "Accept": "application/json, application/xml, text/xml, */*",
}
MIN_DESCRIPTION = 120


def _clean(value) -> str:
    return "" if value is None else str(value).strip()


_RE_TAGS = re.compile(r"<[^>]+>")
_RE_BLANCS = re.compile(r"[ \t\r\f\v]+")


def html_to_text(fragment) -> str:
    texte = _clean(fragment)
    if not texte:
        return ""
    texte = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</div>|</h\d>|</tr>", "\n", texte)
    texte = _RE_TAGS.sub(" ", texte)
    texte = html.unescape(texte)
    texte = _RE_BLANCS.sub(" ", texte)
    return re.sub(r"\n\s*\n+", "\n", texte).strip()


def _statut_be(localisation: str, pays_iso: str = "") -> str:
    if pays_iso and pays_iso.upper() == "BE":
        return BE_CONFIRMED
    if pays_iso and pays_iso.upper() not in ("", "BE"):
        # Un pays explicite non belge tranche, sauf si le texte cite la Belgique.
        st = detect_belgium_multi(localisation)
        return st if st == BE_CONFIRMED else "BE_EXCLUDED"
    return detect_belgium_multi(localisation)


MIN_DETAIL_FIABLE = 250


def declarer_detail(job, texte=None):
    """
    Le connecteur a lu la fiche complete : il doit le dire au Matcher V5.1.

    evaluate_confidence() ne regarde que detail_enrichment_attempted,
    detail_enrichment_success et detail_matching_text_length ; sans eux, une
    offre est « provisoire » et le gate la plafonne a VERIFY, jamais APPLY —
    constate le 17/09/2026 sur 2 400 offres Workday, SuccessFactors,
    Recruitee, Phenom et Greenhouse dont la description complete (1 000 a
    8 000 caracteres) etait pourtant en base : 0 APPLY, 0 STRETCH.
    """
    t = str(texte if texte is not None else (getattr(job, "description", "") or ""))
    n = len(t)
    job.detail_enrichment_attempted = True
    job.detail_enrichment_success = n >= MIN_DETAIL_FIABLE
    job.detail_matching_text_length = n
    return job


def _retenir(statut: str, include_unknown: bool) -> bool:
    return statut in (BE_CONFIRMED, BE_LIKELY) or (statut == BE_UNKNOWN and include_unknown)


def _offre(ats: str, identifiant: str, label: str, external_id: str, titre: str,
           localisation: str, description: str, url: str, date: str | None,
           contrat: str | None = None, langue: str | None = None,
           salaire: str | None = None, entreprise: str | None = None) -> JobOffer:
    job = JobOffer(
        source=ats, external_id=f"{identifiant}:{external_id}",
        title=titre, company=entreprise or label or identifiant,
        location=localisation or "Lieu non précisé",
        description=description, url=url,
        date_published=date or None, contract_type=contrat or None,
        language=langue or None, salary=salaire or None,
        date_collected=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    job.collection_channel = ats
    job.origin_source = identifiant
    job.detail_enrichment_attempted = True
    job.detail_enrichment_success = len(description) >= MIN_DESCRIPTION
    job.detail_matching_text_length = len(description)
    return job


def _get_json(url: str, session, method="GET", body=None):
    r = session.request(method, url, headers=HEADERS, json=body, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


# ------------------------------------------------------------------
# LEVER
# ------------------------------------------------------------------

def collect_lever(identifiant: str, label: str, session, include_unknown=False):
    data = _get_json(f"https://api.lever.co/v0/postings/{identifiant}?mode=json", session)
    if isinstance(data, dict) and data.get("ok") is False:
        raise ValueError(data.get("error") or "slug Lever inconnu")
    jobs, total, hors_be = [], 0, 0
    for p in data if isinstance(data, list) else []:
        total += 1
        cat = p.get("categories") or {}
        localisation = " ; ".join(x for x in [_clean(cat.get("location")),
                                              " ; ".join(p.get("allLocations") or [])] if x)
        statut = _statut_be(localisation, _clean(p.get("country")))
        if not _retenir(statut, include_unknown):
            hors_be += 1
            continue
        parties = [html_to_text(p.get("descriptionBody") or p.get("description"))]
        for liste in p.get("lists") or []:
            parties.append(_clean(liste.get("text")))
            parties.append(html_to_text(liste.get("content")))
        parties.append(html_to_text(p.get("additional")))
        description = "\n".join(x for x in parties if x)
        date = None
        if p.get("createdAt"):
            date = datetime.fromtimestamp(int(p["createdAt"]) / 1000, tz=timezone.utc).date().isoformat()
        jobs.append(_offre("LEVER", identifiant, label, _clean(p.get("id")), _clean(p.get("text")),
                           localisation, description, _clean(p.get("hostedUrl")), date,
                           contrat=_clean(cat.get("commitment")) or None))
    return jobs, {"total": total, "hors_be": hors_be}


# ------------------------------------------------------------------
# ASHBY
# ------------------------------------------------------------------

def collect_ashby(identifiant: str, label: str, session, include_unknown=False):
    data = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{identifiant}"
                     "?includeCompensation=true", session)
    jobs, total, hors_be = [], 0, 0
    for p in data.get("jobs") or []:
        total += 1
        adresse = ((p.get("address") or {}).get("postalAddress") or {})
        localisation = " ; ".join(x for x in [
            _clean(p.get("location")),
            ", ".join(v for v in [_clean(adresse.get("addressLocality")),
                                  _clean(adresse.get("addressRegion")),
                                  _clean(adresse.get("addressCountry"))] if v),
            " ; ".join(_clean(s.get("location")) for s in (p.get("secondaryLocations") or [])),
        ] if x)
        statut = _statut_be(localisation, "")
        if p.get("isRemote") and statut == BE_UNKNOWN and not include_unknown:
            hors_be += 1
            continue
        if not _retenir(statut, include_unknown):
            hors_be += 1
            continue
        description = html_to_text(p.get("descriptionHtml")) or _clean(p.get("descriptionPlain"))
        salaire = None
        comp = p.get("compensation") or {}
        if comp.get("compensationTierSummary"):
            salaire = _clean(comp.get("compensationTierSummary"))
        jobs.append(_offre("ASHBY", identifiant, label, _clean(p.get("id")), _clean(p.get("title")),
                           localisation, description, _clean(p.get("jobUrl")),
                           _clean(p.get("publishedAt"))[:10] or None,
                           contrat=_clean(p.get("employmentType")) or None, salaire=salaire))
    return jobs, {"total": total, "hors_be": hors_be}


# ------------------------------------------------------------------
# WORKABLE
# ------------------------------------------------------------------

def collect_workable(identifiant: str, label: str, session, include_unknown=False,
                     max_details: int = 150):
    base = f"https://apply.workable.com/api/v3/accounts/{identifiant}/jobs"
    jobs, total, hors_be, token = [], 0, 0, None
    lignes = []
    for _ in range(20):
        body = {"query": "", "location": [], "department": [], "worktype": [], "remote": []}
        if token:
            body["token"] = token
        data = _get_json(base, session, method="POST", body=body)
        lignes.extend(data.get("results") or [])
        token = data.get("nextPage")
        if not token:
            break
    details = 0
    for p in lignes:
        total += 1
        loc = p.get("location") or {}
        localisation = ", ".join(v for v in [_clean(loc.get("city")), _clean(loc.get("region")),
                                             _clean(loc.get("country"))] if v)
        if p.get("locations"):
            localisation = " ; ".join([localisation] + [
                ", ".join(v for v in [_clean(l.get("city")), _clean(l.get("country"))] if v)
                for l in p["locations"]])
        statut = _statut_be(localisation, _clean(loc.get("countryCode")))
        if not _retenir(statut, include_unknown):
            hors_be += 1
            continue
        shortcode = _clean(p.get("shortcode"))
        description = ""
        if details < max_details and shortcode:
            try:
                # La liste est en v3, le detail en v2 (verifie le 16/09/2026 :
                # v3/jobs/{shortcode} repond 404, v2 rend description,
                # requirements, benefits).
                d = _get_json(base.replace("/api/v3/", "/api/v2/") + f"/{shortcode}", session)
                description = "\n".join(x for x in [
                    html_to_text(d.get("description")), html_to_text(d.get("requirements")),
                    html_to_text(d.get("benefits"))] if x)
                details += 1
                time.sleep(0.2)
            except Exception:
                description = ""
        jobs.append(_offre("WORKABLE", identifiant, label, shortcode or _clean(p.get("id")),
                           _clean(p.get("title")), localisation, description,
                           f"https://apply.workable.com/{identifiant}/j/{shortcode}/",
                           _clean(p.get("published"))[:10] or None,
                           contrat=_clean(p.get("type")) or None))
    return jobs, {"total": total, "hors_be": hors_be, "details": details}


# ------------------------------------------------------------------
# PERSONIO
# ------------------------------------------------------------------

def collect_personio(identifiant: str, label: str, session, include_unknown=False):
    import xml.etree.ElementTree as ET
    url = f"https://{identifiant}.jobs.personio.de/xml"
    r = session.get(url, headers=HEADERS, timeout=TIMEOUT)
    if r.status_code == 404:
        r = session.get(f"https://{identifiant}.jobs.personio.com/xml", headers=HEADERS, timeout=TIMEOUT)
        url = url.replace(".de/", ".com/")
    r.raise_for_status()
    racine = ET.fromstring(r.content)
    jobs, total, hors_be = [], 0, 0
    for pos in racine.iter("position"):
        total += 1
        champ = lambda nom: _clean((pos.findtext(nom) or ""))
        localisation = champ("office")
        statut = _statut_be(localisation, "")
        if not _retenir(statut, include_unknown):
            hors_be += 1
            continue
        parties = []
        for desc in pos.iter("jobDescription"):
            parties.append(_clean(desc.findtext("name")))
            parties.append(html_to_text(desc.findtext("value")))
        description = "\n".join(x for x in parties if x)
        pid = champ("id")
        lien = url.rsplit("/xml", 1)[0] + f"/job/{pid}"
        jobs.append(_offre("PERSONIO", identifiant, label, pid, champ("name"), localisation,
                           description, lien, champ("createdAt")[:10] or None,
                           contrat=champ("employmentType") or champ("schedule") or None,
                           entreprise=champ("subcompany") or None))
    return jobs, {"total": total, "hors_be": hors_be}


COLLECTEURS = {
    "LEVER": collect_lever,
    "ASHBY": collect_ashby,
    "WORKABLE": collect_workable,
    "PERSONIO": collect_personio,
}


def collect_ats_v2(ats: str, companies: list[dict], verbose: bool = True,
                   include_unknown: bool = False) -> dict:
    """
    Tous les employeurs configures pour un ATS. Rend {"jobs", "report"}.
    Une entreprise en erreur n'arrete pas les autres.
    """
    fonction = COLLECTEURS[ats]
    session = requests.Session()
    jobs, report = [], []
    for company in companies:
        if not company.get("enabled", True):
            continue
        identifiant = _clean(company.get("identifier"))
        label = _clean(company.get("label")) or identifiant
        ligne = {"label": label, "identifier": identifiant, "total": 0, "be": 0,
                 "hors_be": 0, "error": None}
        try:
            trouves, meta = fonction(identifiant, label, session, include_unknown=include_unknown)
            ligne.update(total=meta.get("total", 0), hors_be=meta.get("hors_be", 0),
                         be=len(trouves))
            jobs.extend(trouves)
        except Exception as erreur:
            ligne["error"] = f"{type(erreur).__name__}: {str(erreur)[:120]}"
        report.append(ligne)
        if verbose:
            if ligne["error"]:
                print(f"  {label:<24} ⚠️  {ligne['error']}")
            else:
                print(f"  {label:<24} total={ligne['total']:<4} BE={ligne['be']:<4} "
                      f"hors BE={ligne['hors_be']}")
        time.sleep(PAUSE_ENTRE_EMPLOYEURS)
    dedup = {}
    for job in jobs:
        dedup[job.external_id] = job
    return {"jobs": list(dedup.values()), "report": report}
