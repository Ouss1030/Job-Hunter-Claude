"""
Job Hunter Belgium — Lifecycle Tracker Step 8G
FINAL OFFLINE INTEGRATION VALIDATION V1.0

Validates the installed Lifecycle Tracker + Daily Run V1.2.0 as a whole.

Important:
- DOES NOT run main.py
- DOES NOT run the Daily Run pipeline
- DOES NOT use the network
- production SQLite DB is opened read-only for verification
- mutation tests use temporary/in-memory state only
- unlike old bootstrap audits, this audit DOES NOT require total APPLIED=0.
  Durable invariant: every APPLIED event must have actor_type=USER.
"""

from __future__ import annotations

import inspect
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import daily_run
from applications import lifecycle_daily_sync as lds
from applications import lifecycle_sync as ls
from applications import lifecycle_tracker as lt


FINAL_VALIDATION_VERSION = "1.0"

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "database" / "jobs.db"
LOG_DIR = ROOT / "exports" / "logs"


def check(label, condition, detail=""):
    ok = bool(condition)
    print(
        f"[{'PASS' if ok else 'FAIL'}] {label}"
        + (f" | {detail}" if detail else "")
    )
    return ok


def child_env():
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def run_module(module, *args):
    proc = subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=ROOT,
        env=child_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return {
        "module": module,
        "args": list(args),
        "returncode": proc.returncode,
        "output": proc.stdout,
    }


