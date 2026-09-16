"""
JOB HUNTER BELGIUM
HYGIENE DE LA BASE - OUTIL V1.0

    python -m diagnostics.hygiene_base_v1               (constat seul)
    python -m diagnostics.hygiene_base_v1 --appliquer

Deux anomalies constatees le 16 septembre 2026, apres le premier run
d'absorption complete :

1. Sept runs de collecte restes en statut RUNNING depuis le 8 septembre :
   des runs interrompus (Ctrl+C, seconde instance) et le rattrapage des
   descriptions, qui ne cloturait pas le sien. Un run "en cours" qui ne
   l'est pas fausse l'etat affiche par l'interface. Ils passent INTERRUPTED,
   avec la date de cloture.

2. 901 offres Jobat marquees actives alors qu'aucune n'a ete revue depuis le
   6 septembre : Jobat bloque la lecture directe (HTTP 403) et ne passe plus
   par la collecte. Le contenu de Jobat arrive desormais par Forem et
   Actiris (republication partenaire). Elles passent inactives — texte
   conserve, comme toute offre retiree : elles restent en base pour les
   statistiques.

Aucune offre n'est supprimee. Aucune candidature suivie n'est touchee.
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path


HYGIENE_VERSION = "1.0"
DB_PATH = Path(__file__).resolve().parents[1] / "database" / "jobs.db"
JOBAT_INACTIF_APRES_JOURS = 7


def constat(con: sqlite3.Connection) -> dict:
    runs = con.execute(
        "SELECT run_id, started_at, notes FROM collection_runs WHERE status = 'RUNNING' "
        "ORDER BY started_at").fetchall()
    jobat = con.execute(
        "SELECT COUNT(*), MIN(last_seen), MAX(last_seen) FROM raw_jobs "
        "WHERE source = 'JOBAT' AND is_active = 1 "
        "AND COALESCE(last_seen, first_seen, '') < ?",
        ((datetime.now().replace(microsecond=0)).isoformat(),)).fetchone()
    return {"runs": runs, "jobat_n": jobat[0] or 0, "jobat_min": jobat[1], "jobat_max": jobat[2]}


def appliquer(con: sqlite3.Connection) -> dict:
    maintenant = datetime.now().replace(microsecond=0).isoformat()
    n_runs = con.execute(
        "UPDATE collection_runs SET status = 'INTERRUPTED', finished_at = COALESCE(finished_at, ?), "
        "notes = COALESCE(notes, '') || ' | cloture par hygiene_base_v1 le ' || ? "
        "WHERE status = 'RUNNING'", (maintenant, maintenant[:10])).rowcount
    n_jobat = con.execute(
        "UPDATE raw_jobs SET is_active = 0 WHERE source = 'JOBAT' AND is_active = 1").rowcount
    con.commit()
    return {"runs": n_runs, "jobat": n_jobat}


def main() -> int:
    parseur = argparse.ArgumentParser()
    parseur.add_argument("--appliquer", action="store_true")
    args = parseur.parse_args()
    print("=" * 78)
    print(f"HYGIENE DE LA BASE V{HYGIENE_VERSION}")
    print("=" * 78)
    if not DB_PATH.exists():
        print("[FAIL] base introuvable")
        return 1
    con = sqlite3.connect(DB_PATH, timeout=60)
    try:
        c = constat(con)
        print(f"  runs en statut RUNNING          : {len(c['runs'])}")
        for run_id, debut, notes in c["runs"]:
            print(f"     {run_id}  {str(debut)[:16]}  {str(notes or '')[:50]}")
        print(f"  offres Jobat actives, jamais revues : {c['jobat_n']} "
              f"(dernier passage {str(c['jobat_max'])[:10]})")
        if not args.appliquer:
            print()
            print("CONSTAT SEUL — rien n'a ete modifie. Relancer avec --appliquer.")
            return 0
        fait = appliquer(con)
        print()
        print(f"  runs clotures (INTERRUPTED)     : {fait['runs']}")
        print(f"  offres Jobat passees inactives  : {fait['jobat']}  (texte conserve)")
        print("[PASS] hygiene appliquee.")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
