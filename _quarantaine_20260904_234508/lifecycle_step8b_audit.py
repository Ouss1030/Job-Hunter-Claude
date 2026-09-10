"""
LIFECYCLE TRACKER STEP 8B — CORE AUDIT

Validates:
- production schema installation (read-only checks);
- temp-DB behavior;
- append-only events;
- current status derived from event history;
- APPLIED user-only at Python + SQLite trigger layers;
- visibility/repost does not alter lifecycle status.

No network.
No Main.
No Daily Run.
No writes to production DB.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from applications import lifecycle_tracker as lt


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


def production_schema():
    uri = DB_PATH.resolve().as_uri() + "?mode=ro&immutable=1"
    conn = sqlite3.connect(
        uri,
        uri=True,
    )
    try:
        tables = {
            row[0]
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type='table'
                """
            )
        }
        views = {
            row[0]
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type='view'
                """
            )
        }
        triggers = {
            row[0]
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type='trigger'
                """
            )
        }
        counts = {
            name: conn.execute(
                f'SELECT COUNT(*) FROM "{name}"'
            ).fetchone()[0]
            for name in (
                "application_entities",
                "application_events",
                "source_identity_aliases",
            )
            if name in tables
        }
        return tables, views, triggers, counts
    finally:
        conn.close()


