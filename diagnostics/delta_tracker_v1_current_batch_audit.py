"""
DELTA TRACKER V1.0 - AUDIT SUR LES DEUX DERNIERS FINAL POOLS

Usage:
    python -m diagnostics.delta_tracker_v1_current_batch_audit

Aucun export.
Aucune DB.
Aucun réseau.
"""

from datetime import datetime
import json
from pathlib import Path

from applications.delta_tracker import (
    CURRENT_STATUSES,
    compare_pools,
    discover_pool_files,
    load_pool,
    resolve_inputs,
)


def check(label, condition, detail=""):
    ok = bool(condition)
    print(f"{'✅' if ok else '❌'} {label}" + (f" | {detail}" if detail else ""))
    return ok


def main():
    tests = []

    print("=" * 100)
    print("DELTA TRACKER V1.0 - AUDIT BATCH ACTUEL")
    print("=" * 100)
    print()

    files = discover_pool_files()
    tests.append(check(
        "Au moins 2 Final Pools V1.2",
        len(files) >= 2,
        str(len(files)),
    ))

    if len(files) < 2:
        raise SystemExit("❌ Deux Final Pools sont nécessaires.")

    current_path, previous_path = resolve_inputs()
    current = load_pool(current_path)
    previous = load_pool(previous_path)

    tests.append(check(
        "Current plus récent que Previous",
        current["timestamp"] > previous["timestamp"],
        f"{previous['timestamp']} -> {current['timestamp']}",
    ))

    result = compare_pools(current_path, previous_path)
    summary = result["summary"]
    records = result["records"]

    current_records = [
        r for r in records
        if r["delta_status"] in CURRENT_STATUSES
    ]
    disappeared = [
        r for r in records
        if r["delta_status"] == "DISAPPEARED"
    ]

    tests.append(check(
        "Current total reconstruit",
        len(current_records) == len(current["pool"])
        == summary["current_total"],
        f"{len(current_records)} / {len(current['pool'])}",
    ))

    shared = summary["UPDATED"] + summary["UNCHANGED"]
    tests.append(check(
        "Previous total reconstruit",
        shared + summary["DISAPPEARED"]
        == len(previous["pool"])
        == summary["previous_total"],
        str(summary),
    ))

    tests.append(check(
        "Aucun item actuel en DISAPPEARED",
        not (
            {r["identity_key"] for r in current_records}
            & {r["identity_key"] for r in disappeared}
        ),
    ))

    tests.append(check(
        "Aucune identité actuelle dupliquée",
        len({r["identity_key"] for r in current_records})
        == len(current_records),
    ))

    tests.append(check(
        "Statuts uniquement autorisés",
        all(
            r["delta_status"]
            in {"NEW", "REACTIVATED", "UPDATED", "UNCHANGED", "DISAPPEARED"}
            for r in records
        ),
    ))

    tests.append(check(
        "DISAPPEARED = Final Pool only",
        all(
            r.get("disappearance_scope") == "FINAL_POOL_ONLY"
            for r in disappeared
        ),
    ))

    tests.append(check(
        "Somme statuts actuels cohérente",
        (
            summary["NEW"]
            + summary["REACTIVATED"]
            + summary["UPDATED"]
            + summary["UNCHANGED"]
        ) == summary["current_total"],
        str(summary),
    ))

    print()
    print("Previous :", previous_path)
    print("Current  :", current_path)
    print()
    print("RÉSULTAT DRY-RUN")
    print("-" * 100)
    for key in (
        "previous_total",
        "current_total",
        "NEW",
        "REACTIVATED",
        "UPDATED",
        "UNCHANGED",
        "DISAPPEARED",
        "new_apply_now",
        "updated_apply_now",
    ):
        print(f"{key:<24}: {summary.get(key)}")

    passed = sum(tests)
    total = len(tests)
    status = (
        "✅ DELTA TRACKER V1.0 VALIDÉ SUR LES DEUX DERNIERS POOLS."
        if all(tests)
        else "❌ DELTA TRACKER V1.0 BATCH ACTUEL NON VALIDÉ."
    )

    print()
    print(f"Checks : {passed}/{total}")
    print(status)

    log_dir = Path(__file__).resolve().parents[1] / "exports" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = log_dir / f"delta_tracker_v1_current_batch_audit_{stamp}.json"
    txt_path = log_dir / f"delta_tracker_v1_current_batch_audit_{stamp}.txt"

    audit_payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "previous_pool": str(previous_path),
        "current_pool": str(current_path),
        "checks_passed": passed,
        "checks_total": total,
        "status": status,
        "summary": summary,
    }
    json_path.write_text(
        json.dumps(audit_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    txt_path.write_text(
        "\n".join([
            "DELTA TRACKER V1.0 - CURRENT BATCH AUDIT",
            "=" * 100,
            f"Previous : {previous_path}",
            f"Current  : {current_path}",
            "",
            f"Checks : {passed}/{total}",
            status,
            "",
            json.dumps(summary, ensure_ascii=False, indent=2),
        ]),
        encoding="utf-8",
    )

    print("JSON audit :", json_path)
    print("TXT audit  :", txt_path)

    if not all(tests):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
