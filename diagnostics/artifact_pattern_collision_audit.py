"""
HARDENING STEP 1 - ARTIFACT PATTERN COLLISION AUDIT

Usage:
    python -m diagnostics.artifact_pattern_collision_audit

No network.
No collection.
No DB write.
"""

from __future__ import annotations

import fnmatch
import json
from datetime import datetime
from pathlib import Path

import daily_run


CASES = {
    "main_log": (
        "job_hunter_main_v10_4_1_20260819_004232.txt",
        [
            "job_hunter_main_v10_4_audit_20260819_004232.txt",
            "job_hunter_main_v10_4_current_batch_audit_20260819_004232.txt",
        ],
    ),
    "gate_json": (
        "application_gate_v1_20260819_005210.json",
        [
            "application_gate_v1_audit_20260819_005210.json",
            "application_gate_v1_current_batch_audit_20260819_005210.json",
        ],
    ),
    "queue_json": (
        "application_queue_v1_20260819_005213.json",
        [
            "application_queue_v1_audit_20260819_005213.json",
            "application_queue_v1_current_batch_audit_20260819_005213.json",
        ],
    ),
    "preparation_json": (
        "application_preparation_v1_20260819_005610.json",
        [
            "application_preparation_v1_audit_20260819_005610.json",
            "application_preparation_v1_current_batch_audit_20260819_005610.json",
        ],
    ),
    "preparation_txt": (
        "application_preparation_v1_20260819_005610.txt",
        [
            "application_preparation_v1_audit_20260819_005610.txt",
            "application_preparation_v1_current_batch_audit_20260819_005610.txt",
        ],
    ),
    "refresh_json": (
        "job_refresh_v1_20260819_010001.json",
        [
            "job_refresh_v1_audit_20260819_010001.json",
            "job_refresh_v1_post_upgrade_audit_20260819_010001.json",
        ],
    ),
    "refresh_txt": (
        "job_refresh_v1_20260819_010001.txt",
        [
            "job_refresh_v1_audit_20260819_010001.txt",
            "job_refresh_v1_post_upgrade_audit_20260819_010001.txt",
        ],
    ),
    "recheck_json": (
        "application_recheck_v1_20260819_010100.json",
        [
            "application_recheck_v1_audit_20260819_010100.json",
            "application_recheck_v1_current_batch_audit_20260819_010100.json",
        ],
    ),
    "recheck_txt": (
        "application_recheck_v1_20260819_010100.txt",
        [
            "application_recheck_v1_audit_20260819_010100.txt",
            "application_recheck_v1_current_batch_audit_20260819_010100.txt",
        ],
    ),
    "final_pool_json": (
        "final_application_pool_v12_20260819_010234.json",
        [
            "final_application_pool_v12_audit_20260819_010234.json",
            "final_application_pool_v12_current_batch_audit_20260819_010234.json",
        ],
    ),
    "final_pool_txt": (
        "final_application_pool_v12_20260819_010234.txt",
        [
            "final_application_pool_v12_audit_20260819_010234.txt",
            "final_application_pool_v12_current_batch_audit_20260819_010234.txt",
        ],
    ),
    "final_pool_csv": (
        "final_application_pool_v12_20260819_010234.csv",
        [
            "final_application_pool_v12_audit_20260819_010234.csv",
            "final_application_pool_v12_current_batch_audit_20260819_010234.csv",
        ],
    ),
    "delta_json": (
        "delta_tracker_v1_20260819_012626.json",
        [
            "delta_tracker_v1_audit_20260819_012626.json",
            "delta_tracker_v1_current_batch_audit_20260819_012621.json",
        ],
    ),
    "delta_txt": (
        "delta_tracker_v1_20260819_012626.txt",
        [
            "delta_tracker_v1_audit_20260819_012626.txt",
            "delta_tracker_v1_current_batch_audit_20260819_012621.txt",
        ],
    ),
    "delta_csv": (
        "delta_tracker_v1_20260819_012626.csv",
        [
            "delta_tracker_v1_audit_20260819_012626.csv",
            "delta_tracker_v1_current_batch_audit_20260819_012621.csv",
        ],
    ),
}


def check(label, condition, detail=""):
    ok = bool(condition)
    print(f"{'✅' if ok else '❌'} {label}" + (f" | {detail}" if detail else ""))
    return ok


def main():
    print("=" * 100)
    print("HARDENING STEP 1 - ARTIFACT PATTERN COLLISION AUDIT")
    print("=" * 100)
    print()
    print("Daily Run installé :", daily_run.DAILY_RUN_VERSION)
    print()

    tests = []
    details = {}

    for name, (real_name, audit_names) in CASES.items():
        pattern = daily_run.ARTIFACT_PATTERNS.get(name)

        real_match = bool(pattern) and fnmatch.fnmatch(real_name, pattern)
        audits_rejected = bool(pattern) and all(
            not fnmatch.fnmatch(audit_name, pattern)
            for audit_name in audit_names
        )
        digit_anchor = bool(pattern) and "[0-9]*" in pattern

        ok = real_match and audits_rejected and digit_anchor
        tests.append(check(
            name,
            ok,
            f"{pattern} | real={real_match} | audits_rejected={audits_rejected}",
        ))

        details[name] = {
            "pattern": pattern,
            "real_filename": real_name,
            "real_matches": real_match,
            "audit_filenames": audit_names,
            "audits_rejected": audits_rejected,
            "digit_anchor_present": digit_anchor,
        }

    # Scan actual logs too: any currently matched file containing "audit"
    # indicates a regression in the installed patterns.
    polluted = {}
    for name, pattern in daily_run.ARTIFACT_PATTERNS.items():
        matched = [
            p.name
            for p in daily_run.LOG_DIR.glob(pattern)
            if p.is_file() and "audit" in p.name.lower()
        ]
        if matched:
            polluted[name] = matched

    tests.append(check(
        "Aucun fichier audit capturé dans exports/logs",
        not polluted,
        json.dumps(polluted, ensure_ascii=False),
    ))

    passed = sum(tests)
    total = len(tests)
    status = (
        "✅ HARDENING STEP 1 VALIDÉ."
        if all(tests)
        else "❌ HARDENING STEP 1 NON VALIDÉ."
    )

    print()
    print(f"Tests : {passed}/{total}")
    print(status)

    log_dir = Path(__file__).resolve().parents[1] / "exports" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = log_dir / f"artifact_pattern_collision_audit_{stamp}.json"
    txt_path = log_dir / f"artifact_pattern_collision_audit_{stamp}.txt"

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "daily_run_version_observed": str(daily_run.DAILY_RUN_VERSION),
        "checks_passed": passed,
        "checks_total": total,
        "status": status,
        "patterns": details,
        "polluted_actual_matches": polluted,
    }

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    txt_path.write_text(
        "\n".join([
            "HARDENING STEP 1 - ARTIFACT PATTERN COLLISION AUDIT",
            "=" * 100,
            f"Daily Run : {daily_run.DAILY_RUN_VERSION}",
            f"Tests : {passed}/{total}",
            status,
            f"Polluted actual matches : {json.dumps(polluted, ensure_ascii=False)}",
        ]),
        encoding="utf-8",
    )

    print("JSON audit :", json_path)
    print("TXT audit  :", txt_path)

    if not all(tests):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
