from __future__ import annotations

import re
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "database" / "jobs.db"


def _norm(value) -> str:
    text = "" if value is None else str(value)
    return re.sub(r"[^A-Z0-9]+", "", text.upper())


def _source_aliases(summary: dict) -> set[str]:
    aliases = {
        _norm(summary.get("key")),
        _norm(summary.get("label")),
    }

    key = str(summary.get("key") or "").upper()
    extra = {
        "TALENT_BRUSSELS": {"TALENTBRUSSELS"},
        "TRAVAILLERPOUR": {"TRAVAILLERPOUR", "TRAVAILLERPOURBE"},
        "SMARTRECRUITERS": {"SMARTRECRUITERS"},
        "SCIENCEATWORK": {"SCIENCEATWORK"},
        "JEFFERSON_WELLS": {"JEFFERSONWELLS"},
        "QUALITY_ASSISTANCE": {"QUALITYASSISTANCE"},
        "THERMO_FISHER": {"THERMOFISHER", "THERMOFISHERSCIENTIFIC"},
        "JNJ": {"JNJ", "JOHNSONJOHNSONJANSSEN"},
    }
    aliases.update(extra.get(key, set()))
    return {a for a in aliases if a}


def _completed_runs(con, current_run_id: str, limit: int = 2) -> list[str]:
    rows = con.execute(
        """
        SELECT run_id
        FROM collection_runs
        WHERE status = 'COMPLETED'
          AND (
                run_id = ?
                OR finished_at <= COALESCE(
                    (SELECT finished_at FROM collection_runs WHERE run_id = ?),
                    finished_at
                )
          )
        ORDER BY finished_at DESC, rowid DESC
        LIMIT ?
        """,
        (current_run_id, current_run_id, limit),
    ).fetchall()

    run_ids = [str(row[0]) for row in rows]

    if current_run_id not in run_ids:
        rows = con.execute(
            """
            SELECT run_id
            FROM collection_runs
            WHERE status = 'COMPLETED'
            ORDER BY finished_at DESC, rowid DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        run_ids = [str(row[0]) for row in rows]

    return run_ids


def _counts_for_run(con, run_id: str) -> dict[str, int]:
    rows = con.execute(
        """
        SELECT
            COALESCE(rj.source, 'INCONNUE') AS source,
            COUNT(*) AS n
        FROM raw_job_run_items AS rri
        JOIN raw_jobs AS rj
          ON rj.id = rri.raw_job_id
        WHERE rri.run_id = ?
        GROUP BY COALESCE(rj.source, 'INCONNUE')
        """,
        (run_id,),
    ).fetchall()

    return {_norm(source): int(count or 0) for source, count in rows}


def _count_for_summary(grouped: dict[str, int], summary: dict) -> int:
    aliases = _source_aliases(summary)
    total = 0
    for source_key, count in grouped.items():
        if source_key in aliases:
            total += int(count or 0)
    return total


def build_source_yield_rows(
    source_summaries: list[dict],
    current_counts: dict[str, int],
    previous_counts: dict[str, int] | None = None,
) -> list[dict]:
    previous_counts = previous_counts or {}
    rows = []

    for summary in source_summaries:
        if not summary.get("enabled"):
            continue

        returned = int(summary.get("count") or 0)
        persisted = _count_for_summary(current_counts, summary)
        previous = _count_for_summary(previous_counts, summary)
        error = summary.get("error")

        rows.append(
            {
                "key": summary.get("key"),
                "label": summary.get("label") or summary.get("key"),
                "returned": returned,
                "persisted": persisted,
                "previous_persisted": previous,
                "error": error,
                "zero_two_runs": bool(
                    returned == 0
                    and persisted == 0
                    and previous == 0
                ),
            }
        )

    return rows


def print_source_yield_report(collection: dict, current_run_id: str) -> list[dict]:
    summaries = list(collection.get("source_summaries") or [])

    print()
    print("=" * 94)
    print("RENDEMENT PAR SOURCE - V3.8")
    print("=" * 94)

    if not summaries:
        print("Aucun source_summary disponible.")
        return []

    if not DB_PATH.exists():
        print("Base introuvable :", DB_PATH)
        return []

    uri = DB_PATH.resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)

    try:
        run_ids = _completed_runs(con, current_run_id, limit=2)

        current_counts = _counts_for_run(con, current_run_id)

        previous_run_id = None
        for run_id in run_ids:
            if run_id != current_run_id:
                previous_run_id = run_id
                break

        previous_counts = (
            _counts_for_run(con, previous_run_id)
            if previous_run_id
            else {}
        )

        rows = build_source_yield_rows(
            summaries,
            current_counts,
            previous_counts,
        )

        print(
            f"{'SOURCE':<28} {'RETURNED':>8} {'PERSISTED':>10} "
            f"{'PREV':>6} {'ERROR':>7} {'ZEROx2':>7}"
        )
        print("-" * 94)

        alerts = []

        for row in rows:
            error_flag = "OUI" if row["error"] else "-"
            zero_flag = "ALERTE" if row["zero_two_runs"] else "-"
            print(
                f"{str(row['label']):<28} "
                f"{row['returned']:>8} "
                f"{row['persisted']:>10} "
                f"{row['previous_persisted']:>6} "
                f"{error_flag:>7} "
                f"{zero_flag:>7}"
            )

            if row["zero_two_runs"]:
                alerts.append(row)

        print()
        print("Run courant   :", current_run_id)
        print("Run précédent :", previous_run_id or "indisponible")

        if alerts:
            print()
            print("ALERTES - SOURCE ACTIVE À ZÉRO SUR 2 RUNS")
            print("-" * 94)
            for row in alerts:
                message = f"- {row['label']}"
                if row["error"]:
                    message += f" | erreur courante: {row['error']}"
                print(message)
        else:
            print()
            print("Aucune alerte ZERO x2.")

        print()
        print(
            "Note: 'RETURNED' = offres sorties du collecteur. "
            "'PERSISTED' = observations réellement écrites dans raw_job_run_items."
        )
        print(
            "Le compteur 'seen' interne aux sites n'est pas inventé ici : "
            "il sera ajouté seulement aux connecteurs qui l'exposent réellement."
        )


        print()
        print("MÉTRIQUES DÉTAILLÉES PAR SOURCE")
        print("-" * 112)
        print(
            f"{'SOURCE':<28} {'SEEN':>7} {'CAND':>7} {'KEPT':>7} "
            f"{'NON-TGT':>8} {'LANG':>7} {'GEO':>7} {'CLOSED':>7} {'DERR':>6}"
        )
        print("-" * 112)

        for summary in summaries:
            if not summary.get("enabled"):
                continue

            metrics = summary.get("metrics")
            if not isinstance(metrics, dict):
                print(f"{str(summary.get('label') or summary.get('key')):<28} {'n/a':>7}")
                continue

            def fmt(value):
                return "n/a" if value is None else str(value)

            print(
                f"{str(summary.get('label') or summary.get('key')):<28} "
                f"{fmt(metrics.get('seen')):>7} "
                f"{fmt(metrics.get('candidates')):>7} "
                f"{fmt(metrics.get('kept')):>7} "
                f"{fmt(metrics.get('non_target')):>8} "
                f"{fmt(metrics.get('rejected_language')):>7} "
                f"{fmt(metrics.get('rejected_geo')):>7} "
                f"{fmt(metrics.get('closed')):>7} "
                f"{fmt(metrics.get('detail_errors')):>6}"
            )

        return rows

    finally:
        con.close()
