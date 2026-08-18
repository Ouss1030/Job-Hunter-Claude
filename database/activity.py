"""
JOB HUNTER BELGIUM
ACTIVE JOBS MIGRATION - VERSION 1.0

Objectif
--------
Corriger la gestion de raw_jobs.is_active sans supprimer l'historique.

Problème observé :
- le run courant collecte N offres ;
- d'anciennes offres disparues restent présentes dans raw_jobs ;
- elles restaient aussi is_active = 1 ;
- canonical.py les considérait donc encore comme actives.

Solution
--------
1. Installer un trigger SQLite persistant.
2. À chaque collection_run terminé avec succès :
   - les offres vues pendant ce run restent actives ;
   - les anciennes offres des mêmes collection_channel,
     mais absentes du run, passent à is_active = 0.
3. Une offre qui réapparaît lors d'un futur run repasse active
   automatiquement grâce à l'UPSERT existant.
4. Aucune ligne raw_jobs n'est supprimée.

Sécurité
--------
On ne désactive que les collection_channel réellement observés dans le run.
Donc si une source échoue complètement et ne retourne aucune offre,
ses anciennes lignes ne sont pas désactivées par erreur.

Lancement
---------
python -m database.activity

Log automatique
---------------
exports/logs/activity_v1_YYYYMMDD_HHMMSS.txt
"""

import sys
from datetime import datetime
from pathlib import Path

from database.db import (
    DB_PATH,
    get_connection,
    init_db,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "exports" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

TRIGGER_NAME = "trg_collection_run_complete_deactivate_missing"


# ============================================================
# LOGGER
# ============================================================

class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            try:
                stream.write(data)
                stream.flush()
            except Exception:
                pass

    def flush(self):
        for stream in self.streams:
            try:
                stream.flush()
            except Exception:
                pass


def start_logging():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = LOG_DIR / f"activity_v1_{timestamp}.txt"
    file = path.open("w", encoding="utf-8")

    stdout = sys.stdout
    stderr = sys.stderr

    sys.stdout = Tee(stdout, file)
    sys.stderr = Tee(stderr, file)

    return {
        "path": path,
        "file": file,
        "stdout": stdout,
        "stderr": stderr,
    }


def stop_logging(logger):
    sys.stdout = logger["stdout"]
    sys.stderr = logger["stderr"]

    try:
        logger["file"].close()
    except Exception:
        pass


# ============================================================
# COUNTS
# ============================================================

def get_counts(connection):
    row = connection.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) AS active,
            SUM(CASE WHEN is_active = 0 THEN 1 ELSE 0 END) AS inactive
        FROM raw_jobs
        """
    ).fetchone()

    return {
        "total": int(row["total"] or 0),
        "active": int(row["active"] or 0),
        "inactive": int(row["inactive"] or 0),
    }


def get_active_source_counts(connection):
    rows = connection.execute(
        """
        SELECT
            source,
            COUNT(*) AS count
        FROM raw_jobs
        WHERE is_active = 1
        GROUP BY source
        ORDER BY count DESC, source ASC
        """
    ).fetchall()

    return [
        {
            "source": row["source"],
            "count": int(row["count"]),
        }
        for row in rows
    ]


# ============================================================
# LATEST SAFE RUN
# ============================================================

def get_latest_safe_run(connection):
    return connection.execute(
        """
        SELECT *
        FROM collection_runs
        WHERE status = 'COMPLETED'
          AND COALESCE(error_count, 0) = 0
        ORDER BY started_at DESC
        LIMIT 1
        """
    ).fetchone()


def get_observed_channels(connection, run_id):
    rows = connection.execute(
        """
        SELECT DISTINCT rj.collection_channel
        FROM raw_job_run_items AS rri
        JOIN raw_jobs AS rj
          ON rj.id = rri.raw_job_id
        WHERE rri.run_id = ?
        ORDER BY rj.collection_channel
        """,
        (run_id,),
    ).fetchall()

    return [
        row["collection_channel"]
        for row in rows
        if row["collection_channel"]
    ]


# ============================================================
# TRIGGER
# ============================================================

def install_trigger(connection):
    """
    Le trigger s'exécute lorsque finish_collection_run()
    passe un run à COMPLETED sans erreur.

    Il ne touche qu'aux canaux réellement observés dans ce run.
    """

    connection.execute(
        f"""
        DROP TRIGGER IF EXISTS {TRIGGER_NAME}
        """
    )

    connection.execute(
        f"""
        CREATE TRIGGER {TRIGGER_NAME}
        AFTER UPDATE OF status ON collection_runs

        WHEN
            NEW.status = 'COMPLETED'
            AND COALESCE(NEW.error_count, 0) = 0

        BEGIN

            UPDATE raw_jobs

            SET is_active = 0

            WHERE
                is_active = 1

                AND (
                    last_run_id IS NULL
                    OR last_run_id <> NEW.run_id
                )

                AND collection_channel IN (

                    SELECT DISTINCT rj_current.collection_channel

                    FROM raw_job_run_items AS rri_current

                    JOIN raw_jobs AS rj_current
                      ON rj_current.id = rri_current.raw_job_id

                    WHERE rri_current.run_id = NEW.run_id
                );

        END;
        """
    )


def trigger_exists(connection):
    row = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'trigger'
          AND name = ?
        """,
        (TRIGGER_NAME,),
    ).fetchone()

    return row is not None


