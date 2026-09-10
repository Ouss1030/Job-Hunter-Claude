"""
Lifecycle Tracker Step 8E — Sync Audit

Production DB:
- read-only dry analysis only.

Behavior:
- temp DB only.

No network.
No Main.
No Daily Run.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from applications import lifecycle_tracker as lt
from applications import lifecycle_sync as ls


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "database" / "jobs.db"
LOG_DIR = ROOT / "exports" / "logs"


def check(
    label,
    condition,
    detail="",
):
    ok = bool(condition)
    print(
        f"[{'PASS' if ok else 'FAIL'}] "
        f"{label}"
        + (
            f" | {detail}"
            if detail
            else ""
        )
    )
    return ok


def production_analysis():
    final_path = ls.latest_matching(
        LOG_DIR,
        "final_application_pool_v12_[0-9]*.json",
    )
    delta_path = ls.latest_matching(
        LOG_DIR,
        "delta_tracker_v1_[0-9]*.json",
    )

    if (
        final_path is None
        or delta_path is None
    ):
        raise RuntimeError(
            "Current Final Pool/Delta missing"
        )

    final_items = ls.get_items(
        ls.load_json(final_path)
    )
    delta_items = ls.get_items(
        ls.load_json(delta_path)
    )

    uri = (
        DB_PATH.resolve().as_uri()
        + "?mode=ro&immutable=1"
    )
    conn = sqlite3.connect(
        uri,
        uri=True,
    )
    conn.row_factory = sqlite3.Row

    try:
        analysis = ls.analyze_sync(
            conn,
            final_items=final_items,
            delta_items=delta_items,
        )

        entities = conn.execute(
            """
            SELECT COUNT(*)
            FROM application_entities
            """
        ).fetchone()[0]

        applied = conn.execute(
            """
            SELECT COUNT(*)
            FROM application_events
            WHERE
                event_type='STATUS'
                AND status='APPLIED'
            """
        ).fetchone()[0]

    finally:
        conn.close()

    return {
        "analysis": analysis,
        "final_path":
            str(final_path),
        "delta_path":
            str(delta_path),
        "entities":
            entities,
        "applied":
            applied,
    }


def build_synthetic_db(
    db_path: Path,
):
    conn = lt.connect_database(
        db_path
    )
    lt.ensure_schema(conn)

    # Existing A: READY auto status.
    a = lt.create_entity(
        conn,
        seed="ITEM_A",
        application_group_id=
            "GROUP_A",
        title="Lab A",
        company="Company A",
        location="Bruxelles",
        track="LAB_QC",
    )
    lt.attach_alias(
        conn,
        entity_id=a,
        identity_type=
            "STABLE_ITEM_KEY",
        identity_value="ITEM_A",
        source="FOREM",
    )
    lt.attach_alias(
        conn,
        entity_id=a,
        identity_type=
            "APPLICATION_GROUP_ID",
        identity_value="GROUP_A",
        source="FOREM",
    )
    lt.record_event(
        conn,
        entity_id=a,
        event_type="STATUS",
        status="READY",
        actor_type="MIGRATION",
        actor="TEST_SETUP",
    )

    # Existing B: real manual APPLIED.
    b = lt.create_entity(
        conn,
        seed="ITEM_B",
        application_group_id=
            "GROUP_B",
        title="Data B",
        company="Company B",
        location="Bruxelles",
        track="DATA",
    )
    lt.attach_alias(
        conn,
        entity_id=b,
        identity_type=
            "STABLE_ITEM_KEY",
        identity_value="ITEM_B",
        source="ACTIRIS",
    )
    lt.attach_alias(
        conn,
        entity_id=b,
        identity_type=
            "APPLICATION_GROUP_ID",
        identity_value="GROUP_B",
        source="ACTIRIS",
    )
    lt.record_user_status(
        conn,
        entity_id=b,
        status="APPLIED",
        actor="USER",
    )

    # Existing C old identity: manual REJECTED.
    c = lt.create_entity(
        conn,
        seed="ITEM_C_OLD",
        application_group_id=
            "GROUP_C",
        title="QC C",
        company="Company C",
        location="Wavre",
        track="LAB_QC",
    )
    lt.attach_alias(
        conn,
        entity_id=c,
        identity_type=
            "STABLE_ITEM_KEY",
        identity_value=
            "ITEM_C_OLD",
        source="FOREM",
    )
    lt.attach_alias(
        conn,
        entity_id=c,
        identity_type=
            "APPLICATION_GROUP_ID",
        identity_value=
            "GROUP_C",
        source="FOREM",
    )
    lt.attach_alias(
        conn,
        entity_id=c,
        identity_type="URL",
        identity_value=
            "https://example.test/c-old",
        source="FOREM",
    )
    lt.record_user_status(
        conn,
        entity_id=c,
        status="REJECTED",
        actor="USER",
    )

    conn.commit()
    return conn, a, b, c


def synthetic_payloads():
    final_items = [
        {
            "stable_item_key":
                "ITEM_A",
            "application_group_id":
                "GROUP_A",
            "source": "FOREM",
            "origin_source":
                "FOREM",
            "url":
                "https://example.test/a",
            "title": "Lab A",
            "company": "Company A",
            "location": "Bruxelles",
            "track": "LAB_QC",
            # Lower decision than current READY:
            # must NOT downgrade.
            "recommended_action_v12":
                "REVIEW_FIRST",
        },
        {
            "stable_item_key":
                "ITEM_B",
            "application_group_id":
                "GROUP_B",
            "source": "ACTIRIS",
            "origin_source":
                "ACTIRIS",
            "url":
                "https://example.test/b",
            "title": "Data B",
            "company": "Company B",
            "location": "Bruxelles",
            "track": "DATA",
            # Manual APPLIED must remain APPLIED.
            "recommended_action_v12":
                "DO_NOT_APPLY",
        },
        {
            "stable_item_key":
                "ITEM_C_NEW",
            "application_group_id":
                "GROUP_C",
            "source": "FOREM",
            "origin_source":
                "FOREM",
            "url":
                "https://example.test/c-new",
            "title": "QC C",
            "company": "Company C",
            "location": "Wavre",
            "track": "LAB_QC",
            # Manual REJECTED on old identity
            # must be preserved.
            "recommended_action_v12":
                "APPLY_NOW",
        },
        {
            "stable_item_key":
                "ITEM_D",
            "application_group_id":
                "GROUP_D",
            "source": "FOREM",
            "origin_source":
                "FOREM",
            "url":
                "https://example.test/d",
            "title": "Lab D",
            "company": "Company D",
            "location": "Bruxelles",
            "track": "LAB_QC",
            "recommended_action_v12":
                "APPLY_NOW",
        },
    ]

    delta_items = [
        {
            "identity_key":
                "ITEM_A",
            "identity_method":
                "STABLE_ITEM_KEY",
            "delta_status":
                "UNCHANGED",
            "source": "FOREM",
        },
        {
            "identity_key":
                "ITEM_B",
            "identity_method":
                "STABLE_ITEM_KEY",
            "delta_status":
                "UPDATED",
            "source": "ACTIRIS",
        },
        {
            "identity_key":
                "ITEM_C_NEW",
            "identity_method":
                "STABLE_ITEM_KEY",
            "delta_status":
                "REPOSTED",
            "source": "FOREM",
            "reposted_from_identity_key":
                "ITEM_C_OLD",
            "repost_confidence":
                "EXACT_CONTENT_MATCH",
            "previous_url":
                "https://example.test/c-old",
            "current_url":
                "https://example.test/c-new",
        },
        {
            "identity_key":
                "ITEM_D",
            "identity_method":
                "STABLE_ITEM_KEY",
            "delta_status":
                "NEW",
            "source": "FOREM",
        },
        # Must never auto-close anything.
        {
            "identity_key":
                "ITEM_GONE",
            "delta_status":
                "DISAPPEARED",
            "source": "FOREM",
        },
    ]

    return final_items, delta_items


def main():
    print(
        "=" * 100
    )
    print(
        "LIFECYCLE TRACKER STEP 8E "
        "- SYNC AUDIT"
    )
    print(
        "=" * 100
    )

    tests = []

    prod = production_analysis()

    tests.append(
        check(
            "Sync version 1.0",
            ls.LIFECYCLE_SYNC_VERSION
            == "1.0",
            ls.LIFECYCLE_SYNC_VERSION,
        )
    )

    # Compte non épinglé : il suit la taille du Final Pool.
    tests.append(
        check(
            "Production still has entities",
            prod["entities"] >= 1,
            str(prod["entities"]),
        )
    )

    tests.append(
        check(
            "Production still has zero real APPLIED",
            prod["applied"] == 0,
            str(prod["applied"]),
        )
    )

    analysis = prod[
        "analysis"
    ]

    tests.append(
        check(
            "Current production artifacts resolve with zero new entities",
            analysis["counts"].get(
                "new_entities",
                0,
            ) == 0,
            str(
                analysis["counts"]
            ),
        )
    )

    tests.append(
        check(
            "Current production analysis has no identity warnings",
            not analysis["warnings"],
            str(
                analysis["warnings"]
            ),
        )
    )

    with tempfile.TemporaryDirectory(
        prefix=
            "jobhunter_lifecycle_step8e_"
    ) as tmp:
        db_path = (
            Path(tmp)
            / "test.db"
        )

        (
            conn,
            entity_a,
            entity_b,
            entity_c,
        ) = build_synthetic_db(
            db_path
        )

        try:
            (
                final_items,
                delta_items,
            ) = synthetic_payloads()

            first = ls.sync_lifecycle(
                conn,
                final_items=
                    final_items,
                delta_items=
                    delta_items,
                sync_token=
                    "DELTA_ARTIFACT:"
                    "delta_test_001.json",
                event_at=
                    "2026-08-19T01:00:00+00:00",
            )

            state_a = lt.current_state(
                conn,
                entity_a,
            )
            state_b = lt.current_state(
                conn,
                entity_b,
            )
            state_c = lt.current_state(
                conn,
                entity_c,
            )

            entity_d = (
                lt.resolve_entity_by_alias(
                    conn,
                    identity_type=
                        "STABLE_ITEM_KEY",
                    identity_value=
                        "ITEM_D",
                )
            )
            state_d = (
                lt.current_state(
                    conn,
                    entity_d["id"],
                )
            )

            old_c = (
                lt.resolve_entity_by_alias(
                    conn,
                    identity_type=
                        "STABLE_ITEM_KEY",
                    identity_value=
                        "ITEM_C_OLD",
                )
            )
            new_c = (
                lt.resolve_entity_by_alias(
                    conn,
                    identity_type=
                        "STABLE_ITEM_KEY",
                    identity_value=
                        "ITEM_C_NEW",
                )
            )

            tests.append(
                check(
                    "READY is not downgraded to SHORTLISTED",
                    state_a[
                        "current_status"
                    ] == "READY",
                    state_a[
                        "current_status"
                    ],
                )
            )

            tests.append(
                check(
                    "Manual APPLIED preserved against DO_NOT_APPLY",
                    state_b[
                        "current_status"
                    ] == "APPLIED"
                    and state_b[
                        "status_actor_type"
                    ] == "USER",
                    str(state_b),
                )
            )

            tests.append(
                check(
                    "Manual REJECTED preserved across REPOSTED",
                    state_c[
                        "current_status"
                    ] == "REJECTED"
                    and state_c[
                        "status_actor_type"
                    ] == "USER",
                    str(state_c),
                )
            )

            tests.append(
                check(
                    "REPOSTED old/new stable keys share one entity",
                    (
                        old_c is not None
                        and new_c
                        is not None
                        and old_c["id"]
                        == new_c["id"]
                        == entity_c
                    ),
                )
            )

            tests.append(
                check(
                    "New APPLY_NOW entity auto-advances to READY",
                    (
                        entity_d
                        is not None
                        and state_d[
                            "current_status"
                        ]
                        == "READY"
                        and state_d[
                            "status_actor_type"
                        ]
                        == "SYSTEM"
                    ),
                    str(state_d),
                )
            )

            tests.append(
                check(
                    "DISAPPEARED policy is no status change",
                    first[
                        "disappeared_policy"
                    ]
                    == "NO_STATUS_CHANGE"
                    and first[
                        "counts"
                    ].get(
                        "disappeared_records_ignored_for_status",
                        0,
                    )
                    == 1,
                    str(
                        first["counts"]
                    ),
                )
            )

            non_user_applied = (
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM application_events
                    WHERE
                        status='APPLIED'
                        AND actor_type <> 'USER'
                    """
                ).fetchone()[0]
            )

            tests.append(
                check(
                    "Sync creates zero automatic APPLIED",
                    non_user_applied
                    == 0,
                    str(
                        non_user_applied
                    ),
                )
            )

            counts_before_second = {
                "entities":
                    conn.execute(
                        """
                        SELECT COUNT(*)
                        FROM application_entities
                        """
                    ).fetchone()[0],
                "events":
                    conn.execute(
                        """
                        SELECT COUNT(*)
                        FROM application_events
                        """
                    ).fetchone()[0],
                "aliases":
                    conn.execute(
                        """
                        SELECT COUNT(*)
                        FROM source_identity_aliases
                        """
                    ).fetchone()[0],
            }

            second = ls.sync_lifecycle(
                conn,
                final_items=
                    final_items,
                delta_items=
                    delta_items,
                sync_token=
                    "DELTA_ARTIFACT:"
                    "delta_test_001.json",
                event_at=
                    "2026-08-19T01:00:00+00:00",
            )

            counts_after_second = {
                "entities":
                    conn.execute(
                        """
                        SELECT COUNT(*)
                        FROM application_entities
                        """
                    ).fetchone()[0],
                "events":
                    conn.execute(
                        """
                        SELECT COUNT(*)
                        FROM application_events
                        """
                    ).fetchone()[0],
                "aliases":
                    conn.execute(
                        """
                        SELECT COUNT(*)
                        FROM source_identity_aliases
                        """
                    ).fetchone()[0],
            }

            tests.append(
                check(
                    "Same Delta artifact is event/entity idempotent",
                    (
                        counts_before_second
                        == counts_after_second
                    ),
                    (
                        f"{counts_before_second}"
                        f" -> "
                        f"{counts_after_second}"
                    ),
                )
            )

            repost_count = (
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM application_events
                    WHERE event_type='REPOSTED'
                    """
                ).fetchone()[0]
            )

            tests.append(
                check(
                    "Exactly one synthetic REPOSTED event",
                    repost_count == 1,
                    str(repost_count),
                )
            )

            tests.append(
                check(
                    "Second sync creates no duplicate SEEN/REPOSTED/status event",
                    (
                        second["counts"].get(
                            "seen_events_created",
                            0,
                        )
                        == 0
                        and second[
                            "counts"
                        ].get(
                            "reposted_events_created",
                            0,
                        )
                        == 0
                        and not second[
                            "status_events_created"
                        ]
                    ),
                    str(second),
                )
            )

        finally:
            conn.close()

    passed = sum(
        tests
    )
    total = len(
        tests
    )

    status = (
        "LIFECYCLE TRACKER "
        "STEP 8E VALIDE."
        if all(tests)
        else
        "LIFECYCLE TRACKER "
        "STEP 8E NON VALIDE."
    )

    print()
    print(
        f"Tests : {passed}/{total}"
    )
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
        / (
            "lifecycle_step8e_sync_audit_"
            f"{stamp}.json"
        )
    )
    txt_path = (
        LOG_DIR
        / (
            "lifecycle_step8e_sync_audit_"
            f"{stamp}.txt"
        )
    )

    payload = {
        "generated_at":
            datetime.now().isoformat(
                timespec="seconds"
            ),
        "checks_passed":
            passed,
        "checks_total":
            total,
        "status":
            status,
        "sync_version":
            ls.LIFECYCLE_SYNC_VERSION,
        "production_analysis":
            prod,
        "rules": {
            "no_auto_applied":
                True,
            "no_auto_closed":
                True,
            "no_auto_downgrade":
                True,
            "protected_manual_statuses":
                sorted(
                    ls.PROTECTED_STATUSES
                ),
            "repost_same_entity":
                True,
            "same_artifact_idempotent":
                True,
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
            "LIFECYCLE TRACKER "
            "STEP 8E - SYNC AUDIT",
            "=" * 100,
            f"Tests : {passed}/{total}",
            status,
            (
                "Production entities : "
                f"{prod['entities']}"
            ),
            (
                "Production APPLIED : "
                f"{prod['applied']}"
            ),
            (
                "Production dry analysis : "
                f"{analysis['counts']}"
            ),
        ]),
        encoding="utf-8",
    )

    print(
        "JSON audit :",
        json_path,
    )
    print(
        "TXT audit  :",
        txt_path,
    )

    if not all(tests):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
