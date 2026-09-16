"""
JOB HUNTER BELGIUM
REGISTRE - ABSORPTION COMPLETE DES SERVICES PUBLICS - VERSION 1.0

Branche sources/absorption_v1.py sur les entrees FOREM et ACTIRIS du
registre, sans toucher a registry.py au-dela d'un appel en fin de fichier
(meme motif que registry_ats_v1.py : resynchronisable par simple copie).

Ce que ca change
----------------
Les cles FOREM et ACTIRIS gardent leur nom : la base, le routeur de detail
de main.py, le lifecycle et les statistiques continuent de les reconnaitre.
Seul le collecteur derriere change : catalogue entier au lieu d'une
recherche par termes.

Le budget de detail
-------------------
La page detail d'une offre coute une requete HTTP. Avec 33 000 offres
Actiris au lieu de 4 000, laisser le pipeline chercher le detail de toute
offre pertinente d'un coup ferait un premier run de plusieurs heures.

Regle appliquee ici, par source et par run :
  1. toute offre pertinente dont le detail est deja en cache est enrichie
     (gratuit : lecture disque) ;
  2. les autres offres pertinentes sont enrichies par ordre de fraicheur,
     jusqu'au budget (defaut 2 500 nouvelles pages par source) ;
  3. le reste attend le run suivant — le cache rend chaque page acquise
     pour toujours, le retard se resorbe en quelques jours.

La relance ou un run de nuit peut augmenter le budget dans
config/absorption_settings.json.

Desactiver
----------
    {"complete": false}  dans config/absorption_settings.json
ramene les deux sources a leur comportement historique.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace
from pathlib import Path


REGISTRY_ABSORPTION_VERSION = "1.0"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = PROJECT_ROOT / "config" / "absorption_settings.json"

DEFAULTS = {
    "complete": True,
    "detail_budget_per_source": 2500,
    "backfill_max_per_run": 3000,
    "sources": ["FOREM", "ACTIRIS"],
}


def charger_reglages() -> dict:
    reglages = dict(DEFAULTS)
    if SETTINGS_PATH.exists():
        try:
            charge = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(charge, dict):
                reglages.update({k: v for k, v in charge.items() if k in DEFAULTS})
        except Exception as erreur:
            print("⚠️ Lecture absorption_settings.json impossible :", erreur)
    return reglages


def ecrire_reglages_par_defaut() -> Path:
    """Cree le fichier s'il manque, pour que l'utilisateur voie les boutons."""
    if not SETTINGS_PATH.exists():
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(DEFAULTS, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    return SETTINGS_PATH


# ------------------------------------------------------------------
# Detail avec budget
# ------------------------------------------------------------------

def _detail_en_cache(source_key: str, job) -> bool:
    try:
        if source_key == "FOREM":
            from sources.forem_detail import get_cache_path
            return Path(get_cache_path(job.external_id)).exists()
        if source_key == "ACTIRIS":
            from sources.actiris_detail import cache_path
            from urllib.parse import parse_qs, urlparse
            offer_type = getattr(job, "actiris_offer_type", None)
            if not offer_type and getattr(job, "url", None):
                offer_type = (parse_qs(urlparse(job.url).query).get("type") or [None])[0]
            return Path(cache_path(job.external_id, offer_type)).exists()
    except Exception:
        return False
    return False


def _enrichir_avec_budget(jobs: list, source_key: str, budget: int) -> list:
    """
    Reprend le contrat de registry._enrich_relevant_details, borne par run.
    """
    from sources import registry as reg

    seuil = reg._DETAIL_ENRICH_THRESHOLD
    pertinentes = []
    for job in jobs:
        if len(reg._detail_clean(getattr(job, "description", None))) >= seuil:
            setattr(job, "detail_enrichment_status", "SKIPPED_RICH")
            continue
        if not reg._detail_is_relevant(job):
            setattr(job, "detail_enrichment_status", "SKIPPED_NOT_RELEVANT")
            continue
        pertinentes.append(job)

    en_cache = [j for j in pertinentes if _detail_en_cache(source_key, j)]
    ids_cache = {id(j) for j in en_cache}
    a_chercher = [j for j in pertinentes if id(j) not in ids_cache]
    a_chercher.sort(key=lambda j: str(getattr(j, "date_published", "") or ""), reverse=True)
    retenues = a_chercher[:max(0, int(budget))]
    reportees = a_chercher[len(retenues):]
    for job in reportees:
        setattr(job, "detail_enrichment_status", "DEFERRED_BUDGET")

    succes = echecs = 0
    for job in en_cache + retenues:
        try:
            detail = reg._fetch_existing_detail(source_key, job)
        except Exception as error:
            detail = {"success": False, "error": f"{type(error).__name__}: {error}"}
        succes += int(bool(detail.get("success")))
        echecs += int(not detail.get("success"))
        reg._apply_detail_contract(job, detail)

    print("DETAIL CONTRACT | "
          f"source={source_key} | pertinentes={len(pertinentes)} | "
          f"cache={len(en_cache)} | nouvelles={len(retenues)} | "
          f"reportees={len(reportees)} | success={succes} | failed={echecs}")
    return jobs


# ------------------------------------------------------------------
# Collecteurs de remplacement
# ------------------------------------------------------------------

def _collect_actiris_complet() -> list:
    from sources.absorption_v1 import collect_actiris_full
    from sources import registry as reg
    resultat = collect_actiris_full(verbose=True)
    jobs = resultat["jobs"]
    origins = Counter(reg._origin(job) for job in jobs)
    if origins:
        print("ACTIRIS - provenance :")
        for origin, count in origins.most_common():
            print(f"  {origin:<15} {count}")
    for ligne in resultat["report"]:
        if ligne.get("erreur") or not str(ligne.get("origine", "")).startswith("LIVE"):
            print(f"  ⚠️  ACTIRIS {ligne['mode']} : {ligne.get('origine')} — {ligne.get('erreur')}")
    return _enrichir_avec_budget(jobs, "ACTIRIS", charger_reglages()["detail_budget_per_source"])


def _collect_forem_complet() -> list:
    from sources.absorption_v1 import collect_forem_full
    resultat = collect_forem_full(verbose=True)
    rapport = resultat["report"]
    if rapport.get("erreur") or not str(rapport.get("origine", "")).startswith("LIVE"):
        print(f"  ⚠️  FOREM : {rapport.get('origine')} — {rapport.get('erreur')}")
    return _enrichir_avec_budget(resultat["jobs"], "FOREM",
                                 charger_reglages()["detail_budget_per_source"])


_COLLECTEURS = {"ACTIRIS": _collect_actiris_complet, "FOREM": _collect_forem_complet}


def appliquer_absorption(specs: tuple) -> tuple:
    """
    Rend SOURCE_SPECS avec FOREM/ACTIRIS remplaces, si l'absorption est active.
    """
    reglages = charger_reglages()
    if not reglages.get("complete", True):
        return specs
    cibles = {str(k).upper() for k in (reglages.get("sources") or [])}
    nouvelles = []
    for spec in specs:
        collecteur = _COLLECTEURS.get(spec.key)
        if collecteur and spec.key in cibles:
            nouvelles.append(replace(
                spec, collector=collecteur,
                notes=(f"ABSORPTION COMPLETE V{REGISTRY_ABSORPTION_VERSION} : catalogue "
                       f"entier, sans termes de recherche. {spec.notes}")))
        else:
            nouvelles.append(spec)
    return tuple(nouvelles)
