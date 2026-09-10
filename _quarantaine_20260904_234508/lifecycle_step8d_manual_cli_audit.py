"""
Lifecycle Tracker Step 8D — Manual CLI Audit

Production DB: read-only checks only.
Behavioral mutations: temp DB only.

No network. No Main. No Daily Run.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from applications import lifecycle_tracker as lt
import lifecycle


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


def production_snapshot():
    uri = DB_PATH.resolve().as_uri() + "?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    try:
        entities = conn.execute(
            "SELECT COUNT(*) FROM application_entities"
        ).fetchone()[0]
        applied = conn.execute(
            """
            SELECT COUNT(*)
            FROM application_events
            WHERE event_type='STATUS' AND status='APPLIED'
            """
        ).fetchone()[0]
        return entities, applied
    finally:
        conn.close()


def main():
    print("=" * 100)
    print("LIFECYCLE TRACKER STEP 8D - MANUAL CLI AUDIT")
    print("=" * 100)

    tests = []

    entities, applied = production_snapshot()

    # Compte non épinglé : il suit la taille du Final Pool.
    tests.append(check(
        "Production still has lifecycle entities",
        entities >= 1,
        str(entities),
    ))

    tests.append(check(
        "No real APPLIED before manual user action",
        applied == 0,
        str(applied),
    ))

    tests.append(check(
        "CLI version 1.0",
        lifecycle.CLI_VERSION == "1.0",
        lifecycle.CLI_VERSION,
    ))

    tests.append(check(
        "French POSTULE alias maps to APPLIED",
        lifecycle.normalize_status("postulé") == "APPLIED",
    ))

    with tempfile.TemporaryDirectory(
        prefix="jobhunter_lifecycle_step8d_"
    ) as tmp:
        db = Path(tmp) / "test.db"
        conn = lt.connect_database(db)
        try:
            lt.ensure_schema(conn)

            e1 = lt.create_entity(
                conn,
                seed="ITEM_ONE",
                application_group_id="GROUP_ONE",
                title="Technicien laboratoire",
                company="Example Pharma",
                location="Bruxelles",
                track="LAB_QC",
            )
            lt.attach_alias(
                conn,
                entity_id=e1,
                identity_type="STABLE_ITEM_KEY",
                identity_value="ITEM_ONE",
                source="FOREM",
            )
            lt.attach_alias(
                conn,
                entity_id=e1,
                identity_type="APPLICATION_GROUP_ID",
                identity_value="GROUP_ONE",
                source="FOREM",
            )
            lt.attach_alias(
                conn,
                entity_id=e1,
                identity_type="URL",
                identity_value="https://example.test/one",
                source="FOREM",
            )
            lt.record_event(
                conn,
                entity_id=e1,
                event_type="STATUS",
                status="READY",
                actor_type="MIGRATION",
                actor="TEST",
            )
            conn.commit()

            by_stable = lifecycle.resolve_entity(
                conn,
                "ITEM_ONE",
            )
            by_group = lifecycle.resolve_entity(
                conn,
                "GROUP_ONE",
            )
            by_life = lifecycle.resolve_entity(
                conn,
                by_stable["lifecycle_id"],
            )

            tests.append(check(
                "Resolve by stable key",
                by_stable["id"] == e1,
            ))
            tests.append(check(
                "Resolve by application group",
                by_group["id"] == e1,
            ))
            tests.append(check(
                "Resolve by lifecycle id",
                by_life["id"] == e1,
            ))

            before_events = len(
                lt.event_history(conn, e1)
            )

            result = lifecycle.set_status(
                conn,
                entity=by_stable,
                status="APPLIED",
                note="Test manual application",
                actor="USER",
                write_log=False,
            )

            state = lt.current_state(conn, e1)
            tests.append(check(
                "Manual CLI creates USER APPLIED",
                (
                    result["status"] == "UPDATED"
                    and state["current_status"] == "APPLIED"
                    and state["status_actor_type"] == "USER"
                ),
                str(state),
            ))

            after_first = len(
                lt.event_history(conn, e1)
            )

            no_change = lifecycle.set_status(
                conn,
                entity=by_stable,
                status="APPLIED",
                actor="USER",
                write_log=False,
            )
            after_second = len(
                lt.event_history(conn, e1)
            )

            tests.append(check(
                "Same status is idempotent / no duplicate event",
                (
                    no_change["status"] == "NO_CHANGE"
                    and after_first == after_second
                    and after_first == before_events + 1
                ),
                f"{before_events}->{after_first}->{after_second}",
            ))

            note_result = lifecycle.add_note(
                conn,
                entity=by_stable,
                text="Recruiter called",
                actor="USER",
                write_log=False,
            )
            state_after_note = lt.current_state(
                conn,
                e1,
            )

            tests.append(check(
                "Manual note is append-only event",
                note_result["status"] == "NOTE_ADDED",
            ))
            tests.append(check(
                "NOTE does not change current status",
                state_after_note["current_status"] == "APPLIED",
                state_after_note["current_status"],
            ))

            rows = lifecycle.list_entities(
                conn,
                status="APPLIED",
                limit=10,
            )
            tests.append(check(
                "List filter returns APPLIED item",
                len(rows) == 1
                and rows[0]["stable_item_key"] == "ITEM_ONE",
                str(rows),
            ))

            search = lifecycle.search_entities(
                conn,
                "Example Pharma",
                limit=10,
            )
            tests.append(check(
                "Search by company works",
                len(search) == 1
                and search[0]["entity_id"] == e1,
            ))

            hist = lifecycle.history(
                conn,
                e1,
            )
            tests.append(check(
                "History contains STATUS + NOTE",
                (
                    any(
                        row["event_type"] == "STATUS"
                        and row["status"] == "APPLIED"
                        for row in hist
                    )
                    and any(
                        row["event_type"] == "NOTE"
                        for row in hist
                    )
                ),
            ))

            # Ensure manual statuses beyond APPLIED remain possible as USER.
            lifecycle.set_status(
                conn,
                entity=by_stable,
                status="INTERVIEW",
                actor="USER",
                write_log=False,
            )
            lifecycle.set_status(
                conn,
                entity=by_stable,
                status="OFFER",
                actor="USER",
                write_log=False,
            )
            final = lt.current_state(conn, e1)

            tests.append(check(
                "Manual USER INTERVIEW/OFFER accepted",
                final["current_status"] == "OFFER",
                final["current_status"],
            ))

        finally:
            conn.close()

    passed = sum(tests)
    total = len(tests)
    status = (
        "LIFECYCLE TRACKER STEP 8D VALIDE."
        if all(tests)
        else "LIFECYCLE TRACKER STEP 8D NON VALIDE."
    )

    print()
    print(f"Tests : {passed}/{total}")
    print(status)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = (
        LOG_DIR
        / f"lifecycle_step8d_manual_cli_audit_{stamp}.json"
    )
    txt_path = (
        LOG_DIR
        / f"lifecycle_step8d_manual_cli_audit_{stamp}.txt"
    )

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "checks_passed": passed,
        "checks_total": total,
        "status": status,
        "cli_version": lifecycle.CLI_VERSION,
        "production_entities": entities,
        "production_applied_before_manual_use": applied,
        "commands": [
            "list",
            "search",
            "show",
            "history",
            "set-status",
            "note",
        ],
    }

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    txt_path.write_text(
        "\n".join([
            "LIFECYCLE TRACKER STEP 8D - MANUAL CLI AUDIT",
            "=" * 100,
            f"Tests : {passed}/{total}",
            status,
            f"Production entities : {entities}",
            f"Production APPLIED  : {applied}",
        ]),
        encoding="utf-8",
    )

    print("JSON audit :", json_path)
    print("TXT audit  :", txt_path)

    if not all(tests):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