def main():
    print("=" * 100)
    print("LIFECYCLE TRACKER STEP 8B - CORE AUDIT")
    print("=" * 100)

    tests = []

    tests.append(check(
        "Lifecycle version 1.0",
        lt.LIFECYCLE_VERSION == "1.0",
        lt.LIFECYCLE_VERSION,
    ))

    tables, views, triggers, counts = production_schema()

    required_tables = {
        "application_entities",
        "application_events",
        "source_identity_aliases",
    }
    tests.append(check(
        "3 lifecycle tables installed",
        required_tables <= tables,
        str(sorted(required_tables & tables)),
    ))

    tests.append(check(
        "Lifecycle current-state view installed",
        "application_current_state" in views,
    ))

    required_triggers = {
        "trg_application_events_no_update",
        "trg_application_events_no_delete",
        "trg_application_events_applied_user_only",
        "trg_application_events_system_manual_status_block",
    }
    tests.append(check(
        "Lifecycle safety triggers installed",
        required_triggers <= triggers,
        str(sorted(required_triggers & triggers)),
    ))

    tests.append(check(
        "Production lifecycle tables still empty before bootstrap",
        counts == {
            "application_entities": 0,
            "application_events": 0,
            "source_identity_aliases": 0,
        },
        str(counts),
    ))

    with tempfile.TemporaryDirectory(
        prefix="jobhunter_lifecycle_step8b_"
    ) as tmp:
        db = Path(tmp) / "lifecycle_test.db"
        conn = lt.connect_database(db)

        try:
            lt.ensure_schema(conn)

            entity_id = lt.create_entity(
                conn,
                seed="ITEM_TEST_1",
                application_group_id="GROUP_TEST_1",
                title="Technicien laboratoire",
                company="Example Pharma",
                location="Bruxelles",
                track="LAB_QC",
            )

            tests.append(check(
                "Entity created",
                entity_id > 0,
                str(entity_id),
            ))

            lt.attach_alias(
                conn,
                entity_id=entity_id,
                identity_type="STABLE_ITEM_KEY",
                identity_value="ITEM_TEST_1",
                source="FOREM",
            )
            lt.attach_alias(
                conn,
                entity_id=entity_id,
                identity_type="APPLICATION_GROUP_ID",
                identity_value="GROUP_TEST_1",
                source="FOREM",
            )

            resolved = lt.resolve_entity_by_alias(
                conn,
                identity_type="STABLE_ITEM_KEY",
                identity_value="ITEM_TEST_1",
            )
            tests.append(check(
                "Alias resolves same entity",
                resolved is not None
                and resolved["id"] == entity_id,
            ))

            lt.record_system_status(
                conn,
                entity_id=entity_id,
                status="DISCOVERED",
                actor="TEST_SYNC",
                event_at="2026-08-19T00:00:00+00:00",
            )
            lt.record_system_status(
                conn,
                entity_id=entity_id,
                status="SHORTLISTED",
                actor="TEST_SYNC",
                event_at="2026-08-19T00:01:00+00:00",
            )

            state = lt.current_state(
                conn,
                entity_id,
            )
            tests.append(check(
                "Current status derived from latest STATUS event",
                state["current_status"] == "SHORTLISTED",
                state["current_status"],
            ))

            lt.record_visibility_event(
                conn,
                entity_id=entity_id,
                event_type="SEEN",
                actor="TEST_DELTA",
                stable_item_key="ITEM_TEST_1",
                event_at="2026-08-19T00:02:00+00:00",
            )
            state_after_seen = lt.current_state(
                conn,
                entity_id,
            )
            tests.append(check(
                "SEEN does not change lifecycle status",
                state_after_seen["current_status"] == "SHORTLISTED",
                state_after_seen["current_status"],
            ))

            # Repost lineage: second stable key -> same lifecycle entity.
            lt.attach_alias(
                conn,
                entity_id=entity_id,
                identity_type="STABLE_ITEM_KEY",
                identity_value="ITEM_TEST_2",
                source="FOREM",
                evidence={"reason": "EXACT_CONTENT_MATCH"},
            )
            lt.record_visibility_event(
                conn,
                entity_id=entity_id,
                event_type="REPOSTED",
                actor="TEST_DELTA",
                stable_item_key="ITEM_TEST_2",
                related_identity_value="ITEM_TEST_1",
                event_at="2026-08-19T00:03:00+00:00",
            )

            resolved_repost = lt.resolve_entity_by_alias(
                conn,
                identity_type="STABLE_ITEM_KEY",
                identity_value="ITEM_TEST_2",
            )
            tests.append(check(
                "Reposted identity stays on same lifecycle entity",
                resolved_repost is not None
                and resolved_repost["id"] == entity_id,
            ))

            # Python-layer APPLIED guard.
            python_applied_blocked = False
            try:
                lt.record_system_status(
                    conn,
                    entity_id=entity_id,
                    status="APPLIED",
                    actor="TEST_SYNC",
                )
            except PermissionError:
                python_applied_blocked = True

            tests.append(check(
                "Python blocks automatic APPLIED",
                python_applied_blocked,
            ))

            # DB-layer APPLIED guard bypassing Python helper.
            db_applied_blocked = False
            try:
                conn.execute(
                    """
                    INSERT INTO application_events (
                        entity_id,
                        event_type,
                        status,
                        actor_type,
                        actor,
                        event_at
                    )
                    VALUES (?, 'STATUS', 'APPLIED', 'SYSTEM', 'RAW_SQL_TEST', ?)
                    """,
                    (
                        entity_id,
                        "2026-08-19T00:04:00+00:00",
                    ),
                )
            except sqlite3.IntegrityError:
                db_applied_blocked = True

            tests.append(check(
                "SQLite trigger blocks automatic APPLIED",
                db_applied_blocked,
            ))

            lt.record_user_status(
                conn,
                entity_id=entity_id,
                status="APPLIED",
                actor="USER",
                event_at="2026-08-19T00:05:00+00:00",
            )
            state_applied = lt.current_state(
                conn,
                entity_id,
            )
            tests.append(check(
                "Explicit USER APPLIED accepted",
                state_applied["current_status"] == "APPLIED"
                and state_applied["status_actor_type"] == "USER",
                str({
                    "status": state_applied["current_status"],
                    "actor_type": state_applied["status_actor_type"],
                }),
            ))

            system_closed_blocked = False
            try:
                lt.record_system_status(
                    conn,
                    entity_id=entity_id,
                    status="CLOSED",
                    actor="TEST_SYNC",
                )
            except PermissionError:
                system_closed_blocked = True

            tests.append(check(
                "SYSTEM cannot auto-CLOSE disappeared offer",
                system_closed_blocked,
            ))

            # Append-only UPDATE/DELETE safety.
            first_event_id = lt.event_history(
                conn,
                entity_id,
            )[0]["id"]

            update_blocked = False
            try:
                conn.execute(
                    """
                    UPDATE application_events
                    SET note='tampered'
                    WHERE id=?
                    """,
                    (first_event_id,),
                )
            except sqlite3.IntegrityError:
                update_blocked = True

            tests.append(check(
                "Event UPDATE blocked",
                update_blocked,
            ))

            delete_blocked = False
            try:
                conn.execute(
                    """
                    DELETE FROM application_events
                    WHERE id=?
                    """,
                    (first_event_id,),
                )
            except sqlite3.IntegrityError:
                delete_blocked = True

            tests.append(check(
                "Event DELETE blocked",
                delete_blocked,
            ))

            history = lt.event_history(
                conn,
                entity_id,
            )
            tests.append(check(
                "Event history preserved",
                len(history) >= 5,
                str(len(history)),
            ))

        finally:
            conn.close()

    passed = sum(tests)
    total = len(tests)
    status = (
        "LIFECYCLE TRACKER STEP 8B VALIDE."
        if all(tests)
        else "LIFECYCLE TRACKER STEP 8B NON VALIDE."
    )

    print()
    print(f"Tests : {passed}/{total}")
    print(status)

    LOG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )
    stamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    json_path = (
        LOG_DIR
        / f"lifecycle_step8b_core_audit_{stamp}.json"
    )
    txt_path = (
        LOG_DIR
        / f"lifecycle_step8b_core_audit_{stamp}.txt"
    )

    payload = {
        "generated_at": datetime.now().isoformat(
            timespec="seconds"
        ),
        "checks_passed": passed,
        "checks_total": total,
        "status": status,
        "lifecycle_version": lt.LIFECYCLE_VERSION,
        "schema_version": lt.LIFECYCLE_SCHEMA_VERSION,
        "production_counts": counts,
        "rules": {
            "current_state_derived_from_events": True,
            "applied_user_only": True,
            "system_manual_outcomes_blocked": True,
            "events_append_only": True,
            "visibility_does_not_change_status": True,
        },
    }

    json_path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    txt_path.write_text(
        "\n".join([
            "LIFECYCLE TRACKER STEP 8B - CORE AUDIT",
            "=" * 100,
            f"Tests : {passed}/{total}",
            status,
            f"Production lifecycle counts : {counts}",
            "APPLIED user-only : True",
            "Events append-only : True",
        ]),
        encoding="utf-8",
    )

    print("JSON audit :", json_path)
    print("TXT audit  :", txt_path)

    if not all(tests):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
