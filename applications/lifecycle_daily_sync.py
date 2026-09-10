"""
Job Hunter Belgium — Lifecycle Daily Sync Wrapper V1.0

Called by Daily Run V1.2.0 with exact artifact paths.

No discovery of "latest" Final Pool or Delta.
No network.
APPLIED remains USER-only through Lifecycle Tracker safeguards.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from applications import lifecycle_sync as ls
from applications import lifecycle_tracker as lt


LIFECYCLE_DAILY_SYNC_VERSION = "1.0"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "exports" / "logs"
DB_PATH = PROJECT_ROOT / "database" / "jobs.db"


def same_path(a, b):
    try:
        return Path(a).resolve() == Path(b).resolve()
    except Exception:
        return str(a) == str(b)


def stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def load_json(path):
    return json.loads(
        Path(path).read_text(
            encoding="utf-8-sig",
            errors="strict",
        )
    )


def validate_input_lineage(final_pool_path, delta_path):
    final_payload = load_json(final_pool_path)
    delta_payload = load_json(delta_path)

    final_items = ls.get_items(final_payload)
    delta_items = ls.get_items(delta_payload)

    inputs = delta_payload.get("inputs") if isinstance(delta_payload, dict) else {}
    inputs = inputs or {}
    delta_current_pool = inputs.get("current_pool")

    if delta_current_pool and not same_path(
        delta_current_pool,
        final_pool_path,
    ):
        raise RuntimeError(
            "Lifecycle Daily Sync: Delta current_pool ne correspond "
            "pas au Final Pool exact fourni.\n"
            f"Final Pool : {final_pool_path}\n"
            f"Delta input: {delta_current_pool}"
        )

    current_delta_records = [
        row
        for row in delta_items
        if str(row.get("delta_status") or "").upper() != "DISAPPEARED"
    ]

    if len(current_delta_records) != len(final_items):
        raise RuntimeError(
            "Lifecycle Daily Sync: Delta/current count incompatible: "
            f"{len(current_delta_records)} != Final Pool {len(final_items)}"
        )

    return final_items, delta_items


def post_sync_snapshot(conn):
    counts = {}

    for table in (
        "application_entities",
        "application_events",
        "source_identity_aliases",
    ):
        counts[table] = conn.execute(
            f'SELECT COUNT(*) FROM "{table}"'
        ).fetchone()[0]

    applied_total = conn.execute(
        """
        SELECT COUNT(*)
        FROM application_events
        WHERE event_type='STATUS' AND status='APPLIED'
        """
    ).fetchone()[0]

    non_user_applied = conn.execute(
        """
        SELECT COUNT(*)
        FROM application_events
        WHERE
            event_type='STATUS'
            AND status='APPLIED'
            AND actor_type <> 'USER'
        """
    ).fetchone()[0]

    current_status_counts = dict(
        conn.execute(
            """
            SELECT current_status, COUNT(*)
            FROM application_current_state
            GROUP BY current_status
            ORDER BY current_status
            """
        ).fetchall()
    )

    return {
        **counts,
        "applied_total": applied_total,
        "non_user_applied": non_user_applied,
        "current_status_counts": current_status_counts,
    }


def run(final_pool_path, delta_path, db_path=DB_PATH):
    final_pool_path = Path(final_pool_path).resolve()
    delta_path = Path(delta_path).resolve()
    db_path = Path(db_path).resolve()

    if not final_pool_path.exists():
        raise RuntimeError(f"Final Pool introuvable: {final_pool_path}")
    if not delta_path.exists():
        raise RuntimeError(f"Delta introuvable: {delta_path}")
    if not db_path.exists():
        raise RuntimeError(f"DB introuvable: {db_path}")

    final_items, delta_items = validate_input_lineage(
        final_pool_path,
        delta_path,
    )

    conn = lt.connect_database(db_path)
    try:
        if not lt.lifecycle_tables_present(conn):
            raise RuntimeError(
                "Lifecycle schema absent. Step 8B doit être installé."
            )

        result = ls.sync_lifecycle(
            conn,
            final_items=final_items,
            delta_items=delta_items,
            sync_token=f"DELTA_ARTIFACT:{delta_path.name}",
        )

        post_sync = post_sync_snapshot(conn)
    finally:
        conn.close()

    if post_sync["non_user_applied"] != 0:
        raise RuntimeError(
            "Lifecycle invariant cassé : APPLIED non-USER détecté."
        )

    payload = {
        "lifecycle_daily_sync_version": LIFECYCLE_DAILY_SYNC_VERSION,
        "lifecycle_sync_version": ls.LIFECYCLE_SYNC_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "inputs": {
            "final_pool": str(final_pool_path),
            "delta": str(delta_path),
            "database": str(db_path),
        },
        "result": result,
        "post_sync": post_sync,
    }

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    run_stamp = stamp()

    json_path = LOG_DIR / f"lifecycle_daily_sync_v1_{run_stamp}.json"
    txt_path = LOG_DIR / f"lifecycle_daily_sync_v1_{run_stamp}.txt"

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    txt_path.write_text(
        "\n".join([
            "LIFECYCLE DAILY SYNC V1.0",
            "=" * 100,
            f"Final Pool      : {final_pool_path}",
            f"Delta           : {delta_path}",
            f"Current items   : {result['current_items']}",
            f"Delta items     : {result['delta_items']}",
            f"Counts          : {result['counts']}",
            f"Status events   : {result['status_events_created']}",
            f"APPLIED policy  : {result['applied_policy']}",
            f"DISAPPEARED     : {result['disappeared_policy']}",
            f"APPLIED total   : {post_sync['applied_total']}",
            f"Non-USER APPLIED: {post_sync['non_user_applied']}",
        ]),
        encoding="utf-8",
    )

    print("LIFECYCLE DAILY SYNC V1.0")
    print("Final Pool      :", final_pool_path)
    print("Delta           :", delta_path)
    print("Current items   :", result["current_items"])
    print("Status events   :", result["status_events_created"])
    print("Non-USER APPLIED:", post_sync["non_user_applied"])
    print("JSON            :", json_path)
    print("TXT             :", txt_path)

    return payload, json_path, txt_path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Lifecycle Daily Sync V1.0"
    )
    parser.add_argument(
        "--final-pool",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--delta",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DB_PATH,
    )
    return parser.parse_args()


def main():
    args = parse_args()
    run(
        args.final_pool,
        args.delta,
        db_path=args.db,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
