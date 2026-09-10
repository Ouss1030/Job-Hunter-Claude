"""
JOB HUNTER BELGIUM
RECUPERATION DES DESCRIPTIONS MANQUANTES - VERSION 1.0

    python -m diagnostics.detail_backfill --essai 20
    python -m diagnostics.detail_backfill --source ACTIRIS
    python -m diagnostics.detail_backfill --toutes
    python -m diagnostics.detail_backfill --etat

Le probleme
-----------
Sans le texte de l'annonce, on ne peut juger une offre que sur son intitule.
Mesure au 8 septembre 2026 : 4 889 offres actives n'ont jamais ete tentees en
enrichissement, dont 4 194 chez Actiris qui represente 72 % de la base.

Quand l'enrichissement EST tente, il reussit : sur 189 tentatives Actiris,
189 succes, dont 188 avec plus de 300 caracteres et 151 avec plus de 2 000.

Le mecanisme fonctionne. Il n'est simplement jamais declenche, parce que
main.py demande au pre-score s'il faut aller chercher la description — et le
pre-score se calcule sur la description absente. Une offre sans texte
n'obtient donc jamais son texte.

Ce que fait cet outil
---------------------
Il rattrape ce retard sur les offres DEJA en base, independamment de toute
collecte. Il reutilise la mecanique existante sans la dupliquer :

    main.get_job_detail(job)        routage par source, avec cache
    main.apply_structured_data      champs structures
    upsert_enriched_job             ecriture

Reprise et interruption
-----------------------
Chaque offre est ecrite des qu'elle est enrichie. On peut arreter a tout
moment : la commande suivante reprend ou elle en etait, puisqu'elle
interroge simplement ce qui manque encore.

Jobat
-----
La politique du projet impose CACHE_ONLY pour Jobat : pas de repli navigateur
sur 403. Cet outil refuse donc Jobat par defaut. Le forcer demande
--autoriser-jobat, et c'est une decision a prendre en connaissance de cause.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path


BACKFILL_VERSION = "1.0"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "database" / "jobs.db"

# Delai entre deux requetes reelles. Le cache ne compte pas : une offre deja
# en cache ne coute rien et n'attend pas.
DELAI_ENTRE_REQUETES = 0.8

SOURCES_SUPPORTEES = ("ACTIRIS", "FOREM", "TALENT_BRUSSELS")
SOURCE_CACHE_ONLY = "JOBAT"

SEUIL_TEXTE_UTILE = 300


def _connexion_lecture() -> sqlite3.Connection:
    con = sqlite3.connect(f"{DB_PATH.resolve().as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def offres_a_enrichir(source: str | None, limite: int | None) -> list[sqlite3.Row]:
    """Offres actives sans texte exploitable et jamais tentees."""
    con = _connexion_lecture()
    conditions = [
        "is_active = 1",
        "detail_enrichment_attempted IS NULL",
        f"LENGTH(COALESCE(detail_matching_text, description, '')) < {SEUIL_TEXTE_UTILE}",
    ]
    params: list = []
    if source:
        conditions.append("source = ?")
        params.append(source.upper())
    requete = ("SELECT * FROM raw_jobs WHERE " + " AND ".join(conditions)
               + " ORDER BY date_collected DESC")
    if limite:
        requete += f" LIMIT {int(limite)}"
    lignes = con.execute(requete, params).fetchall()
    con.close()
    return lignes


def etat() -> dict[str, int]:
    con = _connexion_lecture()
    lignes = con.execute(
        "SELECT source, "
        "  SUM(CASE WHEN LENGTH(COALESCE(detail_matching_text, description,'')) "
        f"      >= {SEUIL_TEXTE_UTILE} THEN 1 ELSE 0 END), "
        "  COUNT(*) "
        "FROM raw_jobs WHERE is_active = 1 GROUP BY source ORDER BY 3 DESC"
    ).fetchall()
    con.close()
    return lignes


def _reconstruire(ligne: sqlite3.Row):
    """
    Reconstruit un objet offre a partir d'une ligne de la base.

    JobOffer attend `external_id` la ou la table stocke
    `source_external_id` : c'est exactement le genre d'ecart qui fait croire
    a une panne d'enrichissement alors que seul le nom differe.
    """
    from database.models import JobOffer

    cles = set(ligne.keys())
    job = JobOffer(
        source=ligne["source"],
        external_id=(ligne["source_external_id"]
                     if "source_external_id" in cles else None),
        title=ligne["title"],
        company=ligne["company"],
        location=ligne["location"],
        description=ligne["description"],
        url=ligne["url"],
        date_published=ligne["date_published"],
        contract_type=ligne["contract_type"],
        language=ligne["language"],
        salary=ligne["salary"],
        date_collected=ligne["date_collected"],
    )
    if "origin_source" in cles and ligne["origin_source"]:
        setattr(job, "origin_source", ligne["origin_source"])
    return job


def enrichir(job, run_id: str) -> tuple[bool, int, str]:
    """Renvoie (succes, longueur du texte, message)."""
    import main as pipeline
    from database.enriched_batch import upsert_enriched_job

    try:
        detail = pipeline.get_job_detail(job)
    except Exception as exc:
        return False, 0, f"{type(exc).__name__}: {exc}"

    if not detail or not detail.get("success"):
        return False, 0, str((detail or {}).get("error") or "detail indisponible")

    texte = detail.get("matching_text") or ""
    try:
        pipeline.apply_structured_data(job, detail)
    except Exception as exc:
        return False, len(texte), f"structure: {type(exc).__name__}: {exc}"

    setattr(job, "detail_enrichment_attempted", True)
    setattr(job, "detail_enrichment_success", True)
    setattr(job, "detail_matching_text", texte)
    setattr(job, "detail_matching_text_length", len(texte))
    setattr(job, "detail_from_cache", bool(detail.get("from_cache")))
    setattr(job, "detail_enrichment_error", None)

    try:
        upsert_enriched_job(job, run_id=run_id)
    except Exception as exc:
        return False, len(texte), f"ecriture: {type(exc).__name__}: {exc}"

    return True, len(texte), "cache" if detail.get("from_cache") else "reseau"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Recuperation des descriptions manquantes")
    parser.add_argument("--source", type=str, help="Une seule source")
    parser.add_argument("--essai", type=int,
                        help="Traite N offres pour verifier la qualite")
    parser.add_argument("--toutes", action="store_true")
    parser.add_argument("--etat", action="store_true",
                        help="Affiche la couverture actuelle, ne fait rien")
    parser.add_argument("--delai", type=float, default=DELAI_ENTRE_REQUETES)
    parser.add_argument("--autoriser-jobat", action="store_true",
                        help="Leve le garde CACHE_ONLY sur Jobat")
    args = parser.parse_args(argv)

    if args.etat:
        print("=" * 78)
        print("COUVERTURE DES DESCRIPTIONS")
        print("=" * 78)
        print(f"  {'SOURCE':<22}{'avec texte':>12}{'total':>8}{'%':>8}")
        total_ok = total = 0
        for source, avec, tot in etat():
            avec = avec or 0
            total_ok += avec
            total += tot
            print(f"  {source:<22}{avec:>12}{tot:>8}{100*avec/tot:>7.1f}%")
        print("  " + "-" * 48)
        print(f"  {'ENSEMBLE':<22}{total_ok:>12}{total:>8}"
              f"{100*total_ok/max(total,1):>7.1f}%")
        return 0

    if not (args.source or args.essai or args.toutes):
        parser.error("Choisir --etat, --essai N, --source X ou --toutes")

    source = (args.source or "").upper() or None
    if source == SOURCE_CACHE_ONLY and not args.autoriser_jobat:
        print(f"[STOP] {SOURCE_CACHE_ONLY} est en CACHE_ONLY dans la politique "
              "du projet.")
        print("       Son connecteur bascule sur un navigateur en cas de 403.")
        print("       Utiliser --autoriser-jobat seulement en connaissance de cause.")
        return 1

    lignes = offres_a_enrichir(source, args.essai)
    if not source and not args.autoriser_jobat:
        avant = len(lignes)
        lignes = [l for l in lignes if l["source"] != SOURCE_CACHE_ONLY]
        ecartees = avant - len(lignes)
    else:
        ecartees = 0

    print("=" * 78)
    print(f"RECUPERATION DES DESCRIPTIONS V{BACKFILL_VERSION}")
    print("=" * 78)
    print(f"  offres a traiter : {len(lignes)}")
    if ecartees:
        print(f"  ecartees (Jobat CACHE_ONLY) : {ecartees}")
    print(f"  delai entre requetes : {args.delai}s")
    print("  interruption possible a tout moment : chaque offre est ecrite "
          "immediatement")
    print()

    if not lignes:
        print("  Rien a faire.")
        return 0

    import main as pipeline
    from database.db import start_collection_run, finish_collection_run

    # raw_jobs.last_run_id est une cle etrangere vers collection_runs.
    # Un identifiant invente echoue donc a l'ecriture — et l'operation doit
    # de toute facon apparaitre dans l'historique des runs.
    run_id = start_collection_run(
        notes=f"detail_backfill v{BACKFILL_VERSION} — recuperation des "
              f"descriptions manquantes ({len(lignes)} offres)")
    if isinstance(run_id, (tuple, list)):
        run_id = run_id[0]
    if isinstance(run_id, dict):
        run_id = run_id.get("run_id")
    print(f"  run de collecte : {run_id}")
    print()

    ok = echecs = depuis_cache = 0
    total_car = 0
    erreurs: dict[str, int] = {}
    t0 = time.time()

    for i, ligne in enumerate(lignes, 1):
        job = _reconstruire(ligne)
        succes, longueur, message = enrichir(job, run_id)

        if succes:
            ok += 1
            total_car += longueur
            if message == "cache":
                depuis_cache += 1
            else:
                time.sleep(args.delai)
        else:
            echecs += 1
            cle = message.split(":")[0][:40]
            erreurs[cle] = erreurs.get(cle, 0) + 1
            time.sleep(args.delai)

        if i % 25 == 0 or i == len(lignes):
            ecoule = time.time() - t0
            reste = (ecoule / i) * (len(lignes) - i)
            print(f"  {i:>5}/{len(lignes)}  ok={ok:<5} echecs={echecs:<4} "
                  f"cache={depuis_cache:<5} "
                  f"moy={total_car // max(ok, 1):>5} car.  "
                  f"reste ~{reste/60:.0f} min", flush=True)

    duree = time.time() - t0
    try:
        finish_collection_run(run_id)
    except Exception:
        pass

    print()
    print("=" * 78)
    print(f"TERMINE en {duree/60:.1f} min")
    print("=" * 78)
    print(f"  enrichies          : {ok}")
    print(f"  echecs             : {echecs}")
    print(f"  servies par cache  : {depuis_cache}")
    print(f"  longueur moyenne   : {total_car // max(ok, 1)} caracteres")
    if erreurs:
        print("\n  motifs d'echec :")
        for cle, n in sorted(erreurs.items(), key=lambda x: -x[1])[:8]:
            print(f"    {n:>5}  {cle}")
    print("\n  Verifier la couverture :")
    print("    python -m diagnostics.detail_backfill --etat")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