def production_snapshot():
    uri = DB_PATH.resolve().as_uri() + "?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row

    try:
        objects = {
            (row["type"], row["name"])
            for row in conn.execute(
                """
                SELECT type, name
                FROM sqlite_master
                WHERE name NOT LIKE 'sqlite_%'
                """
            ).fetchall()
        }

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

        invalid_nonstatus_status = conn.execute(
            """
            SELECT COUNT(*)
            FROM application_events
            WHERE event_type <> 'STATUS' AND status IS NOT NULL
            """
        ).fetchone()[0]

        status_without_value = conn.execute(
            """
            SELECT COUNT(*)
            FROM application_events
            WHERE event_type='STATUS' AND status IS NULL
            """
        ).fetchone()[0]

        current_rows = conn.execute(
            """
            SELECT
                s.entity_id,
                s.current_status,
                s.status_event_id,
                (
                    SELECT ev.id
                    FROM application_events AS ev
                    WHERE
                        ev.entity_id = s.entity_id
                        AND ev.event_type='STATUS'
                    ORDER BY ev.event_at DESC, ev.id DESC
                    LIMIT 1
                ) AS expected_status_event_id
            FROM application_current_state AS s
            """
        ).fetchall()

        current_view_mismatches = [
            dict(row)
            for row in current_rows
            if row["status_event_id"] != row["expected_status_event_id"]
        ]

        alias_duplicates = conn.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT identity_type, identity_value, COUNT(*) AS n
                FROM source_identity_aliases
                GROUP BY identity_type, identity_value
                HAVING COUNT(*) > 1
            )
            """
        ).fetchone()[0]

        repost_rows = conn.execute(
            """
            SELECT
                entity_id,
                stable_item_key AS current_key,
                related_identity_value AS old_key
            FROM application_events
            WHERE event_type='REPOSTED'
            """
        ).fetchall()

        repost_lineage_errors = []
        for row in repost_rows:
            current_alias = conn.execute(
                """
                SELECT entity_id
                FROM source_identity_aliases
                WHERE
                    identity_type='STABLE_ITEM_KEY'
                    AND identity_value=?
                """,
                (row["current_key"],),
            ).fetchone()

            old_alias = conn.execute(
                """
                SELECT entity_id
                FROM source_identity_aliases
                WHERE
                    identity_type='STABLE_ITEM_KEY'
                    AND identity_value=?
                """,
                (row["old_key"],),
            ).fetchone()

            if (
                current_alias is None
                or old_alias is None
                or int(current_alias["entity_id"]) != int(row["entity_id"])
                or int(old_alias["entity_id"]) != int(row["entity_id"])
            ):
                repost_lineage_errors.append(dict(row))

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
            "objects": objects,
            "counts": counts,
            "applied_total": applied_total,
            "non_user_applied": non_user_applied,
            "invalid_nonstatus_status": invalid_nonstatus_status,
            "status_without_value": status_without_value,
            "current_view_mismatches": current_view_mismatches,
            "alias_duplicates": alias_duplicates,
            "reposted_count": len(repost_rows),
            "repost_lineage_errors": repost_lineage_errors,
            "current_status_counts": current_status_counts,
        }
    finally:
        conn.close()


def empty_step(status="PENDING"):
    return {
        "status": status,
        "started_at": None,
        "finished_at": None,
        "command": None,
        "log": None,
        "artifacts": {},
        "validation": {},
        "error": None,
    }


def test_legacy_resume():
    legacy = {
        "daily_run_version": "1.1.1",
        "run_id": "FINAL_VALIDATION_RESUME",
        "status": "FAILED",
        "finished_at": None,
        "last_error": "synthetic",
        "resume_count": 7,
        "settings": {
            "preparation_limit": 80,
            "handoff_chunk_size": 10,
            "handoff_enabled": True,
            "stop_after": None,
        },
        "steps": {
            step: empty_step(
                "DONE"
                if step in ("main", "preparation", "refresh")
                else "PENDING"
            )
            for step in (
                "main",
                "preparation",
                "refresh",
                "recheck",
                "final_pool",
                "delta",
                "handoff",
            )
        },
    }

    original_save = daily_run.save_manifest
    daily_run.save_manifest = lambda manifest: None
    try:
        out = daily_run.normalize_manifest_for_resume(legacy)
    finally:
        daily_run.save_manifest = original_save

    return {
        "version": out["daily_run_version"],
        "main": out["steps"]["main"]["status"],
        "preparation": out["steps"]["preparation"]["status"],
        "refresh": out["steps"]["refresh"]["status"],
        "lifecycle": out["steps"]["lifecycle"]["status"],
        "resume_count": out["resume_count"],
    }


def test_no_handoff_pipeline():
    manifest = {
        "run_id": "FINAL_VALIDATION_NO_HANDOFF",
        "status": "RUNNING",
        "finished_at": None,
        "settings": {
            "handoff_enabled": False,
            "stop_after": None,
        },
        "steps": {
            step: empty_step()
            for step in daily_run.STEP_ORDER
        },
    }

    calls = []

    original_funcs = daily_run.STEP_FUNCTIONS
    original_save = daily_run.save_manifest

    fake_funcs = {}
    for step in daily_run.STEP_ORDER:
        def make_fake(name):
            def fake(m):
                calls.append(name)
                m["steps"][name]["status"] = "DONE"
            return fake
        fake_funcs[step] = make_fake(step)

    daily_run.STEP_FUNCTIONS = fake_funcs
    daily_run.save_manifest = lambda manifest: None

    try:
        result = daily_run.run_pipeline(manifest)
    finally:
        daily_run.STEP_FUNCTIONS = original_funcs
        daily_run.save_manifest = original_save

    return {
        "calls": calls,
        "handoff_status": result["steps"]["handoff"]["status"],
        "status": result["status"],
    }


def test_manual_applied_survives_sync():
    with tempfile.TemporaryDirectory(
        prefix="jobhunter_lifecycle_step8g_"
    ) as tmp:
        db = Path(tmp) / "test.db"

        conn = lt.connect_database(db)
        try:
            lt.ensure_schema(conn)

            entity_id = lt.create_entity(
                conn,
                seed="ITEM_OLD",
                application_group_id="GROUP_X",
                title="Technicien QC",
                company="Example Pharma",
                location="Bruxelles",
                track="LAB_QC",
            )
            lt.attach_alias(
                conn,
                entity_id=entity_id,
                identity_type="STABLE_ITEM_KEY",
                identity_value="ITEM_OLD",
                source="FOREM",
            )
            lt.attach_alias(
                conn,
                entity_id=entity_id,
                identity_type="APPLICATION_GROUP_ID",
                identity_value="GROUP_X",
                source="FOREM",
            )
            lt.record_user_status(
                conn,
                entity_id=entity_id,
                status="APPLIED",
                actor="USER",
                event_at="2026-08-19T01:00:00+00:00",
            )
            conn.commit()

            final_items = [
                {
                    "stable_item_key": "ITEM_NEW",
                    "application_group_id": "GROUP_X",
                    "source": "FOREM",
                    "origin_source": "FOREM",
                    "url": "https://example.test/new",
                    "title": "Technicien QC",
                    "company": "Example Pharma",
                    "location": "Bruxelles",
                    "track": "LAB_QC",
                    "recommended_action_v12": "DO_NOT_APPLY",
                }
            ]

            delta_items = [
                {
                    "identity_key": "ITEM_NEW",
                    "identity_method": "STABLE_ITEM_KEY",
                    "delta_status": "REPOSTED",
                    "source": "FOREM",
                    "reposted_from_identity_key": "ITEM_OLD",
                    "repost_confidence": "EXACT_CONTENT_MATCH",
                }
            ]

            first = ls.sync_lifecycle(
                conn,
                final_items=final_items,
                delta_items=delta_items,
                sync_token="DELTA_ARTIFACT:synthetic.json",
                event_at="2026-08-19T02:00:00+00:00",
            )

            counts_before_second = {
                "entities": conn.execute(
                    "SELECT COUNT(*) FROM application_entities"
                ).fetchone()[0],
                "events": conn.execute(
                    "SELECT COUNT(*) FROM application_events"
                ).fetchone()[0],
                "aliases": conn.execute(
                    "SELECT COUNT(*) FROM source_identity_aliases"
                ).fetchone()[0],
            }

            second = ls.sync_lifecycle(
                conn,
                final_items=final_items,
                delta_items=delta_items,
                sync_token="DELTA_ARTIFACT:synthetic.json",
                event_at="2026-08-19T02:00:00+00:00",
            )

            counts_after_second = {
                "entities": conn.execute(
                    "SELECT COUNT(*) FROM application_entities"
                ).fetchone()[0],
                "events": conn.execute(
                    "SELECT COUNT(*) FROM application_events"
                ).fetchone()[0],
                "aliases": conn.execute(
                    "SELECT COUNT(*) FROM source_identity_aliases"
                ).fetchone()[0],
            }

            state = lt.current_state(conn, entity_id)

            old_entity = lt.resolve_entity_by_alias(
                conn,
                identity_type="STABLE_ITEM_KEY",
                identity_value="ITEM_OLD",
            )
            new_entity = lt.resolve_entity_by_alias(
                conn,
                identity_type="STABLE_ITEM_KEY",
                identity_value="ITEM_NEW",
            )

            non_user_applied = conn.execute(
                """
                SELECT COUNT(*)
                FROM application_events
                WHERE
                    status='APPLIED'
                    AND actor_type <> 'USER'
                """
            ).fetchone()[0]

            return {
                "state": state,
                "same_entity": (
                    old_entity is not None
                    and new_entity is not None
                    and old_entity["id"] == new_entity["id"] == entity_id
                ),
                "non_user_applied": non_user_applied,
                "counts_before_second": counts_before_second,
                "counts_after_second": counts_after_second,
                "first": first,
                "second": second,
            }

        finally:
            conn.close()


def main():
    print("=" * 100)
    print("LIFECYCLE TRACKER STEP 8G - FINAL OFFLINE INTEGRATION VALIDATION")
    print("=" * 100)
    print("No Main. No Daily Run pipeline. No network.")
    print()

    tests = []
    subprocess_reports = []

    tests.append(check(
        "Final validation version 1.0",
        FINAL_VALIDATION_VERSION == "1.0",
    ))

    # 1) Existing frozen offline diagnostic suite.
    suite = run_module("diagnostics.run_all")
    subprocess_reports.append(suite)
    tests.append(check(
        "Frozen offline diagnostics suite passes",
        suite["returncode"] == 0,
        f"code={suite['returncode']}",
    ))

    # 2) Current Daily Run integration structure.
    tests.append(check(
        "Daily Run is V1.2.0",
        daily_run.DAILY_RUN_VERSION == "1.2.0",
        daily_run.DAILY_RUN_VERSION,
    ))

    expected_order = [
        "main",
        "preparation",
        "refresh",
        "recheck",
        "final_pool",
        "delta",
        "lifecycle",
        "handoff",
    ]
    tests.append(check(
        "Daily Run step order is exact",
        daily_run.STEP_ORDER == expected_order,
        str(daily_run.STEP_ORDER),
    ))

    preflight = daily_run.run_preflight()
    tests.append(check(
        "Daily Run preflight passes",
        preflight["ok"],
        str(preflight["errors"]),
    ))

    handoff_src = inspect.getsource(daily_run.step_handoff)
    tests.append(check(
        "Handoff requires lifecycle DONE",
        'require_completed(manifest, "lifecycle")' in handoff_src,
    ))

    tests.append(check(
        "Lifecycle components are V1.0",
        (
            lt.LIFECYCLE_VERSION == "1.0"
            and ls.LIFECYCLE_SYNC_VERSION == "1.0"
            and lds.LIFECYCLE_DAILY_SYNC_VERSION == "1.0"
        ),
        str({
            "tracker": lt.LIFECYCLE_VERSION,
            "sync": ls.LIFECYCLE_SYNC_VERSION,
            "wrapper": lds.LIFECYCLE_DAILY_SYNC_VERSION,
        }),
    ))

    # 3) Production DB durable invariants.
    snap = production_snapshot()

    required_objects = {
        ("table", "application_entities"),
        ("table", "application_events"),
        ("table", "source_identity_aliases"),
        ("view", "application_current_state"),
        ("trigger", "trg_application_events_no_update"),
        ("trigger", "trg_application_events_no_delete"),
        ("trigger", "trg_application_events_applied_user_only"),
        ("trigger", "trg_application_events_system_manual_status_block"),
    }

    tests.append(check(
        "Lifecycle schema + safety objects present",
        required_objects <= snap["objects"],
    ))

    tests.append(check(
        "Every APPLIED in production is USER-originated",
        snap["non_user_applied"] == 0,
        (
            f"APPLIED total={snap['applied_total']} "
            f"non-USER={snap['non_user_applied']}"
        ),
    ))

    tests.append(check(
        "Event type/status structural invariant holds",
        (
            snap["invalid_nonstatus_status"] == 0
            and snap["status_without_value"] == 0
        ),
        str({
            "nonstatus_with_status": snap["invalid_nonstatus_status"],
            "status_without_value": snap["status_without_value"],
        }),
    ))

    tests.append(check(
        "Current-state view matches latest STATUS event for every entity",
        not snap["current_view_mismatches"],
        str(snap["current_view_mismatches"][:3]),
    ))

    tests.append(check(
        "Identity aliases remain unique",
        snap["alias_duplicates"] == 0,
        str(snap["alias_duplicates"]),
    ))

    tests.append(check(
        "All REPOSTED events preserve old/new lineage on one entity",
        not snap["repost_lineage_errors"],
        (
            f"reposted={snap['reposted_count']} "
            f"errors={snap['repost_lineage_errors']}"
        ),
    ))

    # 4) Resume + --no-handoff orchestration without real pipeline calls.
    resume = test_legacy_resume()
    tests.append(check(
        "Legacy V1.1.1 resume preserves DONE steps and adds lifecycle",
        (
            resume["version"] == "1.2.0"
            and resume["main"] == "DONE"
            and resume["preparation"] == "DONE"
            and resume["refresh"] == "DONE"
            and resume["lifecycle"] == "PENDING"
            and resume["resume_count"] == 8
        ),
        str(resume),
    ))

    no_handoff = test_no_handoff_pipeline()
    tests.append(check(
        "--no-handoff runs lifecycle and skips only handoff",
        (
            "lifecycle" in no_handoff["calls"]
            and "handoff" not in no_handoff["calls"]
            and no_handoff["handoff_status"] == "SKIPPED"
            and no_handoff["status"] == "COMPLETED"
        ),
        str(no_handoff),
    ))

    # 5) Manual status preservation / repost / idempotence on temp DB.
    synthetic = test_manual_applied_survives_sync()

    tests.append(check(
        "Manual APPLIED survives automatic downgrade/repost sync",
        (
            synthetic["state"]["current_status"] == "APPLIED"
            and synthetic["state"]["status_actor_type"] == "USER"
        ),
        str({
            "status": synthetic["state"]["current_status"],
            "actor": synthetic["state"]["status_actor_type"],
        }),
    ))

    tests.append(check(
        "Synthetic repost old/new identities resolve to same entity",
        synthetic["same_entity"],
    ))

    tests.append(check(
        "Synthetic sync creates zero non-USER APPLIED",
        synthetic["non_user_applied"] == 0,
        str(synthetic["non_user_applied"]),
    ))

    tests.append(check(
        "Same Delta artifact is idempotent",
        (
            synthetic["counts_before_second"]
            == synthetic["counts_after_second"]
            and synthetic["second"]["counts"].get(
                "seen_events_created", 0
            ) == 0
            and synthetic["second"]["counts"].get(
                "reposted_events_created", 0
            ) == 0
            and synthetic["second"]["status_events_created"] == {}
        ),
        (
            f"{synthetic['counts_before_second']} -> "
            f"{synthetic['counts_after_second']}"
        ),
    ))

    passed = sum(tests)
    total = len(tests)
    status = (
        "LIFECYCLE TRACKER STEP 8G VALIDE."
        if all(tests)
        else "LIFECYCLE TRACKER STEP 8G NON VALIDE."
    )

    print()
    print("=" * 100)
    print(f"Tests : {passed}/{total}")
    print(status)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = LOG_DIR / f"lifecycle_step8g_final_validation_{stamp}.json"
    txt_path = LOG_DIR / f"lifecycle_step8g_final_validation_{stamp}.txt"

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "OFFLINE_FINAL_VALIDATION",
        "checks_passed": passed,
        "checks_total": total,
        "status": status,
        "daily_run_version": daily_run.DAILY_RUN_VERSION,
        "step_order": daily_run.STEP_ORDER,
        "preflight_ok": preflight["ok"],
        "production": {
            "counts": snap["counts"],
            "applied_total": snap["applied_total"],
            "non_user_applied": snap["non_user_applied"],
            "current_status_counts": snap["current_status_counts"],
            "reposted_count": snap["reposted_count"],
        },
        "rules": {
            "applied_user_only": True,
            "events_append_only": True,
            "current_state_derived_from_events": True,
            "no_auto_downgrade": True,
            "disappeared_no_status_change": True,
            "repost_same_entity": True,
            "same_delta_artifact_idempotent": True,
            "legacy_resume_supported": True,
            "no_handoff_still_runs_lifecycle": True,
        },
        "subprocesses": [
            {
                "module": row["module"],
                "args": row["args"],
                "returncode": row["returncode"],
                "output_tail": row["output"][-6000:],
            }
            for row in subprocess_reports
        ],
    }

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    txt_path.write_text(
        "\n".join([
            "LIFECYCLE TRACKER STEP 8G - FINAL OFFLINE INTEGRATION VALIDATION",
            "=" * 100,
            f"Tests : {passed}/{total}",
            status,
            f"Daily Run version : {daily_run.DAILY_RUN_VERSION}",
            f"Pipeline          : {daily_run.STEP_ORDER}",
            f"Preflight         : {preflight['ok']}",
            f"Lifecycle counts  : {snap['counts']}",
            f"APPLIED total     : {snap['applied_total']}",
            f"Non-USER APPLIED  : {snap['non_user_applied']}",
            f"REPOSTED events   : {snap['reposted_count']}",
        ]),
        encoding="utf-8",
    )

    print("JSON audit :", json_path)
    print("TXT audit  :", txt_path)

    if not all(tests):
        print()
        print("FAILED SUBPROCESS OUTPUTS")
        print("-" * 100)
        for row in subprocess_reports:
            if row["returncode"] != 0:
                print(row["module"])
                print(row["output"][-4000:])
                print("-" * 100)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
