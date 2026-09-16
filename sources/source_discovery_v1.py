"""
JOB HUNTER BELGIUM
MOTEUR DE DECOUVERTE DE SOURCES - VERSION 1.0

    entreprise / domaine / URL
            ↓
    page carriere                (ats_detector_v1.detecter_site)
            ↓
    ATS reconnu ?  ── oui ──→  connecteur existant ──→ validation (liste seule)
            │                                                  ↓
            non                                    config/ats_employers_v2.json
            ↓
    sitemap + JSON-LD ?  ── oui ──→  JSONLD_SITES ──→ validation (3 pages)
            │
            non
            ↓
    devine un identifiant d'API (recruitee, lever, greenhouse, ashby,
    workable, smartrecruiters, personio) a partir du nom
            ↓
    trace en rapport : "aucune voie publique connue"

Une entreprise n'est plus ajoutee a la main, connecteur par connecteur :
on lui donne un domaine, le moteur trouve la voie et l'enregistre.

Cout
----
Detection : 1 a 10 requetes par domaine. Validation : 1 requete (API),
1 a 3 (sitemap), au plus 4 (pages JSON-LD). Aucune collecte complete ici.

Sorties
-------
exports/logs/discovery_<horodatage>/
    SOURCE_RESULTS.jsonl   une ligne par candidat
    REPORT.txt             lisible
    DIAGNOSTIC.json        compteurs
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests

from sources.ats_detector_v1 import detecter_site, detecter_url, charger_signatures
from sources import ats_employers_v2 as registre


SOURCE_DISCOVERY_VERSION = "1.0"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "exports" / "logs"

PAUSE_ENTRE_CANDIDATS = 0.3
VALIDATION_PAGES_JSONLD = 3


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _clean(v) -> str:
    return "" if v is None else str(v).strip()


# ------------------------------------------------------------------
# Validation par connecteur : liste seule, cout borne
# ------------------------------------------------------------------

def _valider(connecteur: str, identifiant, label: str, session) -> dict:
    """Rend {"ok", "total", "be", "erreur"}."""
    r = {"ok": False, "total": None, "be": None, "erreur": None}
    try:
        if connecteur == "GREENHOUSE":
            from sources.greenhouse import collect_greenhouse_jobs
            res = collect_greenhouse_jobs(companies=[{"identifier": identifiant, "label": label, "enabled": True}], verbose=False)
            l = res["report"][0]
            r.update(ok=not l.get("error"), total=l.get("offers_total"), be=l.get("retained"), erreur=l.get("error"))
        elif connecteur == "RECRUITEE":
            from sources.recruitee import collect_recruitee_jobs
            res = collect_recruitee_jobs(companies=[{"identifier": identifiant, "label": label, "enabled": True}], verbose=False)
            l = res["report"][0]
            r.update(ok=not l.get("error"), total=l.get("offers_total"), be=l.get("converted"), erreur=l.get("error"))
        elif connecteur == "SMARTRECRUITERS":
            from sources.smartrecruiters import fetch_smartrecruiters_jobs
            jobs, metas = fetch_smartrecruiters_jobs(companies=[{"identifier": identifiant, "label": label, "enabled": True}], detail_limit_per_company=1)
            m = metas[0]
            r.update(ok=not m.get("fatal_error"), total=m.get("listings_total") or m.get("listings_belgium"),
                     be=m.get("listings_belgium"), erreur=m.get("fatal_error"))
        elif connecteur == "WORKDAY_ATS":
            from sources.workday_ats_v1 import fetch_job_list, looks_belgian
            company = dict(identifiant, label=label)
            postings, erreur = fetch_job_list(company)
            r.update(ok=not erreur, total=len(postings), be=sum(1 for p in postings if looks_belgian(p)), erreur=erreur)
        elif connecteur in ("SUCCESSFACTORS_ATS", "PHENOM_ATS"):
            # D'abord le lecteur de sitemap du connecteur lui-meme (eprouve),
            # puis le lecteur generique (index, robots.txt) s'il ne voit rien.
            if connecteur == "SUCCESSFACTORS_ATS":
                from sources.successfactors_ats_v1 import fetch_sitemap_urls
            else:
                from sources.phenom_ats_v1 import fetch_sitemap_urls
            urls, erreur = fetch_sitemap_urls(identifiant)
            if not urls:
                from sources.jsonld_sitemap_v1 import urls_offres
                entrees, erreur2 = urls_offres(identifiant, session, max_sitemaps=8)
                urls = [u for u, _ in entrees if "/job/" in u]
                erreur = None if urls else (erreur2 or erreur)
            r.update(ok=bool(urls), total=len(urls), be=None, erreur=erreur)
        elif connecteur in ("LEVER", "ASHBY", "WORKABLE", "PERSONIO"):
            from sources.ats_public_v2 import COLLECTEURS
            kw = {"max_details": 0} if connecteur == "WORKABLE" else {}
            jobs, meta = COLLECTEURS[connecteur](identifiant, label, session, include_unknown=False, **kw)
            r.update(ok=True, total=meta.get("total"), be=len(jobs))
        elif connecteur == "ORACLE_CLOUD":
            from sources.oracle_cloud_v1 import lister
            from sources.ats_public_v2 import _statut_be, _retenir
            lignes = lister(identifiant["host"], identifiant["site"], session)
            be = sum(1 for r in lignes if _retenir(_statut_be(str(r.get("PrimaryLocation") or ""), str(r.get("PrimaryLocationCountry") or "")), False))
            r.update(ok=True, total=len(lignes), be=be)
        elif connecteur == "CVWAREHOUSE":
            from sources.cvwarehouse_v1 import lister
            lignes = lister(identifiant, "nl-BE", session)
            r.update(ok=bool(lignes), total=len(lignes), be=None,
                     erreur=None if lignes else "aucune offre listee")
        elif connecteur == "JSONLD_SITES":
            from sources.jsonld_sitemap_v1 import collect_site
            jobs, meta = collect_site(identifiant, label, session, max_pages=VALIDATION_PAGES_JSONLD,
                                      max_sitemaps=8)
            visitees = meta.get("visitees", 0) + meta.get("cache", 0)
            r.update(ok=(not meta.get("error")) and meta.get("be", 0) > 0,
                     total=meta.get("sitemap_urls"), be=meta.get("be"),
                     erreur=meta.get("error") or (f"{meta.get('sans_jsonld')}/{visitees} pages sans JSON-LD" if not meta.get("be") else None))
        else:
            r["erreur"] = f"connecteur inconnu {connecteur}"
    except Exception as e:
        r["erreur"] = f"{type(e).__name__}: {str(e)[:120]}"
    return r


# ------------------------------------------------------------------
# Devinette d'identifiant d'API a partir du nom
# ------------------------------------------------------------------

def _variantes(nom: str) -> list[str]:
    base = re.sub(r"\b(sa|nv|bv|bvba|sprl|srl|group|groupe|belgium|belgique|belgie|be)\b", " ",
                  _clean(nom).lower())
    base = re.sub(r"[^a-z0-9 ]+", " ", base).strip()
    mots = base.split()
    if not mots:
        return []
    v = ["".join(mots), "-".join(mots), mots[0]]
    if len(mots) > 1:
        v.append("".join(m[0] for m in mots))
    return list(dict.fromkeys(x for x in v if len(x) >= 3))


_SONDES_API = ("RECRUITEE", "LEVER", "GREENHOUSE", "ASHBY", "WORKABLE", "PERSONIO")


def _deviner(label: str, session) -> dict | None:
    for ats in _SONDES_API:
        spec = charger_signatures()["ats"][ats]
        for slug in _variantes(label)[:3]:
            v = _valider(spec["connector"], slug, label, session)
            # Un slug devine est un pari : on ne le garde que s'il a au moins
            # une offre belge (un homonyme etranger en a rarement).
            if v["ok"] and (v["be"] or 0) > 0:
                return {"ats": ats, "connecteur": spec["connector"], "identifiant": slug,
                        "preuve": "DEVINE", "validation": v}
            time.sleep(0.1)
    return None


# ------------------------------------------------------------------
# Un candidat
# ------------------------------------------------------------------

def traiter_candidat(candidat: dict, session, deviner: bool = True) -> dict:
    """
    candidat = {"domaine": "ucb.com", "label": "UCB", "discovered_by": "seed:pharma"}
    ou {"url": "https://jobs.lever.co/x/..."} (detection hors ligne d'abord).
    """
    label = _clean(candidat.get("label")) or _clean(candidat.get("domaine")) or _clean(candidat.get("url"))
    entree = _clean(candidat.get("url")) or _clean(candidat.get("domaine"))
    ligne = {"label": label, "entree": entree, "discovered_by": _clean(candidat.get("discovered_by")) or "manuel",
             "ats": None, "connecteur": None, "identifiant": None, "preuve": None,
             "validation": None, "enregistre": False, "statut": "AUCUNE_VOIE", "page_carriere": None}

    det = detecter_url(entree) if entree.startswith("http") else None
    if not det or not det.get("identifiant"):
        det = detecter_site(entree, session=session)
    ligne["page_carriere"] = det.get("page_carriere") or det.get("url_finale")

    if det.get("ats"):
        ligne.update(ats=det["ats"], connecteur=det.get("connecteur"), identifiant=det.get("identifiant"),
                     preuve=det.get("preuve"))
        if det.get("connecteur") and det.get("identifiant"):
            v = _valider(det["connecteur"], det["identifiant"], label, session)
            ligne["validation"] = v
            if v["ok"]:
                registre.enregistrer(det["ats"], det["connecteur"], det["identifiant"], label,
                                     jobs_total=v["total"], jobs_be=v["be"], discovered_by=ligne["discovered_by"],
                                     career_url=ligne["page_carriere"])
                ligne.update(enregistre=True, statut="ACTIVE")
                return ligne
            ligne["statut"] = "ATS_RECONNU_VALIDATION_ECHOUEE"
        else:
            ligne["statut"] = "ATS_SANS_CONNECTEUR" if not det.get("connecteur") else "ATS_SANS_IDENTIFIANT"

    # Voie universelle : le site carriere publie-t-il sitemap + JSON-LD ?
    hote = None
    for u in (ligne["page_carriere"], f"https://www.{entree}" if not entree.startswith("http") else entree):
        if u:
            hote = urlsplit(u).netloc.lower()
            break
    if hote and ligne["statut"] != "ACTIVE":
        v = _valider("JSONLD_SITES", hote, label, session)
        if v["ok"]:
            registre.enregistrer("JSONLD", "JSONLD_SITES", hote, label, jobs_total=v["total"], jobs_be=v["be"],
                                 discovered_by=ligne["discovered_by"], career_url=ligne["page_carriere"])
            ligne.update(ats=ligne["ats"] or "JSONLD", connecteur="JSONLD_SITES", identifiant=hote,
                         preuve=ligne["preuve"] or "SITEMAP", validation=v, enregistre=True, statut="ACTIVE")
            return ligne
        ligne.setdefault("essais_universel", v)

    if deviner and ligne["statut"] != "ACTIVE":
        d = _deviner(label, session)
        if d:
            registre.enregistrer(d["ats"], d["connecteur"], d["identifiant"], label,
                                 jobs_total=d["validation"]["total"], jobs_be=d["validation"]["be"],
                                 discovered_by=ligne["discovered_by"] + "+devine", career_url=ligne["page_carriere"])
            ligne.update(**{k: d[k] for k in ("ats", "connecteur", "identifiant", "preuve", "validation")},
                         enregistre=True, statut="ACTIVE")
    return ligne


# ------------------------------------------------------------------
# Une campagne
# ------------------------------------------------------------------

def decouvrir(candidats: list[dict], verbose: bool = True, deviner: bool = True,
              dossier: Path | None = None, workers: int = 6) -> dict:
    session = requests.Session()
    debut = time.monotonic()
    dossier = dossier or (LOG_DIR / f"discovery_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    dossier.mkdir(parents=True, exist_ok=True)
    # Deux campagnes sur le meme dossier s'ecriraient l'une sur l'autre
    # (constate le 15/09/2026 : une ligne de resultats coupee en deux).
    verrou = dossier / ".en_cours"
    if verrou.exists():
        raise RuntimeError(f"Une campagne est deja en cours dans {dossier} "
                           f"(supprimer {verrou.name} si elle est morte).")
    verrou.write_text(_now(), encoding="utf-8")
    lignes = []
    deja = {(str(e.get("ats")), str(e.get("identifier")).lower()) for e in registre.charger()["employers"]}
    total = len(candidats)
    if verbose:
        print("=" * 76)
        print(f"  DECOUVERTE DE SOURCES V{SOURCE_DISCOVERY_VERSION} — {total} candidats")
        print("=" * 76)
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _un(c):
        try:
            return traiter_candidat(c, requests.Session(), deviner=deviner)
        except Exception as e:
            return {"label": c.get("label"), "entree": c.get("domaine") or c.get("url"),
                    "statut": "ERREUR", "erreur": f"{type(e).__name__}: {e}", "enregistre": False}

    with (dossier / "SOURCE_RESULTS.jsonl").open("w", encoding="utf-8") as sortie,             ThreadPoolExecutor(max_workers=workers) as pool:
        futurs = {pool.submit(_un, c): c for c in candidats}
        for i, futur in enumerate(as_completed(futurs), 1):
            ligne = futur.result()
            ligne["nouveau"] = ligne.get("enregistre") and (str(ligne.get("ats")), str(ligne.get("identifiant")).lower()) not in deja
            lignes.append(ligne)
            sortie.write(json.dumps(ligne, ensure_ascii=False, default=str) + "\n")
            if verbose:
                v = ligne.get("validation") or {}
                ecoule = int(time.monotonic() - debut)
                tot = "-" if v.get("total") is None else str(v.get("total"))
                be = "-" if v.get("be") is None else str(v.get("be"))
                print(f"  [{i:>3}/{total}] {str(ligne.get('label'))[:26]:<26} "
                      f"{str(ligne.get('ats') or '-'):<15} {str(ligne.get('connecteur') or '-'):<18} "
                      f"{str(ligne.get('statut')):<34} total={tot:<5} BE={be:<4} "
                      f"{ecoule // 60:02d}:{ecoule % 60:02d}", flush=True)

    from collections import Counter
    diag = {
        "version": SOURCE_DISCOVERY_VERSION, "generated_at": _now(), "candidats": total,
        "duree_s": int(time.monotonic() - debut),
        "par_statut": dict(Counter(l.get("statut") for l in lignes)),
        "par_ats": dict(Counter(l.get("ats") for l in lignes if l.get("ats"))),
        "enregistres": sum(1 for l in lignes if l.get("enregistre")),
        "nouveaux": sum(1 for l in lignes if l.get("nouveau")),
        "offres_be_validees": sum(int((l.get("validation") or {}).get("be") or 0) for l in lignes if l.get("enregistre")),
        "registre": registre.resume(),
    }
    (dossier / "DIAGNOSTIC.json").write_text(json.dumps(diag, ensure_ascii=False, indent=1), encoding="utf-8")
    rapport = [f"DECOUVERTE DE SOURCES V{SOURCE_DISCOVERY_VERSION} — {diag['generated_at']}", "",
               f"Candidats : {total}   Enregistres : {diag['enregistres']}   Nouveaux : {diag['nouveaux']}   "
               f"Offres belges validees : {diag['offres_be_validees']}", "",
               "Par statut : " + ", ".join(f"{k}={v}" for k, v in diag["par_statut"].items()),
               "Par ATS    : " + ", ".join(f"{k}={v}" for k, v in diag["par_ats"].items()), ""]
    for l in lignes:
        v = l.get("validation") or {}
        rapport.append(f"{str(l.get('statut')):<34} {str(l.get('label'))[:28]:<28} {str(l.get('ats') or '-'):<15} "
                       f"{str(l.get('identifiant') or '-')[:40]:<40} total={v.get('total') if v else '-'} BE={v.get('be') if v else '-'} "
                       f"{('ERR ' + str(v.get('erreur'))[:60]) if v and v.get('erreur') else ''}")
    (dossier / "REPORT.txt").write_text("\n".join(rapport), encoding="utf-8")
    verrou.unlink(missing_ok=True)
    diag["dossier"] = str(dossier)
    if verbose:
        print()
        print(f"  Enregistres : {diag['enregistres']} ({diag['nouveaux']} nouveaux) — "
              f"offres belges validees : {diag['offres_be_validees']} — {diag['duree_s']} s")
        print(f"  Rapport : {dossier}")
    return diag


def charger_seeds(chemin: Path | None = None) -> list[dict]:
    chemin = chemin or (PROJECT_ROOT / "config" / "discovery_seeds_v1.json")
    data = json.loads(chemin.read_text(encoding="utf-8"))
    candidats = []
    for groupe, entrees in (data.get("groups") or {}).items():
        for e in entrees:
            if isinstance(e, str):
                candidats.append({"domaine": e, "label": e.split(".")[0].title(), "discovered_by": f"seed:{groupe}"})
            else:
                candidats.append({**e, "discovered_by": e.get("discovered_by") or f"seed:{groupe}"})
    return candidats


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if args:
        cands = [{"domaine": a, "label": a.split(".")[0].title(), "discovered_by": "cli"} for a in args]
    else:
        cands = charger_seeds()
    decouvrir(cands)
