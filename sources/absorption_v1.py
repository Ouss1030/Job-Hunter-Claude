"""
JOB HUNTER BELGIUM
ABSORPTION COMPLETE DES SERVICES PUBLICS - VERSION 1.0

Le constat (15 septembre 2026)
------------------------------
Le pipeline interrogeait Actiris et le Forem avec une liste de termes de
recherche tires du profil du candidat. Mesure en base :

    ACTIRIS   4 331 offres actives    alors que le catalogue en compte 33 208
    FOREM       344 offres actives    alors que l'open data en compte 26 198

Le filtrage se faisait donc a l'entree — l'inverse du principe du projet :
COLLECTER LE PLUS LARGEMENT POSSIBLE D'ABORD, FILTRER ET SCORER ENSUITE.

Ce module lit les deux catalogues EN ENTIER, sans mot-cle. La suite du
pipeline ne change pas : tout est sauve en raw_jobs, puis les offres
pertinentes ou a description mince recoivent leur page detail, comme avant.

Ce qui est reutilise, sans copie
--------------------------------
- sources.actiris    : session, payload, appel API, convert_actiris_job
- sources.forem      : convert_forem_job
- sources.*_detail   : inchanges, appeles par le pipeline apres collecte

Actiris : trois provenances, paginees separement
------------------------------------------------
Le champ typeOffre ne distingue pas une offre VDAB/Forem d'une offre
partenaire (les deux sont "Hrxml"). Or main.py raisonne sur cette
provenance. On pagine donc par mode — ACTIRIS, VDAB_FOREM, PARTNER — ce
qui coute le meme nombre de requetes qu'une pagination unique et garde la
provenance exacte. Mesure : 1 953 + 8 874 + 22 380. Pages de 200.

Forem : un export, pas dix mille pages
--------------------------------------
L'endpoint records de l'ODWB refuse un offset au-dela de 10 000. L'endpoint
exports/json rend tout le jeu en une reponse (~26 000 lignes). Repli sur
records si l'export echoue, puis sur le dernier instantane reussi.

Instantanes
-----------
Chaque catalogue lu avec succes est ecrit dans logs/absorption/. Si un
appel echoue a mi-parcours, on rend l'instantane precedent plutot que
rien : rendre rien ferait passer des milliers d'offres pour disparues.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from sources import actiris as _actiris
from sources.forem import convert_forem_job


ABSORPTION_VERSION = "1.0"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = PROJECT_ROOT / "logs" / "absorption"

ACTIRIS_PAGE_SIZE = 200
ACTIRIS_MODES = ("ACTIRIS", "VDAB_FOREM", "PARTNER")
ACTIRIS_PAUSE = 0.15

FOREM_EXPORT_URL = (
    "https://www.odwb.be/api/explore/v2.1/"
    "catalog/datasets/offres-d-emploi-forem/exports/json"
)
FOREM_RECORDS_URL = (
    "https://www.odwb.be/api/explore/v2.1/"
    "catalog/datasets/offres-d-emploi-forem/records"
)
FOREM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) JobHunter/absorption",
    "Accept": "application/json",
}
FOREM_TIMEOUT = 180
FOREM_RECORDS_MAX_OFFSET = 10_000

MARQUEUR_ABSORPTION = "ABSORPTION_COMPLETE"


# ------------------------------------------------------------------
# Utilitaires
# ------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _chrono(debut: float) -> str:
    s = int(time.monotonic() - debut)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _progression(prefixe: str, i: int, total: int, offres: int, debut: float) -> None:
    pct = f"{100 * i // total:3d}%" if total else "  ?%"
    barre = ""
    if total:
        plein = 24 * i // total
        barre = "█" * plein + "░" * (24 - plein) + " "
    print(f"  {prefixe:<22} {barre}{pct}  page {i}/{total or '?'}  "
          f"offres={offres:<6} {_chrono(debut)}", flush=True)


def _snapshot_path(nom: str) -> Path:
    return SNAPSHOT_DIR / f"{nom.lower()}_last_ok.json"


def _ecrire_snapshot(nom: str, lignes: list, meta: dict) -> None:
    try:
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        _snapshot_path(nom).write_text(json.dumps(
            {"generated_at": _now(), "meta": meta, "rows": lignes},
            ensure_ascii=False), encoding="utf-8")
    except Exception as erreur:
        print(f"  ⚠️  instantane {nom} non ecrit : {erreur}")


def _lire_snapshot(nom: str) -> tuple[list, dict]:
    chemin = _snapshot_path(nom)
    if not chemin.exists():
        return [], {}
    try:
        charge = json.loads(chemin.read_text(encoding="utf-8"))
        return list(charge.get("rows") or []), dict(charge.get("meta") or {},
                                                     generated_at=charge.get("generated_at"))
    except Exception:
        return [], {}


# ------------------------------------------------------------------
# ACTIRIS — catalogue complet
# ------------------------------------------------------------------

def lire_catalogue_actiris(mode: str, max_pages: int | None = None,
                           verbose: bool = True) -> dict:
    """
    Toutes les offres d'une provenance Actiris, sans mot-cle.

    Rend {"rows", "total_annonce", "pages", "erreur"}. Une erreur a
    mi-parcours conserve les pages deja lues et la signale.
    """
    debut = time.monotonic()
    rows: list[dict] = []
    vus: set[str] = set()
    total_annonce = None
    pages = 0
    erreur = None
    page = 1
    while True:
        payload = _actiris.build_search_payload(
            keyword="", page=page, page_size=ACTIRIS_PAGE_SIZE,
            provenance_mode=mode)
        try:
            data = _actiris.request_actiris_api(payload)
        except Exception as exc:
            erreur = f"page {page}: {type(exc).__name__}: {exc}"
            break
        if total_annonce is None:
            total_annonce = int(data.get("total") or 0)
        items = data.get("items") or []
        pages += 1
        for item in items:
            ref = str(item.get("reference") or "").strip()
            if not ref or ref in vus:
                continue
            vus.add(ref)
            item["_origin_source"] = mode
            item["_origin_sources"] = [mode]
            item["_search_terms"] = [MARQUEUR_ABSORPTION]
            rows.append(item)
        nb_pages = max(1, -(-total_annonce // ACTIRIS_PAGE_SIZE)) if total_annonce else None
        if verbose and (page == 1 or page % 5 == 0 or (nb_pages and page == nb_pages)):
            _progression(f"ACTIRIS {mode}", page, nb_pages or 0, len(rows), debut)
        if not items or len(items) < ACTIRIS_PAGE_SIZE:
            break
        if nb_pages and page >= nb_pages:
            break
        if max_pages and page >= max_pages:
            break
        page += 1
        time.sleep(ACTIRIS_PAUSE)
    return {"rows": rows, "total_annonce": total_annonce, "pages": pages,
            "erreur": erreur, "duree": _chrono(debut)}


def collect_actiris_full(verbose: bool = True, max_pages_per_mode: int | None = None,
                         use_snapshot_fallback: bool = True) -> dict:
    """
    Le catalogue Actiris entier, converti en JobOffer via convert_actiris_job.

    Rend {"jobs", "report"}. Le rapport donne, par provenance, le total
    annonce par l'API, le nombre lu, et l'origine (LIVE ou SNAPSHOT).
    """
    jobs = []
    report = []
    vus: set[str] = set()
    for mode in ACTIRIS_MODES:
        lecture = lire_catalogue_actiris(mode, max_pages=max_pages_per_mode, verbose=verbose)
        rows = lecture["rows"]
        origine = "LIVE"
        complet = (lecture["erreur"] is None and
                   (max_pages_per_mode or lecture["total_annonce"] is None
                    or len(rows) >= 0.9 * lecture["total_annonce"]))
        if lecture["erreur"] or not complet:
            if verbose:
                print(f"  ⚠️  ACTIRIS {mode} : lecture incomplete "
                      f"({len(rows)}/{lecture['total_annonce']}) — {lecture['erreur'] or 'volume anormal'}")
            if use_snapshot_fallback and not max_pages_per_mode:
                anciennes, meta = _lire_snapshot(f"actiris_{mode}")
                if len(anciennes) > len(rows):
                    rows, origine = anciennes, f"SNAPSHOT {meta.get('generated_at', '?')[:16]}"
                    if verbose:
                        print(f"  ↩  ACTIRIS {mode} : instantane precedent utilise ({len(rows)} offres)")
        elif not max_pages_per_mode:
            _ecrire_snapshot(f"actiris_{mode}", rows,
                             {"mode": mode, "total_annonce": lecture["total_annonce"]})
        convertis = 0
        echecs = 0
        for row in rows:
            ref = str(row.get("reference") or "")
            if ref in vus:
                continue
            try:
                job = _actiris.convert_actiris_job(row)
            except Exception:
                echecs += 1
                continue
            vus.add(ref)
            jobs.append(job)
            convertis += 1
        report.append({
            "mode": mode, "total_annonce": lecture["total_annonce"],
            "lues": len(rows), "converties": convertis, "echecs": echecs,
            "pages": lecture["pages"], "origine": origine,
            "erreur": lecture["erreur"], "duree": lecture["duree"],
        })
    if verbose:
        detail = ", ".join(f"{r['mode']}={r['converties']}" for r in report)
        print(f"  ACTIRIS complet : {len(jobs)} offres ({detail})")
    return {"jobs": jobs, "report": report}


# ------------------------------------------------------------------
# FOREM — export open data complet
# ------------------------------------------------------------------

def _forem_export(limit: int | None = None) -> list[dict]:
    params = {}
    if limit:
        params["limit"] = int(limit)
    r = requests.get(FOREM_EXPORT_URL, params=params, headers=FOREM_HEADERS,
                     timeout=FOREM_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and "results" in data:
        data = data["results"]
    if not isinstance(data, list):
        raise ValueError("export Forem : forme inattendue")
    return data


def _forem_records(limit_total: int | None = None, verbose: bool = True) -> list[dict]:
    """Repli pagine : l'API plafonne l'offset a 10 000, donc partiel au-dela."""
    debut = time.monotonic()
    rows = []
    offset = 0
    page = 100
    while offset < FOREM_RECORDS_MAX_OFFSET:
        r = requests.get(FOREM_RECORDS_URL, params={"limit": page, "offset": offset},
                         headers=FOREM_HEADERS, timeout=60)
        r.raise_for_status()
        results = r.json().get("results") or []
        rows.extend(results)
        offset += page
        if verbose and (offset // page) % 20 == 0:
            _progression("FOREM records", offset // page, 0, len(rows), debut)
        if len(results) < page or (limit_total and len(rows) >= limit_total):
            break
        time.sleep(0.1)
    return rows


def collect_forem_full(verbose: bool = True, limit: int | None = None,
                       use_snapshot_fallback: bool = True) -> dict:
    """
    Tout le jeu de donnees Forem, converti via convert_forem_job.

    La description reste celle de l'open data (metier, secteur, etudes...) ;
    le texte complet vient de forem_detail, appele par le pipeline apres
    collecte, exactement comme avant.
    """
    debut = time.monotonic()
    rows: list[dict] = []
    origine = "LIVE export"
    erreur = None
    try:
        rows = _forem_export(limit=limit)
        if verbose:
            print(f"  FOREM export : {len(rows)} lignes en {_chrono(debut)}")
    except Exception as exc:
        erreur = f"export: {type(exc).__name__}: {exc}"
        if verbose:
            print(f"  ⚠️  FOREM export impossible ({erreur}) — repli sur records")
        try:
            rows = _forem_records(limit_total=limit, verbose=verbose)
            origine = "LIVE records (partiel, plafond 10 000)"
        except Exception as exc2:
            erreur = f"{erreur} ; records: {type(exc2).__name__}: {exc2}"
            rows = []
    if not rows and use_snapshot_fallback and not limit:
        anciennes, meta = _lire_snapshot("forem")
        if anciennes:
            rows, origine = anciennes, f"SNAPSHOT {meta.get('generated_at', '?')[:16]}"
            if verbose:
                print(f"  ↩  FOREM : instantane precedent utilise ({len(rows)} lignes)")
    elif rows and origine == "LIVE export" and not limit:
        _ecrire_snapshot("forem", rows, {"total": len(rows)})

    jobs = []
    vus: set[str] = set()
    echecs = 0
    for row in rows:
        numero = str(row.get("numerooffreforem") or "").strip()
        if not numero or numero in vus:
            continue
        row["_search_terms"] = [MARQUEUR_ABSORPTION]
        try:
            job = convert_forem_job(row)
        except Exception:
            echecs += 1
            continue
        vus.add(numero)
        jobs.append(job)
    if verbose:
        print(f"  FOREM complet : {len(jobs)} offres ({origine}) echecs={echecs}")
    return {"jobs": jobs, "report": {"lues": len(rows), "converties": len(jobs),
                                     "echecs": echecs, "origine": origine,
                                     "erreur": erreur, "duree": _chrono(debut)}}


if __name__ == "__main__":
    # Echantillon : une page par provenance Actiris, 300 lignes Forem.
    a = collect_actiris_full(max_pages_per_mode=1)
    f = collect_forem_full(limit=300)
    print(json.dumps({"actiris": a["report"], "forem": f["report"]}, ensure_ascii=False, indent=1))
