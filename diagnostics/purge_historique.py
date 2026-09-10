"""
JOB HUNTER BELGIUM
PURGE DE L'HISTORIQUE ET DES OFFRES DISPARUES - VERSION 1.0

    python -m diagnostics.purge_historique               (constat seul)
    python -m diagnostics.purge_historique --appliquer
    python -m diagnostics.purge_historique --appliquer --runs 5 --builds 3 --jours 60

Ce que la base contient vraiment
--------------------------------
Mesure du 10 septembre 2026, sur une base de 1 648 Mo :

    raw_job_run_items          1 184 Mo   72 %   historique par run
    canonical_jobs               115 Mo    7 %   17 builds conserves
    raw_jobs                     117 Mo    7 %   les offres elles-memes
    dedup_review_candidates       16 Mo    1 %

Autrement dit, les offres pesent 117 Mo et leur historique dix fois plus.
raw_job_run_items garde trois instantanes JSON complets — a la collecte,
apres enrichissement, et le dernier vu — pour chaque offre et chaque run.
Sur 49 runs et ~5 000 offres, cela fait 241 816 lignes.

Ce qui peut partir sans rien casser
-----------------------------------
Rien dans le pipeline ne decide quoi que ce soit a partir de ces tables :

    raw_job_run_items       lu seulement par get_run_snapshot_stats(), qui
                            compte des lignes pour un rapport
    canonical_jobs          seul le build courant sert au rapprochement ;
                            les anciens ne sont conserves que pour memoire
    dedup_review_candidates propositions de fusion a relire, par build

Le Delta Tracker, lui, ne lit pas la base : il compare ses propres artefacts
JSON d'un run a l'autre. Purger l'historique ne l'affecte pas.

Les garde-fous
--------------
1. Les runs et builds les plus recents sont toujours conserves.
2. Une offre encore active n'est jamais supprimee, quel que soit son age.
3. Une offre dont le titre et l'entreprise apparaissent dans le suivi de
   candidatures n'est jamais supprimee, meme inactive : c'est une trace de
   votre parcours, pas de la donnee de travail.
4. Les enfants sont supprimes avant les parents, dans l'ordre des cles
   etrangeres.
5. Par defaut, ce module ne modifie RIEN.
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


PURGE_VERSION = "1.0"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "database" / "jobs.db"
LOG_DIR = PROJECT_ROOT / "exports" / "logs"

# Valeurs par defaut : assez larges pour qu'un retour en arriere reste
# possible, assez serrees pour que la purge serve a quelque chose.
RUNS_CONSERVES = 3
BUILDS_CONSERVES = 2
JOURS_AVANT_SUPPRESSION = 30


def mo(connexion: sqlite3.Connection) -> float:
    pages = connexion.execute("PRAGMA page_count").fetchone()[0]
    taille = connexion.execute("PRAGMA page_size").fetchone()[0]
    return pages * taille / 1048576


def _un(connexion, requete, *args) -> int:
    return int(connexion.execute(requete, args).fetchone()[0] or 0)


def recenser(connexion: sqlite3.Connection, runs: int, builds: int,
             jours: int) -> dict:
    """Ce qui serait supprime, sans rien supprimer."""
    runs_gardes = [r[0] for r in connexion.execute(
        "SELECT run_id FROM collection_runs ORDER BY started_at DESC LIMIT ?",
        (runs,))]
    builds_gardes = [r[0] for r in connexion.execute(
        "SELECT build_id FROM canonical_builds ORDER BY build_id DESC LIMIT ?",
        (builds,))]

    marque_runs = ",".join("?" * len(runs_gardes)) or "''"
    marque_builds = ",".join("?" * len(builds_gardes)) or "''"

    limite = (datetime.now() - timedelta(days=jours)).isoformat(
        timespec="seconds")

    return {
        "runs_gardes": runs_gardes,
        "builds_gardes": builds_gardes,
        "limite_date": limite,
        "items": _un(connexion,
                     f"SELECT COUNT(*) FROM raw_job_run_items "
                     f"WHERE run_id NOT IN ({marque_runs})", *runs_gardes),
        "items_total": _un(connexion, "SELECT COUNT(*) FROM raw_job_run_items"),
        "canoniques": _un(connexion,
                          f"SELECT COUNT(*) FROM canonical_jobs "
                          f"WHERE build_id NOT IN ({marque_builds})",
                          *builds_gardes),
        "sources_can": _un(connexion,
                           f"SELECT COUNT(*) FROM canonical_job_sources "
                           f"WHERE build_id NOT IN ({marque_builds})",
                           *builds_gardes),
        "dedup": _un(connexion,
                     f"SELECT COUNT(*) FROM dedup_review_candidates "
                     f"WHERE build_id NOT IN ({marque_builds})",
                     *builds_gardes),
        "offres": _un(connexion,
                      "SELECT COUNT(*) FROM raw_jobs WHERE is_active = 0 "
                      "AND COALESCE(last_seen, first_seen, '') < ? "
                      "AND NOT EXISTS (SELECT 1 FROM application_entities ae "
                      "  WHERE ae.title = raw_jobs.title "
                      "    AND ae.company = raw_jobs.company)",
                      limite),
        "offres_inactives": _un(connexion,
                                "SELECT COUNT(*) FROM raw_jobs WHERE is_active = 0"),
        "offres_actives": _un(connexion,
                              "SELECT COUNT(*) FROM raw_jobs WHERE is_active = 1"),
        "offres_protegees": _un(connexion,
                                "SELECT COUNT(*) FROM raw_jobs WHERE is_active = 0 "
                                "AND EXISTS (SELECT 1 FROM application_entities ae "
                                "  WHERE ae.title = raw_jobs.title "
                                "    AND ae.company = raw_jobs.company)"),
    }


def appliquer(connexion: sqlite3.Connection, plan: dict) -> None:
    """Supprime dans l'ordre des cles etrangeres : enfants d'abord."""
    runs = plan["runs_gardes"]
    builds = plan["builds_gardes"]
    mr = ",".join("?" * len(runs)) or "''"
    mb = ",".join("?" * len(builds)) or "''"

    connexion.execute(
        f"DELETE FROM raw_job_run_items WHERE run_id NOT IN ({mr})", runs)
    connexion.execute(
        f"DELETE FROM dedup_review_candidates WHERE build_id NOT IN ({mb})",
        builds)
    connexion.execute(
        f"DELETE FROM canonical_job_sources WHERE build_id NOT IN ({mb})",
        builds)
    connexion.execute(
        f"DELETE FROM canonical_jobs WHERE build_id NOT IN ({mb})", builds)
    connexion.execute(
        f"DELETE FROM canonical_builds WHERE build_id NOT IN ({mb})", builds)

    # Les offres en dernier : leurs enfants viennent de disparaitre. Celles
    # qui restent referencees par un build ou un run conserve sont laissees
    # en place — supprimer un parent encore reference casserait la base.
    connexion.execute(
        "DELETE FROM raw_jobs WHERE is_active = 0 "
        "AND COALESCE(last_seen, first_seen, '') < ? "
        "AND NOT EXISTS (SELECT 1 FROM application_entities ae "
        "  WHERE ae.title = raw_jobs.title AND ae.company = raw_jobs.company) "
        "AND id NOT IN (SELECT raw_job_id FROM raw_job_run_items) "
        "AND id NOT IN (SELECT raw_job_id FROM canonical_job_sources) "
        "AND id NOT IN (SELECT preferred_raw_job_id FROM canonical_jobs "
        "               WHERE preferred_raw_job_id IS NOT NULL)",
        (plan["limite_date"],))

    connexion.commit()


def main() -> None:
    parseur = argparse.ArgumentParser()
    parseur.add_argument("--appliquer", action="store_true")
    parseur.add_argument("--runs", type=int, default=RUNS_CONSERVES)
    parseur.add_argument("--builds", type=int, default=BUILDS_CONSERVES)
    parseur.add_argument("--jours", type=int, default=JOURS_AVANT_SUPPRESSION)
    parseur.add_argument("--vacuum", action="store_true",
                         help="compacte le fichier apres la purge")
    args = parseur.parse_args()

    print("=" * 92)
    print(f"PURGE DE L'HISTORIQUE V{PURGE_VERSION}")
    print("=" * 92)
    print()

    if not DB_PATH.exists():
        raise SystemExit(f"[FAIL] Base introuvable : {DB_PATH}")

    suffixe = "" if args.appliquer else "?mode=ro"
    connexion = sqlite3.connect(f"{DB_PATH.resolve().as_uri()}{suffixe}",
                                uri=True)
    try:
        avant = mo(connexion)
        plan = recenser(connexion, args.runs, args.builds, args.jours)

        print(f"Taille de la base : {avant:.0f} Mo")
        print()
        print(f"Runs conserves    : {len(plan['runs_gardes'])} "
              f"({', '.join(r[:22] for r in plan['runs_gardes'][:3])})")
        print(f"Builds conserves  : {len(plan['builds_gardes'])}")
        print(f"Offres supprimees si inactives avant le "
              f"{plan['limite_date'][:10]}")
        print()
        print("A SUPPRIMER")
        print(f"  historique par run     {plan['items']:>9} / "
              f"{plan['items_total']} lignes")
        print(f"  offres canoniques      {plan['canoniques']:>9} lignes")
        print(f"  liens canoniques       {plan['sources_can']:>9} lignes")
        print(f"  propositions de fusion {plan['dedup']:>9} lignes")
        print(f"  offres disparues       {plan['offres']:>9} lignes")
        print()
        print("CONSERVE")
        print(f"  offres actives         {plan['offres_actives']:>9}")
        print(f"  offres inactives       {plan['offres_inactives']:>9} "
              f"(dont {plan['offres']} eligibles a la suppression)")
        print(f"  offres liees a une candidature suivie "
              f"{plan['offres_protegees']:>4} — jamais supprimees")

        if not args.appliquer:
            print()
            print("CONSTAT SEUL — rien n'a ete modifie.")
            print("Relancer avec --appliquer pour purger, "
                  "et --vacuum pour compacter.")
            return

        print()
        print("Purge en cours...")
        appliquer(connexion, plan)
        apres_purge = mo(connexion)
        print(f"Purge terminee. Base : {apres_purge:.0f} Mo "
              f"(pages liberees, fichier pas encore compacte)")

        if args.vacuum:
            print("Compactage (VACUUM) en cours — cela peut prendre "
                  "plusieurs minutes...")
            connexion.execute("VACUUM")
            print("Compactage termine.")
    finally:
        connexion.close()

    if args.appliquer:
        finale = DB_PATH.stat().st_size / 1048576
        print()
        print(f"AVANT : {avant:>8.0f} Mo")
        print(f"APRES : {finale:>8.0f} Mo")
        print(f"LIBERE: {avant - finale:>8.0f} Mo")

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        (LOG_DIR / f"purge_historique_{stamp}.txt").write_text(
            "\n".join([f"PURGE DE L'HISTORIQUE V{PURGE_VERSION}", "=" * 92,
                       f"Avant : {avant:.0f} Mo", f"Apres : {finale:.0f} Mo",
                       f"Historique supprime : {plan['items']} lignes",
                       f"Offres supprimees : {plan['offres']} lignes"]),
            encoding="utf-8")


if __name__ == "__main__":
    main()
