"""
Lifecycle Tracker Step 8F-B — Daily Run integration audit.

No main.py.
No daily_run pipeline execution.
No network.
Production DB read-only.
Behavior tests on temp DB / in-memory manifests.
"""

from __future__ import annotations

import inspect
import json
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


def production_non_user_applied():
    uri = DB_PATH.resolve().as_uri() + "?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    try:
        return conn.execute(
            """
            SELECT COUNT(*)
            FROM application_events
            WHERE
                event_type='STATUS'
                AND status='APPLIED'
                AND actor_type <> 'USER'
            """
        ).fetchone()[0]
    finally:
        conn.close()


def synthetic_wrapper(tmp):
    tmp = Path(tmp)
    db = tmp / "jobs.db"
    final_path = tmp / "final_application_pool_v12_20260819_010234.json"
    delta_path = tmp / "delta_tracker_v1_20260819_012626.json"

    final_payload = {
        "pool_version": "1.2",
        "pool": [
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
            }
        ],
    }
    delta_payload = {
        "delta_tracker_version": "1.1",
        "scope": "FINAL_APPLICATION_POOL_V1.2",
        "inputs": {
            "current_pool": str(final_path.resolve()),
            "previous_pool": str((tmp / "previous.json").resolve()),
        },
        "summary": {
            "current_total": 1,
            "previous_total": 0,
            "NEW": 1,
            "REACTIVATED": 0,
            "REPOSTED": 0,
            "UPDATED": 0,
            "UNCHANGED": 0,
            "DISAPPEARED": 0,
        },
        "records": [
            {
                "identity_key": "ITEM_A",
                "identity_method": "STABLE_ITEM_KEY",
                "delta_status": "NEW",
                "source": "FOREM",
            }
        ],
    }

    final_path.write_text(
        json.dumps(final_payload, ensure_ascii=False),
        encoding="utf-8",
    )
    delta_path.write_text(
        json.dumps(delta_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    conn = lt.connect_database(db)
    lt.ensure_schema(conn)
    conn.commit()
    conn.close()

    # Call core sync directly to avoid writing wrapper artifacts into production LOG_DIR.
    final_items, delta_items = lds.validate_input_lineage(
        final_path,
        delta_path,
    )
    conn = lt.connect_database(db)
    try:
        result = ls.sync_lifecycle(
            conn,
            final_items=final_items,
            delta_items=delta_items,
            sync_token=f"DELTA_ARTIFACT:{delta_path.name}",
            event_at="2026-08-19T01:00:00+00:00",
        )
        post = lds.post_sync_snapshot(conn)
        state = conn.execute(
            """
            SELECT current_status, status_actor_type
            FROM application_current_state
            LIMIT 1
            """
        ).fetchone()
    finally:
        conn.close()

    return result, post, tuple(state)


def main():
    print("=" * 100)
    print("LIFECYCLE TRACKER STEP 8F-B - DAILY RUN INTEGRATION AUDIT")
    print("=" * 100)

    tests = []

    tests.append(check(
        "Daily Run version 1.2.0",
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
        "Pipeline order contains Lifecycle between Delta and Handoff",
        daily_run.STEP_ORDER == expected_order,
        str(daily_run.STEP_ORDER),
    ))

    tests.append(check(
        "Lifecycle wrapper version 1.0",
        lds.LIFECYCLE_DAILY_SYNC_VERSION == "1.0",
        lds.LIFECYCLE_DAILY_SYNC_VERSION,
    ))

    tests.append(check(
        "Lifecycle artifacts are digit-anchored",
        (
            daily_run.ARTIFACT_PATTERNS.get("lifecycle_json")
            == "lifecycle_daily_sync_v1_[0-9]*.json"
            and daily_run.ARTIFACT_PATTERNS.get("lifecycle_txt")
            == "lifecycle_daily_sync_v1_[0-9]*.txt"
        ),
        str({
            "json": daily_run.ARTIFACT_PATTERNS.get("lifecycle_json"),
            "txt": daily_run.ARTIFACT_PATTERNS.get("lifecycle_txt"),
        }),
    ))

    tests.append(check(
        "Preflight requires Lifecycle tracker/sync/wrapper V1.0",
        (
            daily_run.EXPECTED_VERSIONS.get(
                "applications.lifecycle_tracker:LIFECYCLE_VERSION"
            ) == "1.0"
            and daily_run.EXPECTED_VERSIONS.get(
                "applications.lifecycle_sync:LIFECYCLE_SYNC_VERSION"
            ) == "1.0"
            and daily_run.EXPECTED_VERSIONS.get(
                "applications.lifecycle_daily_sync:LIFECYCLE_DAILY_SYNC_VERSION"
            ) == "1.0"
        ),
    ))

    preflight = daily_run.run_preflight()
    tests.append(check(
        "Daily Run V1.2 preflight passes",
        preflight["ok"],
        str(preflight["errors"]),
    ))

    handoff_src = inspect.getsource(daily_run.step_handoff)
    tests.append(check(
        "Handoff requires lifecycle DONE",
        'require_completed(manifest, "lifecycle")' in handoff_src,
    ))

    # Legacy resume test without filesystem writes.
    legacy = {
        "daily_run_version": "1.1.1",
        "run_id": "TEST_RESUME",
        "status": "FAILED",
        "finished_at": None,
        "last_error": "x",
        "resume_count": 2,
        "settings": {
            "preparation_limit": 80,
            "handoff_chunk_size": 10,
            "handoff_enabled": True,
            "stop_after": None,
        },
        "steps": {
            step: empty_step("DONE" if step == "main" else "PENDING")
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
        normalized = daily_run.normalize_manifest_for_resume(legacy)
    finally:
        daily_run.save_manifest = original_save

    tests.append(check(
        "Legacy V1.1.1 resume adds lifecycle PENDING",
        (
            normalized["daily_run_version"] == "1.2.0"
            and normalized["steps"]["main"]["status"] == "DONE"
            and normalized["steps"]["lifecycle"]["status"] == "PENDING"
            and normalized["resume_count"] == 3
        ),
        str({
            "version": normalized["daily_run_version"],
            "main": normalized["steps"]["main"]["status"],
            "lifecycle": normalized["steps"]["lifecycle"]["status"],
            "resume_count": normalized["resume_count"],
        }),
    ))

    # --no-handoff pipeline property, using fake step functions only.
    manifest = {
        "run_id": "TEST_NO_HANDOFF",
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
    original_skip = daily_run.mark_skipped_handoff

    fake_funcs = {}
    for step in daily_run.STEP_ORDER:
        def make_fake(name):
            def fake(m):
                calls.append(name)
                m["steps"][name]["status"] = "DONE"
            return fake
        fake_funcs[step] = make_fake(step)

    daily_run.STEP_FUNCTIONS = fake_funcs
    daily_run.save_manifest = lambda m: None

    try:
        result = daily_run.run_pipeline(manifest)
    finally:
        daily_run.STEP_FUNCTIONS = original_funcs
        daily_run.save_manifest = original_save

    tests.append(check(
        "--no-handoff still executes lifecycle and skips only handoff",
        (
            "lifecycle" in calls
            and "handoff" not in calls
            and result["steps"]["handoff"]["status"] == "SKIPPED"
            and result["status"] == "COMPLETED"
        ),
        str({"calls": calls, "handoff": result["steps"]["handoff"]["status"]}),
    ))

    # Direct handoff guard should fail before any artifacts are touched.
    guard_manifest = {
        "steps": {
            "final_pool": empty_step("DONE"),
            "delta": empty_step("DONE"),
            "lifecycle": empty_step("PENDING"),
            "handoff": empty_step("PENDING"),
        },
        "settings": {"handoff_chunk_size": 10},
    }
    guard_ok = False
    try:
        daily_run.step_handoff(guard_manifest)
    except RuntimeError as exc:
        guard_ok = "lifecycle=PENDING" in str(exc)
    tests.append(check(
        "Handoff refuses lifecycle not DONE",
        guard_ok,
    ))

    with tempfile.TemporaryDirectory(
        prefix="jobhunter_step8f_b_"
    ) as tmp:
        sync_result, post, state = synthetic_wrapper(tmp)

    tests.append(check(
        "Synthetic Lifecycle sync creates READY, never APPLIED",
        (
            state[0] == "READY"
            and state[1] == "SYSTEM"
            and post["applied_total"] == 0
            and post["non_user_applied"] == 0
        ),
        str({"state": state, "post": post}),
    ))

    tests.append(check(
        "Production has zero non-USER APPLIED",
        production_non_user_applied() == 0,
    ))

    passed = sum(tests)
    total = len(tests)
    status = (
        "LIFECYCLE TRACKER STEP 8F-B VALIDE."
        if all(tests)
        else "LIFECYCLE TRACKER STEP 8F-B NON VALIDE."
    )

    print()
    print(f"Tests : {passed}/{total}")
    print(status)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = LOG_DIR / f"lifecycle_step8f_b_daily_run_audit_{stamp}.json"
    txt_path = LOG_DIR / f"lifecycle_step8f_b_daily_run_audit_{stamp}.txt"

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "checks_passed": passed,
        "checks_total": total,
        "status": status,
        "daily_run_version": daily_run.DAILY_RUN_VERSION,
        "step_order": daily_run.STEP_ORDER,
        "preflight_ok": preflight["ok"],
        "preflight_errors": preflight["errors"],
        "rules": {
            "lifecycle_after_delta": True,
            "lifecycle_before_handoff": True,
            "no_handoff_still_runs_lifecycle": True,
            "legacy_resume_supported": True,
            "handoff_requires_lifecycle_done": True,
            "non_user_applied_must_be_zero": True,
        },
    }

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    txt_path.write_text(
        "\n".join([
            "LIFECYCLE TRACKER STEP 8F-B - DAILY RUN AUDIT",
            "=" * 100,
            f"Tests : {passed}/{total}",
            status,
            f"Daily Run version : {daily_run.DAILY_RUN_VERSION}",
            f"Step order        : {daily_run.STEP_ORDER}",
            f"Preflight         : {preflight['ok']}",
        ]),
        encoding="utf-8",
    )

    print("JSON audit :", json_path)
    print("TXT audit  :", txt_path)

    if not all(tests):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
