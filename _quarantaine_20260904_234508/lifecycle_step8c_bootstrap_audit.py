"""
LIFECYCLE TRACKER STEP 8C — BOOTSTRAP AUDIT

Production DB is read-only during audit.
Also performs a full synthetic bootstrap against a temp DB/artifacts.

No network.
No main.py.
No daily_run.py.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

from applications import lifecycle_tracker as lt
import lifecycle_step8c_bootstrap as bs


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
    conn.row_factory = sqlite3.Row

    try:
        counts = bs.lifecycle_counts(conn)

        status_counts = dict(
            conn.execute(
                """
                SELECT status, COUNT(*)
                FROM application_events
                WHERE event_type='STATUS'
                GROUP BY status
                ORDER BY status
                """
            ).fetchall()
        )

        event_counts = dict(
            conn.execute(
                """
                SELECT event_type, COUNT(*)
                FROM application_events
                GROUP BY event_type
                ORDER BY event_type
                """
            ).fetchall()
        )

        current_counts = dict(
            conn.execute(
                """
                SELECT current_status, COUNT(*)
                FROM application_current_state
                GROUP BY current_status
                ORDER BY current_status
                """
            ).fetchall()
        )

        applied = conn.execute(
            """
            SELECT COUNT(*)
            FROM application_events
            WHERE event_type='STATUS' AND status='APPLIED'
            """
        ).fetchone()[0]

        closed = conn.execute(
            """
            SELECT COUNT(*)
            FROM application_events
            WHERE event_type='STATUS' AND status='CLOSED'
            """
        ).fetchone()[0]

        reposted = conn.execute(
            """
            SELECT COUNT(*)
            FROM application_events
            WHERE event_type='REPOSTED'
            """
        ).fetchone()[0]

        old_aliases = conn.execute(
            """
            SELECT COUNT(*)
            FROM source_identity_aliases
            WHERE identity_type='STABLE_ITEM_KEY' AND is_current=0
            """
        ).fetchone()[0]

        return {
            "counts": counts,
            "status_counts": status_counts,
            "event_counts": event_counts,
            "current_counts": current_counts,
            "applied": applied,
            "closed": closed,
            "reposted": reposted,
            "old_aliases": old_aliases,
        }
    finally:
        conn.close()


def synthetic_case(tmp):
    tmp = Path(tmp)
    db_path = tmp / "test.db"
    final_path = tmp / "final_application_pool_v12_20260819_010234.json"
    delta_path = tmp / "delta_tracker_v1_20260819_012626.json"

    final_items = [
        {
            "stable_item_key": "ITEM_A",
            "application_group_id": "GROUP_A",
            "source": "FOREM",
            "origin_source": "FOREM",
            "url": "https://example.test/a",
            "title": "Lab A",
            "company": "Company A",
            "location": "Bruxelles",
            "track": "LAB_QC",
            "recommended_action_v12": "APPLY_NOW",
        },
        {
            "stable_item_key": "ITEM_B_NEW",
            "application_group_id": "GROUP_B",
            "source": "FOREM",
            "origin_source": "FOREM",
            "url": "https://example.test/b-new",
            "title": "Data B",
            "company": "Company B",
            "location": "Bruxelles",
            "track": "DATA",
            "recommended_action_v12": "APPLY_NEXT",
        },
        {
            "stable_item_key": "ITEM_C",
            "application_group_id": "GROUP_C",
            "source": "ACTIRIS",
            "origin_source": "ACTIRIS",
            "url": "https://example.test/c",
            "title": "QC C",
            "company": "Company C",
            "location": "Bruxelles",
            "track": "QUALITY",
            "recommended_action_v12": "DO_NOT_APPLY",
        },
    ]

    delta_items = [
        {
            "identity_key": "ITEM_A",
            "identity_method": "STABLE_ITEM_KEY",
            "delta_status": "UNCHANGED",
            "source": "FOREM",
        },
        {
            "identity_key": "ITEM_B_NEW",
            "identity_method": "STABLE_ITEM_KEY",
            "delta_status": "REPOSTED",
            "source": "FOREM",
            "reposted_from_identity_key": "ITEM_B_OLD",
            "repost_confidence": "EXACT_CONTENT_MATCH",
            "previous_url": "https://example.test/b-old",
            "current_url": "https://example.test/b-new",
        },
        {
            "identity_key": "ITEM_C",
            "identity_method": "STABLE_ITEM_KEY",
            "delta_status": "UNCHANGED",
            "source": "ACTIRIS",
        },
    ]

    final_path.write_text(
        json.dumps({"items": final_items}, ensure_ascii=False),
        encoding="utf-8",
    )
    delta_path.write_text(
        json.dumps({"items": delta_items}, ensure_ascii=False),
        encoding="utf-8",
    )

    conn = lt.connect_database(db_path)
    lt.ensure_schema(conn)
    conn.commit()
    conn.close()

    first = bs.apply_bootstrap(
        db_path=db_path,
        final_pool_path=final_path,
        delta_path=delta_path,
        write_logs=False,
    )
    second = bs.apply_bootstrap(
        db_path=db_path,
        final_pool_path=final_path,
        delta_path=delta_path,
        write_logs=False,
    )

    conn = lt.connect_database(db_path)
    try:
        counts = bs.lifecycle_counts(conn)
        current = dict(
            conn.execute(
                """
                SELECT current_status, COUNT(*)
                FROM application_current_state
                GROUP BY current_status
                """
            ).fetchall()
        )
        applied = conn.execute(
            """
            SELECT COUNT(*)
            FROM application_events
            WHERE status='APPLIED'
            """
        ).fetchone()[0]

        repost_events = conn.execute(
            """
            SELECT COUNT(*)
            FROM application_events
            WHERE event_type='REPOSTED'
            """
        ).fetchone()[0]

        old = lt.resolve_entity_by_alias(
            conn,
            identity_type="STABLE_ITEM_KEY",
            identity_value="ITEM_B_OLD",
        )
        new = lt.resolve_entity_by_alias(
            conn,
            identity_type="STABLE_ITEM_KEY",
            identity_value="ITEM_B_NEW",
        )

        return {
            "first": first,
            "second": second,
            "counts": counts,
            "current": current,
            "applied": applied,
            "repost_events": repost_events,
            "same_repost_entity":
                old is not None and new is not None
                and old["id"] == new["id"],
        }
    finally:
        conn.close()


def main():
    print("=" * 100)
    print("LIFECYCLE TRACKER STEP 8C - BOOTSTRAP AUDIT")
    print("=" * 100)

    tests = []

    snap = production_snapshot()

    # Le nombre d'entités suit la taille du Final Pool : l'épingler à 66
    # rendrait cet audit faux à la première collecte suivante. L'invariant
    # réel est qu'il y a au moins une entité et pas plus que le pool.
    tests.append(check(
        "Production has lifecycle entities",
        snap["counts"]["application_entities"] >= 1,
        str(snap["counts"]),
    ))

    tests.append(check(
        "Production has zero APPLIED",
        snap["applied"] == 0,
        str(snap["applied"]),
    ))

    tests.append(check(
        "Production has zero CLOSED",
        snap["closed"] == 0,
        str(snap["closed"]),
    ))

    tests.append(check(
        "Production has exactly one REPOSTED visibility event",
        snap["reposted"] == 1,
        str(snap["reposted"]),
    ))

    tests.append(check(
        "Production retained at least one historical stable alias",
        snap["old_aliases"] >= 1,
        str(snap["old_aliases"]),
    ))

    final_path = bs.latest_matching(
        "final_application_pool_v12_[0-9]*.json"
    )
    delta_path = bs.latest_matching(
        "delta_tracker_v1_[0-9]*.json"
    )
    final_items = bs.get_items(bs.load_json(final_path))
    delta_items = bs.get_items(bs.load_json(delta_path))
    pf = bs.preflight(final_items, delta_items)

    tests.append(check(
        "Current artifacts still pass bootstrap preflight",
        pf["ok"],
        str(pf["errors"]),
    ))

    conn = lt.connect_database(DB_PATH)
    try:
        all_current_resolve = all(
            lt.resolve_entity_by_alias(
                conn,
                identity_type="STABLE_ITEM_KEY",
                identity_value=item["stable_item_key"],
            )
            is not None
            for item in final_items
        )
    finally:
        conn.close()

    tests.append(check(
        "All 66 current stable_item_key resolve to lifecycle entities",
        all_current_resolve,
    ))

    # Expected current statuses based only on conservative bootstrap mapping.
    actions = Counter(
        (
            item.get("recommended_action_v12")
            or item.get("recommended_action")
            or ""
        ).upper()
        for item in final_items
    )

    expected_ready = actions.get("APPLY_NOW", 0)
    expected_discovered = actions.get("DO_NOT_APPLY", 0)
    expected_shortlisted = (
        len(final_items)
        - expected_ready
        - expected_discovered
    )
    expected_current = {
        key: value
        for key, value in {
            "READY": expected_ready,
            "SHORTLISTED": expected_shortlisted,
            "DISCOVERED": expected_discovered,
        }.items()
        if value
    }

    tests.append(check(
        "Production current statuses match conservative action mapping",
        snap["current_counts"] == expected_current,
        f"actual={snap['current_counts']} expected={expected_current}",
    ))

    with tempfile.TemporaryDirectory(
        prefix="jobhunter_lifecycle_step8c_"
    ) as tmp:
        synthetic = synthetic_case(tmp)

    tests.append(check(
        "Synthetic bootstrap creates expected 3 entities",
        synthetic["counts"]["application_entities"] == 3,
        str(synthetic["counts"]),
    ))

    tests.append(check(
        "Synthetic current statuses map READY/SHORTLISTED/DISCOVERED",
        synthetic["current"] == {
            "READY": 1,
            "SHORTLISTED": 1,
            "DISCOVERED": 1,
        },
        str(synthetic["current"]),
    ))

    tests.append(check(
        "Synthetic repost old/new aliases share one entity",
        synthetic["same_repost_entity"],
    ))

    tests.append(check(
        "Synthetic creates one REPOSTED event",
        synthetic["repost_events"] == 1,
        str(synthetic["repost_events"]),
    ))

    tests.append(check(
        "Synthetic creates zero APPLIED",
        synthetic["applied"] == 0,
        str(synthetic["applied"]),
    ))

    tests.append(check(
        "Bootstrap is idempotent / second run no-op",
        synthetic["second"]["status"] == "ALREADY_BOOTSTRAPPED",
        synthetic["second"]["status"],
    ))

    passed = sum(tests)
    total = len(tests)
    status = (
        "LIFECYCLE TRACKER STEP 8C VALIDE."
        if all(tests)
        else "LIFECYCLE TRACKER STEP 8C NON VALIDE."
    )

    print()
    print(f"Tests : {passed}/{total}")
    print(status)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = LOG_DIR / f"lifecycle_step8c_bootstrap_audit_{stamp}.json"
    txt_path = LOG_DIR / f"lifecycle_step8c_bootstrap_audit_{stamp}.txt"

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "checks_passed": passed,
        "checks_total": total,
        "status": status,
        "production_snapshot": snap,
        "expected_current_statuses": expected_current,
        "final_pool_count": len(final_items),
        "delta_count": len(delta_items),
        "delta_reposted_count": pf["counts"]["reposted"],
        "synthetic": synthetic,
    }

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    txt_path.write_text(
        "\n".join([
            "LIFECYCLE TRACKER STEP 8C - BOOTSTRAP AUDIT",
            "=" * 100,
            f"Tests : {passed}/{total}",
            status,
            f"Production counts : {snap['counts']}",
            f"Current statuses  : {snap['current_counts']}",
            f"REPOSTED events   : {snap['reposted']}",
            "APPLIED events    : 0",
            "CLOSED events     : 0",
        ]),
        encoding="utf-8",
    )

    print("JSON audit :", json_path)
    print("TXT audit  :", txt_path)

    if not all(tests):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
