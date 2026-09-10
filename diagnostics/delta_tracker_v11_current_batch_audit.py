"""
DELTA TRACKER V1.1 - AUDIT DU BATCH ACTUEL

Usage:
    python -m diagnostics.delta_tracker_v11_current_batch_audit

Aucun export. Aucun réseau.
"""

from datetime import datetime
import json
from pathlib import Path

from applications.delta_tracker import compare_pools, resolve_inputs


def check(label, condition, detail=""):
    ok = bool(condition)
    print(f"{'✅' if ok else '❌'} {label}" + (f" | {detail}" if detail else ""))
    return ok


def main():
    print("=" * 100)
    print("DELTA TRACKER V1.1 - CURRENT BATCH AUDIT")
    print("=" * 100)
    print()

    current, previous = resolve_inputs()
    result = compare_pools(current, previous)
    s = result["summary"]

    tests = []
    tests.append(check(
        "Somme current cohérente",
        (
            s["NEW"] + s["REACTIVATED"] + s["REPOSTED"]
            + s["UPDATED"] + s["UNCHANGED"]
        ) == s["current_total"],
        str(s),
    ))
    tests.append(check(
        "Reconstruction previous cohérente",
        (
            s["REPOSTED"] + s["UPDATED"] + s["UNCHANGED"]
            + s["DISAPPEARED"]
        ) == s["previous_total"],
        str(s),
    ))

    print()
    for key in (
        "previous_total",
        "current_total",
        "NEW",
        "REACTIVATED",
        "REPOSTED",
        "UPDATED",
        "UNCHANGED",
        "DISAPPEARED",
        "new_apply_now",
        "reposted_apply_now",
        "updated_apply_now",
    ):
        print(f"{key:<24}: {s.get(key)}")

    passed = sum(tests)
    total = len(tests)
    status = (
        "✅ DELTA TRACKER V1.1 CURRENT BATCH VALIDÉ."
        if all(tests)
        else "❌ CURRENT BATCH V1.1 NON VALIDÉ."
    )

    print()
    print(f"Checks : {passed}/{total}")
    print(status)

    log_dir = Path(__file__).resolve().parents[1] / "exports" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = log_dir / f"delta_tracker_v11_current_batch_audit_{stamp}.json"
    txt_path = log_dir / f"delta_tracker_v11_current_batch_audit_{stamp}.txt"

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "previous_pool": str(previous),
        "current_pool": str(current),
        "checks_passed": passed,
        "checks_total": total,
        "status": status,
        "summary": s,
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    txt_path.write_text(
        "\n".join([
            "DELTA TRACKER V1.1 - CURRENT BATCH AUDIT",
            "=" * 100,
            f"Previous : {previous}",
            f"Current  : {current}",
            "",
            f"Checks : {passed}/{total}",
            status,
            "",
            json.dumps(s, ensure_ascii=False, indent=2),
        ]),
        encoding="utf-8",
    )

    print("JSON audit :", json_path)
    print("TXT audit  :", txt_path)

    if not all(tests):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