# ============================================================
# REPAIR CURRENT DATABASE
# ============================================================

def repair_from_latest_safe_run(connection):
    """
    Répare immédiatement la base actuelle.
    Le trigger, lui, gérera les futurs runs.
    """

    run = get_latest_safe_run(connection)

    if run is None:
        return {
            "success": False,
            "run_id": None,
            "channels": [],
            "deactivated": 0,
            "reason": "Aucun run COMPLETED sans erreur trouvé.",
        }

    run_id = run["run_id"]
    channels = get_observed_channels(connection, run_id)

    if not channels:
        return {
            "success": False,
            "run_id": run_id,
            "channels": [],
            "deactivated": 0,
            "reason": "Aucun collection_channel observé dans ce run.",
        }

    placeholders = ",".join("?" for _ in channels)

    cursor = connection.execute(
        f"""
        UPDATE raw_jobs

        SET is_active = 0

        WHERE
            is_active = 1

            AND (
                last_run_id IS NULL
                OR last_run_id <> ?
            )

            AND collection_channel IN ({placeholders})
        """,
        (
            run_id,
            *channels,
        ),
    )

    deactivated = (
        cursor.rowcount
        if cursor.rowcount is not None and cursor.rowcount >= 0
        else 0
    )

    return {
        "success": True,
        "run_id": run_id,
        "channels": channels,
        "deactivated": int(deactivated),
        "reason": None,
    }


# ============================================================
# MAIN LOGIC
# ============================================================

def migrate_and_repair():
    init_db()
    connection = get_connection()

    try:
        before = get_counts(connection)

        install_trigger(connection)

        repair = repair_from_latest_safe_run(connection)

        connection.commit()

        after = get_counts(connection)

        return {
            "before": before,
            "after": after,
            "repair": repair,
            "trigger_installed": trigger_exists(connection),
            "active_sources": get_active_source_counts(connection),
        }

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def print_result(result):
    print()
    print("=" * 80)
    print("       JOB HUNTER - ACTIVE JOBS MIGRATION V1")
    print("=" * 80)

    print()
    print("SQLite :", DB_PATH)

    print()
    print("TRIGGER")
    print("-------")
    print(
        "Installé :",
        "OUI" if result["trigger_installed"] else "NON",
    )
    print("Nom      :", TRIGGER_NAME)

    repair = result["repair"]

    print()
    print("RÉPARATION DU DERNIER RUN")
    print("-------------------------")
    print(
        "Succès      :",
        "OUI" if repair["success"] else "NON",
    )
    print("Run utilisé :", repair["run_id"])
    print(
        "Canaux      :",
        ", ".join(repair["channels"])
        if repair["channels"]
        else "-",
    )
    print("Désactivées :", repair["deactivated"])

    if repair["reason"]:
        print("Motif       :", repair["reason"])

    print()
    print("COMPTAGE RAW")
    print("------------")
    print(
        f"Avant : total={result['before']['total']} | "
        f"actifs={result['before']['active']} | "
        f"inactifs={result['before']['inactive']}"
    )
    print(
        f"Après : total={result['after']['total']} | "
        f"actifs={result['after']['active']} | "
        f"inactifs={result['after']['inactive']}"
    )

    print()
    print("RAW ACTIFS PAR SOURCE")
    print("---------------------")

    for item in result["active_sources"]:
        print(
            f"{item['source']:<20} "
            f"{item['count']}"
        )

    print()
    print("=" * 80)
    print("VALIDATION")
    print("=" * 80)
    print()

    valid = (
        result["trigger_installed"]
        and
        repair["success"]
        and
        result["after"]["total"] == result["before"]["total"]
        and
        result["after"]["active"] <= result["before"]["active"]
    )

    if valid:
        print("✅ Aucune ligne RAW supprimée.")
        print("✅ Gestion is_active réparée.")
        print("✅ Le trigger protégera aussi les futurs runs.")
        print()
        print("Contrôle suivant :")
        print("python -m database.canonical")
    else:
        print("⚠️ Migration à vérifier avant de poursuivre.")

    return valid


def main():
    logger = start_logging()

    try:
        print()
        print("TXT automatique :")
        print(logger["path"])

        result = migrate_and_repair()
        print_result(result)

        print()
        print("Fichier résultat :")
        print(logger["path"])

    finally:
        path = logger["path"]
        stop_logging(logger)

        print()
        print("TXT généré automatiquement :")
        print(path)


if __name__ == "__main__":
    main()